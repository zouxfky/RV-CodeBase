#!/usr/bin/env python3
import argparse
import sys
from pathlib import Path

BENCHMARK_DIR = Path(__file__).resolve().parents[2]
DEFAULT_RESULTS_DIR = BENCHMARK_DIR / "results/qa"
if str(BENCHMARK_DIR) not in sys.path:
    sys.path.insert(0, str(BENCHMARK_DIR))

from common.io import read_jsonl, write_json


METRIC_BLOCKS = ("instruction", "operand", "intrinsic", "overall")
BLOCK_METRICS = ("faithfulness", "accuracy", "precision", "f1")


def mean_non_null(rows, key):
    values = [float(row[key]) for row in rows if row.get(key) is not None]
    if not values:
        return None
    return f"{sum(values) / len(values):.4f}"


def mean_nested_non_null(rows, block, key):
    values = []
    for row in rows:
        block_value = row.get(block)
        if not isinstance(block_value, dict):
            continue
        value = block_value.get(key)
        if value is not None:
            values.append(float(value))
    if not values:
        return None
    return f"{sum(values) / len(values):.4f}"


def main():
    parser = argparse.ArgumentParser(description="Aggregate QA metrics.")
    parser.add_argument("--method", default=None)
    parser.add_argument("--metrics", default=None)
    parser.add_argument("--output", default=None)
    args = parser.parse_args()

    metrics_path = args.metrics
    output_path = args.output
    if args.method:
        metrics_path = metrics_path or str(DEFAULT_RESULTS_DIR / args.method / "metrics.jsonl")
        output_path = output_path or str(DEFAULT_RESULTS_DIR / args.method / "summary.json")
    if not metrics_path:
        parser.error("either --method or --metrics is required")
    if not output_path:
        parser.error("either --method or --output is required")

    rows = read_jsonl(metrics_path)
    method = rows[0].get("method", "") if rows else ""
    summary = {
        "method": method,
        "num_questions": len(rows),
    }
    for block in METRIC_BLOCKS:
        summary[block] = {
            key: mean_nested_non_null(rows, block, key) for key in BLOCK_METRICS
        }

    write_json(output_path, summary)


if __name__ == "__main__":
    main()
