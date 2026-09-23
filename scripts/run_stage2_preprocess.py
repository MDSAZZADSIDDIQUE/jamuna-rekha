"""Stage 2 entry point — gap-fill, threshold and stack into JamunaShift-52Y.

    python scripts/run_stage2_preprocess.py
    python scripts/run_stage2_preprocess.py --tiles T02_00

Writes ``<tile>_index.npy``, ``<tile>_water.npy``, ``<tile>_observed.npy`` and
``<tile>_meta.json`` into ``data/processed/``, then prints the coverage summary
that feeds the data section of the paper.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from jamunarekha.data import preprocess
from jamunarekha.utils.config import load_config
from jamunarekha.utils.geo import grid_from_config
from jamunarekha.utils.logging import get_logger
from jamunarekha.utils.seed import seed_everything


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=None)
    parser.add_argument("--tiles", nargs="+")
    args = parser.parse_args()

    cfg = load_config(args.config)
    logger = get_logger("jamunarekha.stage2", cfg.paths.logs)
    seed_everything(int(cfg.project.seed))

    tiles = grid_from_config(cfg)
    if args.tiles:
        wanted = set(args.tiles)
        tiles = [t for t in tiles if t.name in wanted]

    metas = preprocess.run(cfg, tiles)
    if not metas:
        logger.error("nothing processed — is data/raw populated?")
        return 1

    logger.info("--- coverage summary ---")
    for meta in metas:
        logger.info(
            "%s  observed=%.3f  after gap-fill=%.3f  water=%.3f  months=%d",
            meta["tile"], meta["observed_fraction_raw"],
            meta["usable_fraction_filled"], meta["water_fraction"],
            len(meta["months"]),
        )

    summary = Path(cfg.paths.data_processed) / "coverage_summary.json"
    summary.write_text(json.dumps(metas, indent=2), encoding="utf-8")
    logger.info("wrote %s", summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
