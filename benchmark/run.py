#!/usr/bin/env python3
"""Single entry point for the four benchmarks; each suite is evaluated on its
target extension: TSVC -> RVV, Mbed TLS -> B, TACLeBench -> Zicond, CMSIS-NN -> IME.
All suites share the prompts in common/prompts.

    python3 benchmark/run.py --suite tsvc|mbedtls|tacle|cmsisnn \
        --method <model>|<model>-sft [--platform <board>] [--llm-j N] [-n K]

Reads <suite>/dataset.jsonl. Optimized code goes to <suite>/baseline/<method>/<ext>.jsonl;
speedups and status go to <suite>/results/<method>/<ext>.jsonl.
"""
import argparse
import importlib.util
import sys
from pathlib import Path

BENCHMARK_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BENCHMARK_DIR))

SUITES = ["tsvc", "mbedtls", "tacle", "cmsisnn"]


def main() -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--suite", choices=SUITES)
    known, rest = parser.parse_known_args()
    if known.suite == "tsvc":
        # TSVC builds its translation units around the TSVC driver; same flags otherwise.
        spec = importlib.util.spec_from_file_location("tsvc_run", BENCHMARK_DIR / "tsvc" / "run.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        sys.argv = [sys.argv[0]] + rest
        return module.main()
    from common.runner import main as run_suite

    return run_suite()


if __name__ == "__main__":
    raise SystemExit(main())
