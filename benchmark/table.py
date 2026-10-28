#!/usr/bin/env python3
"""Main results table: CR / PSR / SR of each model before (Base) and after (SFT)
fine-tuning on the four benchmarks and overall (metric definitions: common/metrics.py).

Reads <suite>/results/<model>/<ext>.jsonl (Base) and <suite>/results/<model>-sft/<ext>.jsonl
(SFT) for the tasks listed in classes.json; a task without a result counts as failed.
Overall pools the tasks of all four benchmarks.

    python3 benchmark/table.py > benchmark/table.md
    python3 benchmark/table.py --format latex
"""
import argparse
import json
import sys
from pathlib import Path

BENCHMARK_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BENCHMARK_DIR))

from common import metrics  # noqa: E402

SUITES = [("tsvc", "TSVC"), ("mbedtls", "Mbed TLS"), ("tacle", "TACLeBench"), ("cmsisnn", "CMSIS-NN")]
MODELS = [
    ("deepseek-coder-7b", "DeepSeek-Coder-7B"),
    ("deepseek-coder-33b", "DeepSeek-Coder-33B"),
    ("codellama-13b", "CodeLlama-13B"),
    ("codellama-34b", "CodeLlama-34B"),
    ("qwen3.5-9b", "Qwen3.5-9B"),
    ("qwen3.5-27b", "Qwen3.5-27B"),
    ("gemma4-12b", "Gemma4-12B"),
    ("gemma4-31b", "Gemma4-31B"),
]


def load(path: Path) -> dict:
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as fh:
        return {r["id"]: r for r in (json.loads(line) for line in fh if line.strip())}


def evaluate(method: str, classes: dict) -> list[dict]:
    """Metrics per suite, then overall, for one method (result directory name)."""
    pooled_results, pooled_ids, out = {}, [], []
    for suite, _ in SUITES:
        (ext, ids), = classes[suite].items()
        results = load(BENCHMARK_DIR / suite / "results" / method / f"{ext}.jsonl")
        out.append(metrics.compute(results, ids))
        pooled_results |= {f"{suite}:{i}": r for i, r in results.items()}
        pooled_ids += [f"{suite}:{i}" for i in ids]
    out.append(metrics.compute(pooled_results, pooled_ids))
    return out


def cells(block: dict) -> list[str]:
    cr, psr, sr = block["cr"], block["psr"], block["sr"]
    return [f"{cr:.1f}", f"{psr:.1f}", "--" if sr is None else f"{sr:.2f}"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--format", choices=["markdown", "latex"], default="markdown")
    ap.add_argument("--models", nargs="*", help="result directory names (default: the eight models)")
    args = ap.parse_args()

    classes = json.loads((BENCHMARK_DIR / "classes.json").read_text())
    names = dict(MODELS)
    models = args.models or [m for m, _ in MODELS]
    groups = [label for _, label in SUITES] + ["Overall"]

    if args.format == "markdown":
        hdr = ["Model", "Setting"] + [f"{g} {m}" for g in groups for m in ("CR (%)", "PSR (%)", "SR")]
        print("| " + " | ".join(hdr) + " |")
        print("|" + "---|" * len(hdr))
        for model in models:
            for setting, method in (("Base", model), ("SFT", f"{model}-sft")):
                row = [c for b in evaluate(method, classes) for c in cells(b)]
                print("| " + " | ".join([names.get(model, model), setting] + row) + " |")
    else:
        for model in models:
            for setting, method in (("Base", model), ("SFT", f"{model}-sft")):
                row = [c for b in evaluate(method, classes) for c in cells(b)]
                name = f"\\multirow{{2}}{{*}}{{{names.get(model, model)}}}" if setting == "Base" else ""
                print(f"{name} & {setting} & " + " & ".join(row) + " \\\\")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
