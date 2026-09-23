"""Model contracts, loss behaviour, and the overfit-one-batch sanity check.

CLAUDE.md §3 is explicit about why these exist:

    *"Every module gets smoke-tested locally on tiny crops first — shape
    assertions, one forward pass, one backward pass, a 2-epoch
    overfit-on-one-batch sanity check. [...] If the model cannot memorise one
    batch, it will not learn 52 years of river."*

Every test here runs on a 64x64 crop so the whole file finishes in seconds on
CPU. The point is not performance, it is catching a broken contract before any
paid A100 time is booked.
"""

from __future__ import annotations

import pytest
import torch

from jamunarekha.models.baselines import ConvLSTMForecaster, PersistenceForecaster
from jamunarekha.models.losses import ErosionForecastLoss, SpatialGradientLoss
from jamunarekha.models.timesformer import TimeSformerForecaster

from .synthetic import river_batch

IMG = 64
T_IN, T_OUT, BATCH = 12, 3, 2


def _tiny_timesformer() -> TimeSformerForecaster:
    return TimeSformerForecaster(
        in_frames=T_IN, out_frames=T_OUT, img_size=IMG, patch_size=16,
        embed_dim=64, depth=2, num_heads=4, decoder_channels=[32, 16], dropout=0.0,
    )


def _models():
    return {
        "timesformer": _tiny_timesformer(),
        "convlstm": ConvLSTMForecaster(
            in_frames=T_IN, out_frames=T_OUT, hidden_channels=16, num_layers=1
        ),
        "persistence": PersistenceForecaster(out_frames=T_OUT),
    }


def _batch(seed: int = 0):
    """A batch of migrating synthetic rivers.

    Deliberately NOT random noise. With independent random targets there is no
    function from input to output to learn, so an "overfit one batch" test
    would only measure raw memorisation capacity and a small model would fail
    it for the wrong reason. A drifting channel has the structure the real task
    has, so failing to fit it means something is genuinely broken.
    """
    return river_batch(
        batch=BATCH, in_frames=T_IN, out_frames=T_OUT, size=IMG, seed=seed + 1
    )


# ------------------------------------------------------------ shape contract
@pytest.mark.parametrize("name", ["timesformer", "convlstm", "persistence"])
def test_forward_shape_is_identical_across_models(name):
    """All three must be drop-in replaceable — that is the whole point of the
    shared interface (CLAUDE.md §2)."""
    model = _models()[name]
    x, _, _ = _batch()
    out = model(x)
    assert out.shape == (BATCH, T_OUT, 1, IMG, IMG)
    assert out.dtype == torch.float32
    assert torch.isfinite(out).all()


@pytest.mark.parametrize("name", ["timesformer", "convlstm"])
def test_backward_produces_gradients(name):
    model = _models()[name]
    x, y, valid = _batch()
    loss = ErosionForecastLoss(gradient_weight=0.3)(model(x), y, valid)["loss"]
    loss.backward()
    grads = [p.grad for p in model.parameters() if p.requires_grad and p.grad is not None]
    assert grads, "no parameter received a gradient"
    assert any(g.abs().sum() > 0 for g in grads), "all gradients are exactly zero"


@pytest.mark.parametrize("name", ["timesformer", "convlstm", "persistence"])
def test_wrong_input_length_is_rejected(name):
    """A silently-accepted wrong sequence length would train on nonsense."""
    model = _models()[name]
    bad = torch.rand(BATCH, T_IN - 1, 1, IMG, IMG)
    if name == "persistence":
        pytest.skip("persistence reads only the last frame, any length is valid")
    with pytest.raises(ValueError):
        model(bad)


def test_persistence_really_repeats_the_last_frame():
    model = PersistenceForecaster(out_frames=T_OUT)
    x, _, _ = _batch()
    probs = torch.sigmoid(model(x))
    for horizon in range(T_OUT):
        assert torch.allclose(probs[:, horizon] > 0.5, x[:, -1] > 0.5)


def test_timesformer_output_actually_depends_on_the_input():
    """Guards against a decoder that has learned to ignore the encoder."""
    model = _tiny_timesformer().eval()
    x1, _, _ = _batch(seed=1)
    x2, _, _ = _batch(seed=2)
    with torch.no_grad():
        assert not torch.allclose(model(x1), model(x2))


# -------------------------------------------------------------------- losses
def test_gradient_loss_is_zero_for_an_identical_pair():
    frame = torch.zeros(1, 1, 32, 32)
    frame[:, :, :, :16] = 1.0
    assert SpatialGradientLoss()(frame, frame).item() == pytest.approx(0.0, abs=1e-6)


def test_bce_alone_rewards_hedging_and_the_gradient_term_does_not():
    """The reason the 0.3 Sobel term exists at all.

    Two ways to be wrong about a shoreline:

    *blurred* — the bank is in the right place but smeared over six columns,
    the model hedging where it is least certain;
    *displaced* — the bank is perfectly sharp but two pixels off.

    For a forecast that has to answer *where will the bank be*, the displaced
    prediction is the more useful of the two: it names a position. BCE ranks
    them the other way round, and by a wide margin, because hedging costs it
    almost nothing. The Sobel term charges both roughly equally, which removes
    the incentive to smear.

    Measured on this fixture: BCE 0.133 blurred vs 0.863 displaced (6.5x), and
    gradient 0.129 vs 0.124 (1.04x).
    """
    sharp = torch.zeros(1, 1, 32, 32)
    sharp[:, :, :, :16] = 1.0

    blurred = sharp.clone()
    for offset, value in ((13, 0.15), (14, 0.35), (15, 0.6), (16, 0.4), (17, 0.2), (18, 0.05)):
        blurred[:, :, :, offset] = value

    displaced = torch.zeros(1, 1, 32, 32)
    displaced[:, :, :, :18] = 1.0

    def bce(pred):
        return torch.nn.functional.binary_cross_entropy(
            pred.clamp(1e-6, 1 - 1e-6), sharp
        ).item()

    grad = SpatialGradientLoss()
    bce_ratio = bce(blurred) / bce(displaced)
    grad_ratio = grad(blurred, sharp).item() / grad(displaced, sharp).item()

    assert bce_ratio < 0.25, "BCE should strongly prefer the hedged prediction"
    assert 0.8 < grad_ratio < 1.25, "the gradient term should treat them comparably"
    assert grad(sharp, sharp).item() < 1e-6


def test_loss_respects_the_validity_mask():
    """Errors on interpolated pixels must not be charged to the model."""
    logits = torch.full((1, 1, 1, 16, 16), -5.0)
    target = torch.ones(1, 1, 1, 16, 16)
    criterion = ErosionForecastLoss(gradient_weight=0.3)

    all_valid = criterion(logits, target, torch.ones_like(target))["loss"]
    none_valid = criterion(logits, target, torch.zeros_like(target))["loss"]
    assert all_valid.item() > 1.0
    assert none_valid.item() == pytest.approx(0.0, abs=1e-6)


def test_loss_components_are_reported_separately():
    x, y, valid = _batch()
    parts = ErosionForecastLoss(gradient_weight=0.3)(_tiny_timesformer()(x), y, valid)
    assert set(parts) == {"loss", "bce", "grad"}
    assert parts["loss"].item() == pytest.approx(
        parts["bce"].item() + 0.3 * parts["grad"].item(), rel=1e-5
    )


# ------------------------------------------------------ overfit a single batch
@pytest.mark.parametrize("name", ["timesformer", "convlstm"])
def test_model_can_overfit_one_batch(name):
    """The gate before any cloud run.

    If a model cannot drive the loss down on a single fixed batch it has a
    broken gradient path, and no amount of A100 time will fix that.
    """
    torch.manual_seed(1972)
    model = _models()[name]
    x, y, valid = _batch(seed=7)
    criterion = ErosionForecastLoss(gradient_weight=0.3)
    optimiser = torch.optim.AdamW(model.parameters(), lr=3e-3)

    first = last = None
    for step in range(60):
        optimiser.zero_grad()
        loss = criterion(model(x), y, valid)["loss"]
        loss.backward()
        optimiser.step()
        if step == 0:
            first = loss.item()
        last = loss.item()

    assert last < first * 0.5, (
        f"{name} failed to overfit one batch: {first:.4f} -> {last:.4f}"
    )
