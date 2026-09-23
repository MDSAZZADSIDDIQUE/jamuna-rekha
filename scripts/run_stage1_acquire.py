"""Stage 1 entry point — build monthly water-index composites.

    python scripts/run_stage1_acquire.py
    python scripts/run_stage1_acquire.py --config local.yaml --years 2015 2024
    python scripts/run_stage1_acquire.py --tiles T02_00

Resumable: a tile-month already present in ``data/raw/`` is skipped, so the run
can be interrupted and restarted freely.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from jamunarekha.data import acquire_pc
from jamunarekha.utils.config import load_config
from jamunarekha.utils.geo import grid_from_config
from jamunarekha.utils.logging import get_logger
from jamunarekha.utils.seed import seed_everything


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=None, help="override YAML in configs/")
    parser.add_argument("--years", nargs=2, type=int, metavar=("START", "END"))
    parser.add_argument("--tiles", nargs="+", help="tile names, e.g. T02_00")
    parser.add_argument("--workers", type=int, default=None)
    args = parser.parse_args()

    cfg = load_config(args.config)
    logger = get_logger("jamunarekha.stage1", cfg.paths.logs)
    seed_everything(int(cfg.project.seed))

    if args.years:
        cfg.acquire.year_start, cfg.acquire.year_end = args.years
    if args.workers:
        cfg.acquire.workers = args.workers

    tiles = grid_from_config(cfg)
    if args.tiles:
        wanted = set(args.tiles)
        tiles = [t for t in tiles if t.name in wanted]
        if not tiles:
            logger.error("no tiles matched %s", sorted(wanted))
            return 1

    logger.info(
        "Stage 1 | %d tiles | %d-%d | %s @ %.0f m | %d workers",
        len(tiles), cfg.acquire.year_start, cfg.acquire.year_end,
        cfg.study_area.target_crs, cfg.study_area.resolution_m, cfg.acquire.workers,
    )
    acquire_pc.run(cfg, tiles)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
