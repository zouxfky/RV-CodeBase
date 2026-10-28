#!/usr/bin/env python3
"""B / Zicond / IME benchmarks (RVV on TSVC: benchmark/tsvc/run.py).

Each suite is evaluated on its target extension: Mbed TLS -> B,
TACLeBench -> Zicond, CMSIS-NN -> IME.

    python3 benchmark/run.py --suite mbedtls|tacle|cmsisnn \
        [--platform <board>] --mode llm|manual [--method <model>]

Reads <suite>/dataset.jsonl. Optimized code goes to <suite>/baseline/<method>/<ext>.jsonl
(manual mode reads it from there); speedups and status go to
<suite>/results/<method>/<ext>.jsonl.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common.runner import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
