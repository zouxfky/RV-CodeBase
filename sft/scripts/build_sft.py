#!/usr/bin/env python3
"""Build original/optimized pairs with positive speedups from RV-CodeBase results.

Inputs:
  - data/seed.jsonl         (pid, extension, code)       written by stages 1-2
  - data/optimized.jsonl    (pid, extension, status, speedup, code, ...)  written by stage 3

Output:
  - sft/data/pairs.jsonl    {pid, extension, speedup, baseline, optimized}

Only programs that pass correctness checks and run faster than the original
(status == "success" and speedup > --min-speedup) are kept for fine-tuning.
Failed and slower attempts stay in data/optimized.jsonl for failure analysis.
"""
import argparse
import json
import random
import sys
from collections import Counter
from pathlib import Path


REPO_DIR = Path(__file__).resolve().parents[2]
DEFAULT_SEED = REPO_DIR / "data" / "seed.jsonl"
DEFAULT_OPTIMIZED = REPO_DIR / "data" / "optimized.jsonl"
DEFAULT_OUT = REPO_DIR / "sft" / "data" / "pairs.jsonl"


def read_jsonl(path):
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            yield json.loads(line)


def to_speedup(value):
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def build(args):
    seed_map = {row["pid"]: row for row in read_jsonl(args.seed)}

    rows = []
    seen = set()
    skipped = Counter()

    for opt in read_jsonl(args.optimized):
        pid = opt.get("pid")
        if not pid or pid in seen:
            continue
        seen.add(pid)

        if str(opt.get("status", "")).strip() != "success":
            skipped["not correct"] += 1
            continue
        speedup = to_speedup(opt.get("speedup"))
        if speedup <= args.min_speedup:
            skipped[f"speedup <= {args.min_speedup}"] += 1
            continue

        seed = seed_map.get(pid)
        baseline = str((seed or {}).get("code", ""))
        if not baseline.strip():
            skipped["no baseline"] += 1
            continue
        optimized = str(opt.get("code") or "")
        if not optimized.strip():
            skipped["empty optimized"] += 1
            continue

        extension = str(opt.get("extension") or seed.get("extension") or "").strip()
        if not extension:
            skipped["no extension"] += 1
            continue

        rows.append({
            "pid": pid, "extension": extension, "speedup": speedup,
            "baseline": baseline, "optimized": optimized,
        })

    if args.shuffle:
        random.Random(args.seed_value).shuffle(rows)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    print(f"seeds loaded:      {len(seed_map)}")
    print(f"results read:      {len(seen)}")
    for reason, count in sorted(skipped.items()):
        print(f"  skipped ({reason}): {count}")
    by_ext = Counter(row["extension"] for row in rows)
    print(f"positive pairs:    {len(rows)}  "
          + "  ".join(f"{ext}={by_ext[ext]}" for ext in sorted(by_ext)))
    print(f"pairs.jsonl -> {out_path}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", default=str(DEFAULT_SEED))
    ap.add_argument("--optimized", default=str(DEFAULT_OPTIMIZED))
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--min-speedup", type=float, default=1.0,
                    help="keep pairs whose speedup is strictly greater than this (default: 1.0)")
    ap.add_argument("--shuffle", action="store_true",
                    help="shuffle rows in the output")
    ap.add_argument("--seed-value", type=int, default=42)
    args = ap.parse_args()
    build(args)


if __name__ == "__main__":
    sys.exit(main())
