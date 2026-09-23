"""Stage 3 entry point — train and evaluate one forecaster.

    python scripts/run_stage3_train.py --config local.yaml --model timesformer
    python scripts/run_stage3_train.py --config local.yaml --model convlstm
    python scripts/run_stage3_train.py --config local.yaml --model persistence --eval-only
    python scripts/run_stage3_train.py --resume

Writes checkpoints to ``outputs/checkpoints/<run>/`` every epoch and a metrics
JSON to ``outputs/tables/``. Runs are resumable from ``last.ckpt``: the GPU
budget is about 30 A100-hours in total and a crashed un-resumable run is burnt
budget (CLAUDE.md §3).

The wall-clock seconds per epoch printed at the end is not decoration. It is
the number used to estimate A100 time *before* booking it, which CLAUDE.md §3
requires.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import torch
from torch.utils.data import DataLoader

from jamunarekha.data.dataset import JamunaShift52Y
from jamunarekha.models.lit_module import JamunaForecastModule, build_trainer
from jamunarekha.utils.config import load_config
from jamunarekha.utils.logging import get_logger
from jamunarekha.utils.seed import seed_everything


def build_loaders(cfg) -> dict[str, DataLoader]:
    """Train/val/test loaders over JamunaShift-52Y."""
    common = dict(
        processed_dir=cfg.paths.data_processed,
        in_frames=int(cfg.data.in_frames),
        out_frames=int(cfg.data.out_frames),
        crop_size=int(cfg.data.crop_size),
        train_end_year=int(cfg.data.split.train_end_year),
        window_stride=int(cfg.data.get("window_stride", 1)),
        max_windows=int(cfg.data.get("max_val_windows", 0)) or None,
        val_end_year=int(cfg.data.split.val_end_year),
        seed=int(cfg.project.seed),
    )
    datasets = {split: JamunaShift52Y(split=split, **common) for split in ("train", "val", "test")}
    loaders = {
        split: DataLoader(
            dataset,
            batch_size=int(cfg.data.batch_size),
            shuffle=(split == "train"),
            num_workers=int(cfg.data.num_workers),
            drop_last=(split == "train"),
            persistent_workers=bool(int(cfg.data.num_workers) > 0),
        )
        for split, dataset in datasets.items()
    }
    loaders["_datasets"] = datasets  # type: ignore[assignment]
    return loaders


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="local.yaml")
    parser.add_argument("--model", default=None, choices=["timesformer", "convlstm", "persistence"])
    parser.add_argument("--epochs", type=int, default=None)
    parser.add_argument("--run-name", default=None)
    parser.add_argument("--resume", action="store_true", help="continue from last.ckpt")
    parser.add_argument("--eval-only", action="store_true", help="skip fit, just test")
    parser.add_argument("--threads", type=int, default=None, help="torch CPU threads")
    args = parser.parse_args()

    cfg = load_config(args.config)
    if args.model:
        cfg.model.name = args.model
    if args.epochs is not None:
        cfg.train.max_epochs = args.epochs
    if args.threads:
        torch.set_num_threads(args.threads)

    run_name = args.run_name or f"{cfg.model.name}_crop{cfg.data.crop_size}"
    logger = get_logger("jamunarekha.stage3", cfg.paths.logs)
    seed_everything(int(cfg.project.seed))
    logger.info("run=%s model=%s seed=%d threads=%d",
                run_name, cfg.model.name, cfg.project.seed, torch.get_num_threads())

    loaders = build_loaders(cfg)
    datasets = loaders.pop("_datasets")
    for split, dataset in datasets.items():
        logger.info("%-5s: %d windows", split, len(dataset))
    if len(datasets["train"]) == 0:
        logger.error("empty training split — run Stage 2 first")
        return 1

    pos_weight = cfg.loss.pos_weight
    if pos_weight is None:
        pos_weight = datasets["train"].positive_weight()
        logger.info("pos_weight estimated from the training split: %.3f", pos_weight)

    module = JamunaForecastModule(cfg, pos_weight=float(pos_weight))
    n_params = sum(p.numel() for p in module.model.parameters() if p.requires_grad)
    logger.info("%s: %.2f M trainable parameters", cfg.model.name, n_params / 1e6)

    trainer = build_trainer(cfg, run_name)
    ckpt_dir = Path(cfg.paths.checkpoints) / run_name
    last_ckpt = ckpt_dir / "last.ckpt"
    resume_from = str(last_ckpt) if (args.resume and last_ckpt.exists()) else None
    if resume_from:
        logger.info("resuming from %s", resume_from)

    seconds_per_epoch = float("nan")
    if not args.eval_only:
        started = time.time()
        trainer.fit(
            module,
            train_dataloaders=loaders["train"],
            val_dataloaders=loaders["val"],
            ckpt_path=resume_from,
        )
        elapsed = time.time() - started
        epochs_run = max(1, trainer.current_epoch)
        seconds_per_epoch = elapsed / epochs_run
        logger.info(
            "training wall clock: %.1f s over %d epochs = %.1f s/epoch",
            elapsed, epochs_run, seconds_per_epoch,
        )

    results = trainer.test(module, dataloaders=loaders["test"], verbose=False)
    metrics = {k: float(v) for k, v in (results[0] if results else {}).items()}

    record = {
        "run_name": run_name,
        "model": str(cfg.model.name),
        "crop_size": int(cfg.data.crop_size),
        "in_frames": int(cfg.data.in_frames),
        "out_frames": int(cfg.data.out_frames),
        "seed": int(cfg.project.seed),
        "gradient_weight": float(cfg.loss.gradient_weight),
        "pos_weight": float(pos_weight),
        "trainable_params": int(n_params),
        "epochs_configured": int(cfg.train.max_epochs),
        "seconds_per_epoch": seconds_per_epoch,
        "resolution_m": float(cfg.study_area.resolution_m),
        "n_train_windows": len(datasets["train"]),
        "n_val_windows": len(datasets["val"]),
        "n_test_windows": len(datasets["test"]),
        "test_metrics": metrics,
        "per_horizon": module.horizon_table(),
    }

    out_path = Path(cfg.paths.tables) / f"metrics_{run_name}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(record, indent=2), encoding="utf-8")
    logger.info("wrote %s", out_path)

    for key in ("test/iou", "test/bank_f1", "test/mde_m"):
        if key in metrics:
            logger.info("%-16s %.4f", key, metrics[key])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
