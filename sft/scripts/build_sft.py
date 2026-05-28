#!/usr/bin/env python3
"""Build before/after optimization pairs from RV-CodeBase results.

Inputs:
  - data/seed/seed.jsonl              (pid, code)
  - data/optimized/optimized.jsonl    (pid, status, stage, speedup, code, ...)

Output:
  - sft/data/pairs.jsonl    {pid, label, speedup, baseline, optimized}

Composition (configurable via --pos-ratio, default 0.7):
  positive:  status == "success" AND speedup > 1   (all of them)
  negative:  status == "success" AND speedup <= 1  (sampled to match ratio)
  both branches keep `optimized` as the LLM output.
"""
import argparse
import json
import random
import sys
from pathlib import Path


REPO_DIR = Path(__file__).resolve().parents[2]
DEFAULT_SEED = REPO_DIR / "data" / "seed" / "seed.jsonl"
DEFAULT_OPTIMIZED = REPO_DIR / "data" / "optimized" / "optimized.jsonl"
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
    seed_map = {row["pid"]: row.get("code", "") for row in read_jsonl(args.seed)}

    positives = []         # (pid, baseline, optimized, speedup)
    neg_candidates = []    # (pid, baseline, optimized, speedup)
    seen = set()
    skipped_no_seed = 0
    skipped_no_code = 0

    for opt in read_jsonl(args.optimized):
        pid = opt.get("pid")
        if not pid or pid in seen:
            continue
        seen.add(pid)

        if str(opt.get("status", "")).strip() != "success":
            continue

        baseline = seed_map.get(pid)
        if not baseline:
            skipped_no_seed += 1
            continue
        optimized = opt.get("code") or ""
        if not optimized.strip():
            skipped_no_code += 1
            continue

        speedup = to_speedup(opt.get("speedup"))
        record = (pid, baseline, optimized, speedup)
        if speedup > args.min_speedup:
            positives.append(record)
        else:
            neg_candidates.append(record)

    pos_n = len(positives)
    if not (0 < args.pos_ratio < 1):
        sys.exit(f"--pos-ratio must be in (0, 1), got {args.pos_ratio}")
    target_neg = int(round(pos_n * (1 - args.pos_ratio) / args.pos_ratio))
    if target_neg > len(neg_candidates):
        print(
            f"[warn] requested {target_neg} negatives but only "
            f"{len(neg_candidates)} negative-speedup samples available; taking all"
        )
        target_neg = len(neg_candidates)
    rng = random.Random(args.seed_value)
    negatives = rng.sample(neg_candidates, target_neg) if target_neg else []

    rows = []
    for pid, baseline, optimized, speedup in positives:
        rows.append({
            "pid": pid, "label": "positive", "speedup": speedup,
            "baseline": baseline, "optimized": optimized,
        })
    for pid, baseline, optimized, speedup in negatives:
        rows.append({
            "pid": pid, "label": "negative", "speedup": speedup,
            "baseline": baseline, "optimized": optimized,
        })

    if args.shuffle:
        rng.shuffle(rows)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    total = pos_n + target_neg
    print(f"seeds loaded:           {len(seed_map)}")
    if skipped_no_seed:
        print(f"  skipped (no baseline):     {skipped_no_seed}")
    if skipped_no_code:
        print(f"  skipped (empty optimized): {skipped_no_code}")
    print(f"")
    print(f"positives  (speedup > {args.min_speedup}):    {pos_n}")
    print(f"neg pool   (speedup <= {args.min_speedup}):  {len(neg_candidates)}")
    print(f"negatives  (sampled):           {target_neg}")
    if total:
        print(f"")
        print(f"final ratio  pos:neg = {pos_n}:{target_neg}  "
              f"({pos_n/total:.1%} : {target_neg/total:.1%})")
    print(f"")
    print(f"pairs.jsonl  {len(rows):>6} -> {out_path}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", default=str(DEFAULT_SEED))
    ap.add_argument("--optimized", default=str(DEFAULT_OPTIMIZED))
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--min-speedup", type=float, default=1.0,
                    help="speedup strictly greater than this counts as positive (default: 1.0)")
    ap.add_argument("--pos-ratio", type=float, default=0.7,
                    help="positive share of the output, e.g. 0.7 means 7:3 (default: 0.7)")
    ap.add_argument("--shuffle", action="store_true",
                    help="shuffle rows in the output")
    ap.add_argument("--seed-value", type=int, default=42)
    args = ap.parse_args()
    build(args)


if __name__ == "__main__":
    sys.exit(main())
