"""Run the offline-capable investigation workflow for all 20 supplied cases."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from fraud_app.investigator import Investigator


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    parser.add_argument("--output-dir", type=Path, default=Path("cases"))
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for stale in args.output_dir.glob("HHG-*.json"):
        stale.unlink()
    with (args.data_dir / "case_pack.csv").open(newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))
    investigator = Investigator(args.data_dir)
    try:
        for row in rows:
            result = investigator.investigate(row)
            path = args.output_dir / f"{row['case_id']}.json"
            path.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            print(f"{row['case_id']}: {result['case']['verdict']} {result['case']['pattern']} p={result['case']['fraud_probability']:.2f}")
    finally:
        investigator.close()


if __name__ == "__main__":
    main()