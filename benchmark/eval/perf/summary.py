#!/usr/bin/env python3
import argparse
import math
import sys
from pathlib import Path

BENCHMARK_DIR = Path(__file__).resolve().parents[2]
if str(BENCHMARK_DIR) not in sys.path:
    sys.path.insert(0, str(BENCHMARK_DIR))

from common.io import read_jsonl, write_json


SPEEDUP_THRESHOLD = 1.5

COMPILE_PASSED_STAGES = {"correctness", "run", "performance"}


def is_success(row):
    return str(row.get("status", "")).strip() == "success"


def is_compile_pass(row):
    history = row.get("rounds_history")
    if isinstance(history, list) and history:
        for item in history:
            if not isinstance(item, dict):
                continue
            if str(item.get("status", "")).strip() == "pass":
                return True
            if str(item.get("stage", "")).strip() in COMPILE_PASSED_STAGES:
                return True
        return False
    if is_success(row):
        return True
    return str(row.get("stage", "")).strip() in COMPILE_PASSED_STAGES


def round1_entry(row):
    history = row.get("rounds_history")
    if not isinstance(history, list) or not history:
        return None
    for item in history:
        if isinstance(item, dict) and int(item.get("round", 0) or 0) == 1:
            return item
    first = history[0]
    return first if isinstance(first, dict) else None


def round1_status(row):
    entry = round1_entry(row)
    if entry is not None:
        return str(entry.get("status", "")).strip() == "pass"
    if not is_success(row):
        return False
    try:
        return int(row.get("best_round") or 0) == 1
    except (TypeError, ValueError):
        return False


def round1_compile_pass(row):
    entry = round1_entry(row)
    if entry is not None:
        if str(entry.get("status", "")).strip() == "pass":
            return True
        return str(entry.get("stage", "")).strip() in COMPILE_PASSED_STAGES
    return round1_status(row)


def round1_speedup(row):
    entry = round1_entry(row)
    if entry is not None:
        try:
            return float(entry.get("speedup") or 0.0)
        except (TypeError, ValueError):
            return 0.0
    return row_speedup(row)


def round1_is_success(row):
    return round1_status(row) and round1_speedup(row) > 0.0


def row_speedup(row):
    value = row.get("best_speedup_ratio")
    if value is None:
        debug = row.get("debug") or {}
        value = debug.get("speedup_ratio")
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def fmt_ratio(value):
    if value is None:
        return None
    return f"{value:.4f}"


def safe_ratio(numerator, denominator):
    if denominator <= 0:
        return None
    return numerator / denominator


def geometric_mean(values):
    positive = [v for v in values if v is not None and v > 0]
    if not positive:
        return None
    log_sum = sum(math.log(v) for v in positive)
    return math.exp(log_sum / len(positive))


def block_metrics(*, total, success_speedups, compile_count, correct_count):
    compile_rate = safe_ratio(compile_count, total)
    correct_rate = safe_ratio(correct_count, total)
    positive_count = sum(1 for s in success_speedups if s > 1.0)
    positive_rate = safe_ratio(positive_count, len(success_speedups))
    over_threshold = sum(1 for s in success_speedups if s > SPEEDUP_THRESHOLD)
    over_threshold_rate = safe_ratio(over_threshold, len(success_speedups))
    geo_mean = geometric_mean(success_speedups)
    max_speedup = max(success_speedups) if success_speedups else None
    return {
        "compile_pass_rate": fmt_ratio(compile_rate),
        "correct_pass_rate": fmt_ratio(correct_rate),
        "positive_rate": fmt_ratio(positive_rate),
        "speedup_over_1_5_rate": fmt_ratio(over_threshold_rate),
        "geometric_mean_speedup": fmt_ratio(geo_mean),
        "max_speedup": fmt_ratio(max_speedup),
    }


def summarize(rows):
    total = len(rows)

    overall_success_speedups = [row_speedup(row) for row in rows if is_success(row)]
    overall_compile_count = sum(1 for row in rows if is_compile_pass(row))
    overall_correct_count = sum(1 for row in rows if is_success(row))
    overall = block_metrics(
        total=total,
        success_speedups=overall_success_speedups,
        compile_count=overall_compile_count,
        correct_count=overall_correct_count,
    )

    round1_success_speedups = [
        round1_speedup(row) for row in rows if round1_is_success(row)
    ]
    round1_compile_count = sum(1 for row in rows if round1_compile_pass(row))
    round1_correct_count = sum(1 for row in rows if round1_status(row))
    round1 = block_metrics(
        total=total,
        success_speedups=round1_success_speedups,
        compile_count=round1_compile_count,
        correct_count=round1_correct_count,
    )

    return {
        "num_samples": total,
        "round1": round1,
        "overall": overall,
    }


def main():
    parser = argparse.ArgumentParser(description="Summarize perf benchmark results.")
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", default=None)
    args = parser.parse_args()

    input_path = Path(args.input)
    output_path = Path(args.output) if args.output else input_path.parent / "summary.json"

    rows = read_jsonl(input_path)
    summary = summarize(rows)
    write_json(output_path, summary)


if __name__ == "__main__":
    main()
