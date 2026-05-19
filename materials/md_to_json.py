#!/usr/bin/env python3
import argparse
import json
import re
from pathlib import Path


FIELD_MAP = {
    "Function": "function",
    "Instruction Formats": "instruction_formats",
    "Parameters": "parameters",
    "Semantics": "semantics",
    "Assembly Examples": "assembly_examples",
    "Intrinsics": "intrinsics",
    "Notes": "notes",
}

FIELD_KEYS = list(FIELD_MAP.values())


def parse_numbered_heading(text):
    match = re.match(r"^([0-9]+(?:\.[0-9]+)*)(?:\.)?\s+(.+)$", text)
    if not match:
        raise ValueError(f"invalid numbered heading: {text}")
    return match.group(1), match.group(2)


def normalize_block(lines):
    start = 0
    end = len(lines)
    while start < end and lines[start].strip() == "":
        start += 1
    while end > start and lines[end - 1].strip() == "":
        end -= 1
    return "\n".join(lines[start:end])


def finalize_field(current_instruction, current_field, current_lines):
    if current_instruction is None or current_field is None:
        return
    current_instruction[current_field] = normalize_block(current_lines)


def new_instruction(number, title):
    item = {
        "number": number,
        "title": title,
    }
    for key in FIELD_KEYS:
        item[key] = ""
    return item


def parse_rvv_md(path):
    root = {"title": "", "chapters": []}
    current_chapter = None
    current_section = None
    current_instruction = None
    current_field = None
    current_lines = []
    seen_fields = set()
    errors = []

    def close_instruction():
        nonlocal current_instruction, current_field, current_lines, seen_fields
        finalize_field(current_instruction, current_field, current_lines)
        if current_instruction is not None:
            missing = [key for key in FIELD_KEYS if key not in seen_fields]
            if missing:
                errors.append(
                    f"instruction {current_instruction['number']} missing fields: {', '.join(missing)}"
                )
        current_field = None
        current_lines = []
        seen_fields = set()

    lines = path.read_text(encoding="utf-8").splitlines()
    for line_number, line in enumerate(lines, start=1):
        if line.startswith("# "):
            close_instruction()
            root["title"] = line[2:].strip()
            current_chapter = None
            current_section = None
            current_instruction = None
            continue

        if line.startswith("## "):
            close_instruction()
            number, title = parse_numbered_heading(line[3:].strip())
            current_chapter = {"number": number, "title": title, "sections": []}
            root["chapters"].append(current_chapter)
            current_section = None
            current_instruction = None
            continue

        if line.startswith("### "):
            close_instruction()
            if current_chapter is None:
                errors.append(f"line {line_number}: section appears before chapter")
                continue
            number, title = parse_numbered_heading(line[4:].strip())
            current_section = {"number": number, "title": title, "instructions": []}
            current_chapter["sections"].append(current_section)
            current_instruction = None
            continue

        if line.startswith("#### "):
            close_instruction()
            if current_section is None:
                errors.append(f"line {line_number}: instruction appears before section")
                continue
            number, title = parse_numbered_heading(line[5:].strip())
            current_instruction = new_instruction(number, title)
            current_section["instructions"].append(current_instruction)
            current_field = None
            current_lines = []
            seen_fields = set()
            continue

        if line.startswith("##### "):
            finalize_field(current_instruction, current_field, current_lines)
            if current_instruction is None:
                errors.append(f"line {line_number}: field appears before instruction")
                current_field = None
                current_lines = []
                continue
            field_title = line[6:].strip()
            if field_title not in FIELD_MAP:
                errors.append(f"line {line_number}: unknown field heading: {field_title}")
                current_field = None
                current_lines = []
                continue
            current_field = FIELD_MAP[field_title]
            current_lines = []
            seen_fields.add(current_field)
            continue

        if current_field is not None:
            current_lines.append(line)
        elif line.strip():
            errors.append(f"line {line_number}: non-empty content outside instruction field")

    close_instruction()

    if not root["title"]:
        errors.append("missing document title")
    if errors:
        raise ValueError("\n".join(errors))
    return root


def main():
    parser = argparse.ArgumentParser(description="Convert materials/RVV.md to nested JSON.")
    parser.add_argument(
        "--input",
        default="materials/RVV.md",
        help="Path to RVV markdown input.",
    )
    parser.add_argument(
        "--output",
        default="materials/RVV.json",
        help="Path to JSON output.",
    )
    args = parser.parse_args()

    data = parse_rvv_md(Path(args.input))
    Path(args.output).write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
