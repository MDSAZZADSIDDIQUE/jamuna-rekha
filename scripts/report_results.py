"""Format Stage 3 and Stage 4 results as Bengali Markdown for the manuscript.

    python scripts/report_results.py

Reads every ``outputs/tables/metrics_*.json`` and the latest risk summary, and
prints the comparison table, the per-horizon table and the compute table with
**Bengali numerals**, ready to paste into ``docs/paper/``.

This exists so that no number reaches the paper by being retyped. Every figure
in the results section is generated from the JSON the run actually wrote, which
means re-running the pipeline on the A100 regenerates the tables rather than
inviting a manual update that silently disagrees with the data.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from jamunarekha.utils.config import load_config

BENGALI_DIGITS = str.maketrans("0123456789", "০১২৩৪৫৬৭৮৯")

MODEL_BN = {
    "timesformer": "টাইমসফরমার",
    "convlstm": "কনভএলএসটিএম",
    "persistence": "স্থিতাবস্থা",
}


def bn(value, decimals: int = 3, thousands: bool = False) -> str:
    """Render a number in Bengali numerals.

    Parameters
    ----------
    value
        The number, or something non-numeric which is returned unchanged.
    decimals
        Digits after the decimal point.
    thousands
        Insert thousands separators before converting.
    """
    if value is None:
        return "—"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if number != number:  # NaN
        return "—"
    text = f"{number:,.{decimals}f}" if thousands else f"{number:.{decimals}f}"
    return text.translate(BENGALI_DIGITS)


def load_metrics(tables_dir: Path) -> list[dict]:
    records = []
    for path in sorted(tables_dir.glob("metrics_*.json")):
        records.append(json.loads(path.read_text(encoding="utf-8")))
    order = {"timesformer": 0, "convlstm": 1, "persistence": 2}
    return sorted(records, key=lambda r: order.get(r["model"], 9))


def comparison_table(records: list[dict]) -> str:
    lines = [
        "| মডেল | প্যারামিটার | IoU | তীর-F1 | নির্ভুলতা | পুনরাহ্বান | গড় স্থানচ্যুতি ত্রুটি (মি) |",
        "|---|---|---|---|---|---|---|",
    ]
    for record in records:
        metrics = record["test_metrics"]
        params = record["trainable_params"] / 1e6
        lines.append(
            "| {model} | {params} মি. | {iou} | {f1} | {prec} | {rec} | {mde} |".format(
                model=MODEL_BN.get(record["model"], record["model"]),
                params=bn(params, 2),
                iou=bn(metrics.get("test/iou")),
                f1=bn(metrics.get("test/bank_f1")),
                prec=bn(metrics.get("test/bank_precision")),
                rec=bn(metrics.get("test/bank_recall")),
                mde=bn(metrics.get("test/mde_m"), 1, thousands=True),
            )
        )
    return "\n".join(lines)


def horizon_table(records: list[dict]) -> str:
    lines = ["| মডেল | দিগন্ত | তীর-F1 | গড় স্থানচ্যুতি ত্রুটি (মি) |", "|---|---|---|---|"]
    for record in records:
        for row in record.get("per_horizon", []):
            lines.append(
                "| {model} | +{h} মাস | {f1} | {mde} |".format(
                    model=MODEL_BN.get(record["model"], record["model"]),
                    h=bn(row["horizon_months"], 0),
                    f1=bn(row.get("bank_f1")),
                    mde=bn(row.get("mde_m"), 1, thousands=True),
                )
            )
    return "\n".join(lines)


def compute_table(records: list[dict]) -> str:
    lines = [
        "| মডেল | প্যারামিটার | সেকেন্ড/ইপক | প্রশিক্ষণ উইন্ডো |",
        "|---|---|---|---|",
    ]
    for record in records:
        seconds = record.get("seconds_per_epoch")
        lines.append(
            "| {model} | {params} মি. | {sec} | {n} |".format(
                model=MODEL_BN.get(record["model"], record["model"]),
                params=bn(record["trainable_params"] / 1e6, 2),
                sec=bn(seconds, 1, thousands=True) if seconds == seconds else "—",
                n=bn(record["n_train_windows"], 0),
            )
        )
    return "\n".join(lines)


def risk_summary(tables_dir: Path) -> str:
    summaries = sorted(tables_dir.glob("risk_summary_*.json"))
    if not summaries:
        return "(Stage 4 has not been run yet.)"
    data = json.loads(summaries[-1].read_text(encoding="utf-8"))

    import pandas as pd

    csvs = sorted(tables_dir.glob("at_risk_households_*.csv"))
    table = pd.read_csv(csvs[-1]) if csvs else None

    erosion = float(data.get("total_erosion_ha") or 0.0)
    accretion = float(data.get("total_accretion_ha") or 0.0)
    out = [
        f"forecast month          : {data.get('forecast_month')}",
        f"model / checkpoint      : {data.get('model')}",
        f"water threshold         : {data.get('water_threshold')}  (calibrated on validation)",
        f"total erosion (ha)      : {erosion:,.1f}",
        f"total accretion (ha)    : {accretion:,.1f}",
        f"NET land change (ha)    : {accretion - erosion:,.1f}   <- the interpretable figure",
        f"change polygons         : {data.get('n_polygons')}",
        f"OSM buildings           : {data.get('n_buildings_osm')}",
        f"unions affected         : {data.get('n_unions_affected')}",
    ]
    for tile in data.get("tiles", []):
        out.append(
            f"  {tile['tile']}: ref={tile.get('reference_month')} "
            f"-> {tile.get('forecast_month')} "
            f"erosion={tile.get('erosion_ha', 0):.1f} ha "
            f"accretion={tile.get('accretion_ha', 0):.1f} ha"
        )
    if table is not None and not table.empty:
        out.append("")
        out.append("top unions by predicted erosion:")
        for _, row in table.nlargest(8, "erosion_ha").iterrows():
            out.append(
                f"  {row['union']:<22s} {row['district']:<14s} "
                f"{row['erosion_ha']:7.1f} ha  {int(row['buildings_osm']):5d} buildings"
            )
        out.append("")
        out.append(f"total households at risk (OSM lower bound): {int(table['households_est'].sum())}")
        out.append(f"total persons at risk   (OSM lower bound): {int(table['persons_est'].sum())}")
    return "\n".join(out)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=None)
    args = parser.parse_args()

    cfg = load_config(args.config)
    tables_dir = Path(cfg.paths.tables)
    records = load_metrics(tables_dir)
    if not records:
        print("no metrics files yet", file=sys.stderr)
        return 1

    print("=" * 72)
    print("COMPARISON (test split, 2018-2024)")
    print("=" * 72)
    print(comparison_table(records))
    print()
    print("=" * 72)
    print("PER HORIZON")
    print("=" * 72)
    print(horizon_table(records))
    print()
    print("=" * 72)
    print("COMPUTE")
    print("=" * 72)
    print(compute_table(records))
    print()
    print("=" * 72)
    print("RISK OVERLAY")
    print("=" * 72)
    print(risk_summary(tables_dir))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
