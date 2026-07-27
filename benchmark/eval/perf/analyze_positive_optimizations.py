#!/usr/bin/env python3
"""Analyze instruction families and optimization patterns in positive kernels."""

import argparse
import csv
import json
import re
from collections import defaultdict
from pathlib import Path


REPO_DIR = Path(__file__).resolve().parents[3]
DEFAULT_RESULTS_ROOT = REPO_DIR / "benchmark/results"
DEFAULT_OUTPUT_DIR = DEFAULT_RESULTS_ROOT / "optimization_analysis"

INTRINSIC_RE = re.compile(r"__riscv_([A-Za-z0-9_]+)")
VECTOR_TYPE_RE = re.compile(r"^(?:[iuf](?:8|16|32|64|128)m(?:f?[1248]|[1248])(?:x\d+)?)$")
POLICY_RE = re.compile(r"^(?:m|tu|tum|tumu|mu)$")

PATTERN_ORDER = (
    "Element-wise",
    "Reduction",
    "Scan",
    "Gather",
    "Scatter",
    "Compact",
    "Interleave",
    "Permute",
    "Idiom",
    "Other",
)


def normalize_instruction(intrinsic):
    parts = intrinsic.lower().split("_")
    if not parts:
        return None
    opcode = parts[0]
    # The first token contains the opcode and, for memory instructions, EEW/NF.
    opcode = re.sub(r"^(v(?:le|se|l[su]e|s[su]e|vluxei|vloxei|vsuxei|vsoxei))\d+", r"\1", opcode)
    opcode = re.sub(r"^(v(?:l|s)seg)\d+e\d+", r"\1", opcode)
    opcode = re.sub(r"^(v(?:l|s)[ls]seg)\d+e\d+", r"\1", opcode)
    opcode = re.sub(r"^(v(?:l|s)[uo]xseg)\d+ei\d+", r"\1", opcode)
    opcode = re.sub(r"^(v(?:l|s)[uo]xei)\d+", r"\1", opcode)
    return opcode


def extract_instruction_families(code):
    families = set()
    for match in INTRINSIC_RE.finditer(code or ""):
        family = normalize_instruction(match.group(1))
        if family and family.startswith("v") and family not in {"vector", "rvv", "v", "vundefined", "vget", "vreinterpret", "vscan"}:
            families.add(family)
    return families


def classify_patterns(instructions):
    patterns = set()
    for instruction in instructions:
        if instruction.startswith(("vred", "vfred", "vwred", "vfwred")):
            patterns.add("Reduction")
        elif instruction.startswith(("vluxei", "vloxei", "vluxseg", "vloxseg")):
            patterns.add("Gather")
        elif instruction.startswith(("vsuxei", "vsoxei", "vsuxseg", "vsoxseg")):
            patterns.add("Scatter")
        elif instruction == "vcompress":
            patterns.add("Compact")
        elif instruction.startswith(("vlseg", "vsseg", "vlsseg", "vssseg")):
            patterns.add("Interleave")
        elif instruction.startswith(("vrgather", "vslide", "vfslide", "vmv")):
            patterns.add("Permute")
        elif instruction.startswith(("vcpop", "vfirst")) or re.match(r"^vm(?:and|or|xor|nand|nor|xnor|not|merge|slt|sle|seq|sne|adc|sbc|first|popc)", instruction):
            patterns.add("Idiom")
        elif instruction.startswith((
            "vadd", "vsub", "vrsub", "vmul", "vdiv", "vfadd", "vfsub",
            "vfmul", "vfdiv", "vfmacc", "vfnmacc", "vmf", "vmseq", "vmsne", "vmslt", "vmsle", "vmax", "vmin", "vabs",
            "vneg", "vsll", "vsrl", "vsra", "vsadd", "vssub", "vwadd",
            "vwsub", "vwaddu", "vwsubu", "vwmul", "vfwadd", "vfwsub",
            "vfwmul", "vfcvt", "vfncvt", "vnclip", "vnsrl", "vnsra",
        )):
            patterns.add("Element-wise")

    if "vslideup" in instructions and any(
        instruction.startswith(("vadd", "vfadd", "vsub", "vfsub"))
        for instruction in instructions
    ):
        patterns.add("Scan")
    return patterns or {"Other"}


def iter_positive_results(results_root):
    for result_path in sorted(Path(results_root).glob("*/*/results.jsonl")):
        benchmark = result_path.parent.parent.name
        model = result_path.parent.name
        with result_path.open(encoding="utf-8") as handle:
            for row in map(json.loads, handle):
                speedup = row.get("best_speedup_ratio")
                if speedup is None:
                    speedup = row.get("debug", {}).get("speedup_ratio")
                if row.get("status") not in {"success", "pass"}:
                    continue
                if speedup is None or float(speedup) <= 1.0:
                    continue
                code = row.get("code", "")
                instructions = extract_instruction_families(code)
                patterns = classify_patterns(instructions)
                yield {
                    "benchmark": benchmark,
                    "model": model,
                    "id": row.get("id", ""),
                    "speedup": float(speedup),
                    "instructions": sorted(instructions),
                    "patterns": sorted(patterns),
                }


def aggregate(samples, key):
    samples = [sample for sample in samples if sample["instructions"]]
    grouped = defaultdict(list)
    for sample in samples:
        for item in sample[key]:
            grouped[item].append(sample["speedup"])
    total = len(samples)
    rows = []
    for item, speedups in grouped.items():
        rows.append({
            key.title().replace("_", " "): item,
            "Count": len(speedups),
            "Percentage": len(speedups) / total if total else 0.0,
            "Avg. Speedup": sum(speedups) / len(speedups),
        })
    return sorted(rows, key=lambda row: (-row["Count"], row[key.title().replace("_", " ")]))


def write_csv(path, rows, first_column):
    path.parent.mkdir(parents=True, exist_ok=True)
    headers = [first_column, "Count", "Percentage", "Avg. Speedup"]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers)
        writer.writeheader()
        for row in rows:
            writer.writerow({
                first_column: row[first_column],
                "Count": row["Count"],
                "Percentage": f"{row['Percentage']:.4f}",
                "Avg. Speedup": f"{row['Avg. Speedup']:.4f}",
            })


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results-root", default=str(DEFAULT_RESULTS_ROOT))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    args = parser.parse_args()

    samples = list(iter_positive_results(args.results_root))
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    with (output_dir / "positive_accelerated_results.jsonl").open("w", encoding="utf-8") as handle:
        for sample in samples:
            handle.write(json.dumps(sample, ensure_ascii=False) + "\n")

    recognized_samples = [sample for sample in samples if sample["instructions"]]
    unrecognized_count = len(samples) - len(recognized_samples)
    instruction_rows = aggregate(recognized_samples, "instructions")
    pattern_rows = aggregate(recognized_samples, "patterns")
    write_csv(output_dir / "instruction_distribution.csv", instruction_rows, "Instructions")
    write_csv(output_dir / "pattern_distribution.csv", pattern_rows, "Patterns")
    print(f"positive kernels: {len(samples)}")
    print(f"recognized RVV kernels: {len(recognized_samples)}")
    print(f"unrecognized kernels: {unrecognized_count}")
    print(f"instruction distribution: {output_dir / 'instruction_distribution.csv'}")
    print(f"pattern distribution: {output_dir / 'pattern_distribution.csv'}")


if __name__ == "__main__":
    main()
