"""The LightningModule shared by every model in Stage 3.

One contract for all three architectures (CLAUDE.md §2), so the training and
evaluation harness never branches on which model it is holding. Swapping
``model.name`` in the config between ``timesformer``, ``convlstm`` and
``persistence`` is the only change needed to run a different arm of the
comparison.

Checkpointing is per-epoch and resumable by design. The project has roughly 30
A100-hours in total and a crashed un-resumable run is burnt budget
(CLAUDE.md §3), so the Trainer built by :func:`build_trainer` always writes
``last.ckpt`` and always restores the optimiser and scheduler state.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytorch_lightning as pl
import torch
from torch import Tensor

from jamunarekha.models.baselines import ConvLSTMForecaster, PersistenceForecaster
from jamunarekha.models.losses import ErosionForecastLoss
from jamunarekha.models.metrics import MetricAccumulator
from jamunarekha.models.timesformer import TimeSformerForecaster

MODELS = {
    "timesformer": TimeSformerForecaster,
    "convlstm": ConvLSTMForecaster,
    "persistence": PersistenceForecaster,
}


def build_model(cfg) -> torch.nn.Module:
    """Instantiate the architecture named by ``cfg.model.name``.

    Raises
    ------
    KeyError
        On an unknown name — a typo in a config should stop the run, not
        silently fall through to a default.
    """
    name = str(cfg.model.name).lower()
    if name not in MODELS:
        raise KeyError(f"unknown model {name!r}; known: {sorted(MODELS)}")

    common = dict(
        in_frames=int(cfg.data.in_frames),
        out_frames=int(cfg.data.out_frames),
    )
    if name == "timesformer":
        return TimeSformerForecaster(
            img_size=int(cfg.data.crop_size),
            patch_size=int(cfg.model.patch_size),
            embed_dim=int(cfg.model.embed_dim),
            depth=int(cfg.model.depth),
            num_heads=int(cfg.model.num_heads),
            decoder_channels=list(cfg.model.decoder_channels),
            dropout=float(cfg.model.dropout),
            **common,
        )
    if name == "convlstm":
        return ConvLSTMForecaster(
            hidden_channels=int(cfg.model.get("hidden_channels", 64)),
            num_layers=int(cfg.model.get("num_layers", 2)),
            **common,
        )
    return PersistenceForecaster(**common)


class JamunaForecastModule(pl.LightningModule):
    """Train and evaluate any of the three forecasters.

    Parameters
    ----------
    cfg
        The merged run config. Stored in the checkpoint via
        ``save_hyperparameters`` so a checkpoint is self-describing — including
        the random seed, which CLAUDE.md §4 requires be recorded with the run.
    pos_weight
        BCE positive-class weight. Computed from the training split by the
        caller and passed in, so it is recorded in the checkpoint too.
    """

    def __init__(self, cfg, pos_weight: float | None = None) -> None:
        super().__init__()
        self.save_hyperparameters({"cfg": _to_container(cfg), "pos_weight": pos_weight})
        self.cfg = cfg
        self.model = build_model(cfg)
        self.criterion = ErosionForecastLoss(
            bce_weight=float(cfg.loss.bce_weight),
            gradient_weight=float(cfg.loss.gradient_weight),
            pos_weight=pos_weight,
        )
        self.resolution_m = float(cfg.study_area.resolution_m)
        self._val_metrics: MetricAccumulator | None = None
        self._test_metrics: MetricAccumulator | None = None
        self._test_rows: list[dict] = []

    # ------------------------------------------------------------- plumbing
    def forward(self, x: Tensor) -> Tensor:
        return self.model(x)

    def _step(self, batch: dict, stage: str) -> dict[str, Tensor]:
        logits = self(batch["x"])
        parts = self.criterion(logits, batch["y"], batch["y_valid"])
        batch_size = batch["x"].shape[0]
        self.log(f"{stage}/loss", parts["loss"], prog_bar=True, batch_size=batch_size)
        self.log(f"{stage}/bce", parts["bce"], batch_size=batch_size)
        self.log(f"{stage}/grad", parts["grad"], batch_size=batch_size)
        return {"logits": logits, **parts}

    def training_step(self, batch: dict, batch_idx: int) -> Tensor:
        return self._step(batch, "train")["loss"]

    # ------------------------------------------------------------ validation
    def on_validation_epoch_start(self) -> None:
        self._val_metrics = MetricAccumulator(resolution_m=self.resolution_m)

    def validation_step(self, batch: dict, batch_idx: int) -> None:
        out = self._step(batch, "val")
        self._accumulate(self._val_metrics, out["logits"], batch)

    def on_validation_epoch_end(self) -> None:
        if self._val_metrics is None:
            return
        for key, value in self._val_metrics.compute().items():
            if key == "n_frames":
                continue
            self.log(f"val/{key}", value, prog_bar=(key in {"iou", "bank_f1"}))

    # ------------------------------------------------------------------ test
    def on_test_epoch_start(self) -> None:
        self._test_metrics = MetricAccumulator(resolution_m=self.resolution_m)
        self._test_rows = []

    def test_step(self, batch: dict, batch_idx: int) -> None:
        out = self._step(batch, "test")
        self._accumulate(self._test_metrics, out["logits"], batch)

        # Per-horizon breakdown: does month +3 degrade relative to month +1?
        probs = torch.sigmoid(out["logits"]).detach().cpu().numpy()
        target = batch["y"].detach().cpu().numpy()
        valid = batch["y_valid"].detach().cpu().numpy()
        for horizon in range(probs.shape[1]):
            acc = MetricAccumulator(resolution_m=self.resolution_m)
            acc.update(probs[:, horizon] > 0.5, target[:, horizon] > 0.5, valid[:, horizon] > 0.5)
            row = acc.compute()
            row["horizon_months"] = horizon + 1
            self._test_rows.append(row)

    def on_test_epoch_end(self) -> None:
        if self._test_metrics is None:
            return
        for key, value in self._test_metrics.compute().items():
            if key == "n_frames":
                continue
            self.log(f"test/{key}", value)

    def horizon_table(self) -> list[dict]:
        """Per-horizon metrics collected during ``test``, averaged over batches."""
        if not self._test_rows:
            return []
        table = []
        for horizon in sorted({r["horizon_months"] for r in self._test_rows}):
            rows = [r for r in self._test_rows if r["horizon_months"] == horizon]
            entry = {"horizon_months": horizon}
            for key in ("iou", "bank_f1", "bank_precision", "bank_recall", "mde_m"):
                values = [r[key] for r in rows if np.isfinite(r[key])]
                entry[key] = float(np.mean(values)) if values else float("nan")
            table.append(entry)
        return table

    @staticmethod
    def _accumulate(acc: MetricAccumulator | None, logits: Tensor, batch: dict) -> None:
        if acc is None:
            return
        probs = torch.sigmoid(logits).detach().cpu().numpy()
        target = batch["y"].detach().cpu().numpy()
        valid = batch["y_valid"].detach().cpu().numpy()
        acc.update(probs > 0.5, target > 0.5, valid > 0.5)

    # -------------------------------------------------------------- optimiser
    def configure_optimizers(self):
        params = [p for p in self.model.parameters() if p.requires_grad]
        optimiser = torch.optim.AdamW(
            params,
            lr=float(self.cfg.train.lr),
            weight_decay=float(self.cfg.train.weight_decay),
        )
        scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(
            optimiser, T_max=max(1, int(self.cfg.train.max_epochs))
        )
        return {"optimizer": optimiser, "lr_scheduler": scheduler}


def _to_container(cfg):
    """Best-effort conversion of an OmegaConf node to a plain dict for hparams."""
    try:
        from omegaconf import OmegaConf

        return OmegaConf.to_container(cfg, resolve=True)
    except Exception:  # noqa: BLE001
        return dict(cfg)


def build_trainer(cfg, run_name: str, logger: bool = True) -> pl.Trainer:
    """Trainer configured for a resumable, per-epoch-checkpointed run.

    Parameters
    ----------
    cfg
        Merged config.
    run_name
        Subdirectory under ``outputs/checkpoints`` for this run.
    logger
        Whether to attach the CSV logger. Off for smoke tests.
    """
    from pytorch_lightning.callbacks import (
        EarlyStopping,
        LearningRateMonitor,
        ModelCheckpoint,
    )
    from pytorch_lightning.loggers import CSVLogger

    ckpt_dir = Path(cfg.paths.checkpoints) / run_name
    ckpt_dir.mkdir(parents=True, exist_ok=True)

    callbacks: list = [
        ModelCheckpoint(
            dirpath=str(ckpt_dir),
            filename="epoch{epoch:03d}-valf1{val/bank_f1:.4f}",
            auto_insert_metric_name=False,
            monitor="val/bank_f1",
            mode="max",
            save_top_k=3,
            save_last=True,          # last.ckpt is what a resumed run reads
            every_n_epochs=1,
        ),
        LearningRateMonitor(logging_interval="epoch"),
    ]
    patience = int(cfg.train.get("early_stop_patience", 0) or 0)
    if patience > 0:
        callbacks.append(
            EarlyStopping(monitor="val/bank_f1", mode="max", patience=patience)
        )

    return pl.Trainer(
        max_epochs=int(cfg.train.max_epochs),
        accelerator=str(cfg.train.accelerator),
        precision=str(cfg.train.precision),
        gradient_clip_val=float(cfg.train.grad_clip),
        accumulate_grad_batches=int(cfg.train.accumulate_grad_batches),
        callbacks=callbacks,
        logger=CSVLogger(save_dir=str(cfg.paths.logs), name=run_name) if logger else False,
        log_every_n_steps=10,
        enable_progress_bar=True,
        num_sanity_val_steps=0,
    )
