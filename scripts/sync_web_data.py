"""Copy the latest Stage 4 forecast into the web dashboard.

    python scripts/sync_web_data.py                 # most recent forecast month
    python scripts/sync_web_data.py --month 2025-03

Writes ``web/public/data/forecast.json`` and a byte-identical copy of the DDM
CSV. Run it after Stage 4, then rebuild the site (``npm run build`` in
``web/``). The output is deterministic, so it is safe to commit — which lets
the site build on a host that has no Python.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from jamunarekha.dashboard.web_export import WebExportError, export
from jamunarekha.utils.config import load_config


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=None, help="override YAML in configs/")
    parser.add_argument("--month", default=None, help="YYYY-MM; default: latest")
    args = parser.parse_args()

    cfg = load_config(args.config)
    try:
        export(cfg, month=args.month)
    except WebExportError as exc:
        print(f"sync_web_data: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
