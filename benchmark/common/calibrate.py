#!/usr/bin/env python3
"""Find per-program repetition counts so one run of the original takes about --goal-ms.

Run on the board, then pass the output to the suite's build.py --repeat-json:

    python3 benchmark/common/calibrate.py --suite tacle --output reps.json

The repetition macro is the -D<NAME>_REPEAT=... in each row's compile_defs.
"""
import argparse
import json
import re
import shutil
import subprocess
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

BENCHMARK_DIR = Path(__file__).resolve().parents[1]


def run(row: dict, rep: int, cc: str, src: str, work: Path) -> tuple[float, str]:
    d = work / row["id"].replace("/", "__")
    shutil.rmtree(d, ignore_errors=True)
    d.mkdir(parents=True)
    for name, text in row["files"].items():
        (d / name).parent.mkdir(parents=True, exist_ok=True)
        (d / name).write_text(text)
    (d / "baseline.c").write_text(row["code"])
    mac = re.search(r"-D(\w+_REPEAT)=", row["compile_defs"]).group(1)
    defs = [x.replace("{src}", src) for x in row["compile_defs"].split() if not x.startswith(f"-D{mac}=")]
    sources = [x.replace("{src}", src) for x in row["compile_sources"]]
    subprocess.run([cc, "-x", "c", "-std=gnu11", "-O3", "-march=rv64gc", "-mabi=lp64d", "-I.", *defs,
                    f"-D{mac}={rep}", "baseline.c", *sources, "-lm", "-o", "a.out"],
                   cwd=d, check=True, capture_output=True)
    best, out = 1e18, ""
    for _ in range(2):
        t0 = time.perf_counter()
        r = subprocess.run(["./a.out"], cwd=d, capture_output=True, text=True, timeout=900)
        best, out = min(best, (time.perf_counter() - t0) * 1000), r.stdout.strip()
    return best, out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--suite", required=True)
    ap.add_argument("--cc", default="gcc")
    ap.add_argument("--goal-ms", type=float, default=300)
    ap.add_argument("--output", required=True)
    ap.add_argument("--only", help="comma-separated program names")
    ap.add_argument("--jobs", type=int, default=1, help="programs calibrated at once (keep 1 on small boards)")
    args = ap.parse_args()
    suite_dir = BENCHMARK_DIR / args.suite
    only = set(args.only.split(",")) if args.only else None
    res = {}
    rows = [r for r in map(json.loads, open(suite_dir / "dataset.jsonl"))
            if not only or r["id"].split("/", 1)[1] in only]

    def find(row: dict, work: str) -> tuple[str, int]:
        name = row["id"].split("/", 1)[1]
        rep = 1
        while True:
            t, out = run(row, rep, args.cc, str(suite_dir / "src"), Path(work))
            if t >= args.goal_ms or rep >= 10**8:
                break
            rep = max(rep * 2, int(rep * args.goal_ms / max(t - 2.5, 0.05) * 1.1)) if t > 10 else rep * 50
        print(name, rep, f"{t:.0f}ms", out, flush=True)
        return name, rep

    with tempfile.TemporaryDirectory() as work, ThreadPoolExecutor(args.jobs) as pool:
        res = dict(pool.map(lambda r: find(r, work), rows))
    Path(args.output).write_text(json.dumps(res, indent=1) + "\n")


if __name__ == "__main__":
    main()
