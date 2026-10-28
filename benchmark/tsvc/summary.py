#!/usr/bin/env python3
"""Print CR / PSR / SR for one results file (metric definitions: common/metrics.py).

    python3 benchmark/tsvc/summary.py --input benchmark/tsvc/results/<model>/rvv.jsonl

Tasks are those listed in classes.json for the suite and extension of the
input path (<suite>/results/<method>/<ext>.jsonl); a task without a result
counts as failed.
"""
import argparse
import json
import sys
from pathlib import Path

BENCHMARK_DIR = Path(__file__).resolve().parents[1]
if str(BENCHMARK_DIR) not in sys.path:
    sys.path.insert(0, str(BENCHMARK_DIR))

from common import metrics  # noqa: E402
from common.io import read_jsonl, write_json  # noqa: E402


def summarize(input_path: Path) -> dict:
    path = input_path.resolve()
    suite, ext = path.parents[2].name, path.stem
    classes = json.loads((BENCHMARK_DIR / "classes.json").read_text())
    ids = classes.get(suite, {}).get(ext)
    results = {str(r["id"]): r for r in read_jsonl(path)}
    if ids is None:
        ids = sorted(results)
    block = metrics.compute(results, ids)
    return {
        "suite": suite,
        "extension": ext,
        "tasks": block["tasks"],
        "cr": None if block["cr"] is None else round(block["cr"], 1),
        "psr": None if block["psr"] is None else round(block["psr"], 1),
        "sr": None if block["sr"] is None else round(block["sr"], 2),
    }


def main():
    parser = argparse.ArgumentParser(description="Summarize benchmark results.")
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", default=None)
    args = parser.parse_args()

    summary = summarize(Path(args.input))
    if args.output:
        write_json(args.output, summary)
    else:
        print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
