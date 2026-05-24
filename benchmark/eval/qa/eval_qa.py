#!/usr/bin/env python3
import argparse
import json
import re
import sys
from pathlib import Path

BENCHMARK_DIR = Path(__file__).resolve().parents[2]
REPO_DIR = BENCHMARK_DIR.parent
DEFAULT_RVV_JSON = BENCHMARK_DIR / "datasets" / "rvv.json"
DEFAULT_QUESTIONS = BENCHMARK_DIR / "datasets/questions.jsonl"
DEFAULT_RESULTS_DIR = BENCHMARK_DIR / "results/qa"
if str(BENCHMARK_DIR) not in sys.path:
    sys.path.insert(0, str(BENCHMARK_DIR))

from common.io import read_jsonl, write_jsonl
from common.qa_schema import (
    validate_qa_predictions,
    validate_qa_questions,
)


INSTRUCTION_RE = re.compile(
    r"(?<!\w)(?:"
    r"vsetvli|vsetivli|vsetvl|"
    r"v[a-z][a-z0-9]*(?:<[a-z0-9]+>[a-z0-9]*)*"
    r"(?:\.[a-z0-9]+(?:<[a-z0-9]+>[a-z0-9]*)*)*"
    r"(?:\.[a-z0-9]+(?:<[a-z0-9]+>[a-z0-9]*)*)"
    r")(?=$|[\s,`*/)])"
)
INTRINSIC_RE = re.compile(r"__riscv_[A-Za-z0-9_<>#]+")


def normalize_text(text):
    return re.sub(r"\s+", " ", text.strip().lower())


def normalize_token(text):
    return text.strip().strip("`.,;:()[]{}")


def normalize_operand_token(text):
    token = normalize_token(text).strip("*")
    token = token.strip().strip("`.,;:()[]{}")
    if not token:
        return ""
    token = token.split()[0]
    token = token.strip().strip("`.,;:()[]{}")
    return token


def normalize_evidence_list(value):
    if value is None:
        return None
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [evidence_to_text(item) for item in value]
    return [evidence_to_text(value)]


def evidence_to_text(item):
    if isinstance(item, str):
        return item
    if isinstance(item, dict):
        return str(item.get("content", "")).strip()
    return str(item).strip()


def extract_instruction_names(answer):
    return {normalize_token(match.group(0)) for match in INSTRUCTION_RE.finditer(answer)}


def extract_instruction_families(answer, question_text):
    relax_opcode_params = should_relax_opcode_params(question_text)
    relax_vf_factor = should_relax_vf_factor(question_text)
    families = {
        normalize_instruction_family(
            match.group(0),
            relax_opcode_params=relax_opcode_params,
            relax_vf_factor=relax_vf_factor,
        )
        for match in INSTRUCTION_RE.finditer(answer)
    }
    families.update(extract_compact_instruction_families(answer, question_text))
    return families


def extract_compact_instruction_families(answer, question_text):
    if "vnclip[|u].w[v|x|i]" not in answer:
        return set()
    return {
        "vnclip.wv",
        "vnclip.wx",
        "vnclip.wi",
        "vnclipu.wv",
        "vnclipu.wx",
        "vnclipu.wi",
    }


def extract_intrinsics(answer):
    return {normalize_token(match.group(0)) for match in INTRINSIC_RE.finditer(answer)}


def extract_intrinsic_families(answer, *, relax_opcode_params=False, relax_vf_factor=False):
    families = set()
    for match in INTRINSIC_RE.finditer(answer):
        family = normalize_intrinsic_family(
            match.group(0),
            relax_opcode_params=relax_opcode_params,
            relax_vf_factor=relax_vf_factor,
        )
        if family:
            families.add(family)
    return families


def normalize_intrinsic_family(
    intrinsic,
    *,
    relax_opcode_params=False,
    relax_vf_factor=False,
):
    name = normalize_token(intrinsic)
    if not name.startswith("__riscv_"):
        return None

    parts = [part for part in name[len("__riscv_") :].split("_") if part]
    if not parts:
        return None
    if not is_plausible_intrinsic_parts(parts):
        return None

    family_parts = [
        normalize_intrinsic_opcode(
            parts[0],
            relax_opcode_params=relax_opcode_params,
        )
    ]
    for part in parts[1:]:
        if is_intrinsic_type_suffix(part) or is_intrinsic_policy_suffix(part):
            continue
        family_parts.append(
            normalize_intrinsic_form(part, relax_vf_factor=relax_vf_factor)
        )

    return "__riscv_" + "_".join(family_parts)


def normalize_instruction_family(
    instruction,
    *,
    relax_opcode_params=False,
    relax_vf_factor=False,
):
    name = normalize_token(instruction)
    if "." not in name:
        return name
    opcode, form = name.split(".", 1)
    opcode = normalize_opcode_params(opcode, relax_opcode_params=relax_opcode_params)
    if relax_vf_factor and re.fullmatch(r"vf(?:\d+|<nf>)", form):
        form = "vf"
    return f"{opcode}.{form}"


def normalize_intrinsic_opcode(opcode, *, relax_opcode_params):
    if not relax_opcode_params:
        return opcode

    return normalize_opcode_params(opcode, relax_opcode_params=True)


def normalize_opcode_params(opcode, *, relax_opcode_params):
    if not relax_opcode_params:
        return opcode
    for pattern, replacement in (
        (r"^(vlseg)<nf>e<eew>(ff)?$", lambda m: m.group(1) + ("ff" if m.group(2) else "")),
        (r"^(vsseg)<nf>e<eew>$", lambda m: m.group(1)),
        (r"^(vlsseg)<nf>e<eew>$", lambda m: m.group(1)),
        (r"^(vssseg)<nf>e<eew>$", lambda m: m.group(1)),
        (r"^(vluxseg|vloxseg|vsuxseg|vsoxseg)<nf>ei<eew>$", lambda m: m.group(1)),
        (r"^(vluxei|vloxei|vsuxei|vsoxei)<eew>$", lambda m: m.group(1)),
        (r"^(vle|vse|vlse|vsse)<eew>(ff)?$", lambda m: m.group(1) + ("ff" if m.group(2) else "")),
        (r"^(vl)<nf>re<eew>$", lambda m: m.group(1) + "re"),
        (r"^(vs)<nf>r$", lambda m: m.group(1) + "r"),
        (r"^(vlseg)\d+e\d+(ff)?$", lambda m: m.group(1) + ("ff" if m.group(2) else "")),
        (r"^(vsseg)\d+e\d+$", lambda m: m.group(1)),
        (r"^(vlsseg)\d+e\d+$", lambda m: m.group(1)),
        (r"^(vssseg)\d+e\d+$", lambda m: m.group(1)),
        (r"^(vluxseg|vloxseg|vsuxseg|vsoxseg)\d+ei\d+$", lambda m: m.group(1)),
        (r"^(vluxei|vloxei|vsuxei|vsoxei)\d+$", lambda m: m.group(1)),
        (r"^(vle|vse|vlse|vsse)\d+(ff)?$", lambda m: m.group(1) + ("ff" if m.group(2) else "")),
        (r"^(vl)\d+re\d+$", lambda m: m.group(1) + "re"),
        (r"^(vs)\d+r$", lambda m: m.group(1) + "r"),
    ):
        match = re.match(pattern, opcode)
        if match:
            return replacement(match)
    return opcode


def normalize_intrinsic_form(form, *, relax_vf_factor):
    if relax_vf_factor and re.fullmatch(r"vf(?:\d+|<nf>)", form):
        return "vf"
    return form


def is_intrinsic_type_suffix(part):
    return bool(
        is_vector_type_suffix(part)
        or is_scalar_type_suffix(part)
        or is_placeholder_type_suffix(part)
        or re.fullmatch(r"e\d+(?:m(?:f?[1248]|[1248]))?", part)
        or re.fullmatch(r"b\d+", part)
    )


def is_intrinsic_policy_suffix(part):
    return part in {"m", "tu", "tum", "tumu", "mu"}


def is_plausible_intrinsic_parts(parts):
    opcode = parts[0]
    vector_types = [part for part in parts[1:] if is_vector_type_suffix(part)]
    mask_types = [part for part in parts[1:] if re.fullmatch(r"b\d+", part)]
    placeholder_types = [part for part in parts[1:] if is_placeholder_type_suffix(part)]

    # Template-style intrinsic spellings such as
    # __riscv_vredsum_vs_##suffix##_##suffix are accepted at the family level.
    # Concrete spellings without placeholders still go through structural checks.
    if placeholder_types:
        return True

    if is_reduction_opcode(opcode):
        if len(vector_types) != 2:
            return False
    elif len(vector_types) > 1:
        return False

    segment_nf = segment_field_count(opcode)
    if segment_nf is not None:
        if not vector_types:
            return False
        tuple_count = tuple_field_count(vector_types[0])
        if tuple_count != segment_nf:
            return False

    if mask_types and vector_types:
        expected_mask = expected_mask_suffix(vector_types[0])
        if expected_mask is not None and mask_types[-1] != expected_mask:
            return False

    return True


def is_vector_type_suffix(part):
    return bool(
        re.fullmatch(r"[iuf]\d+m(?:f?[1248]|[1248])(?:x\d+)?", part)
    )


def is_scalar_type_suffix(part):
    return bool(
        re.fullmatch(r"[iuf](?:8|16|32|64)", part)
    )


def is_placeholder_type_suffix(part):
    return bool(
        "<" in part
        or ">" in part
        or "#" in part
        or part in {"type", "vl", "m", "l"}
    )


def is_reduction_opcode(opcode):
    return bool(
        re.fullmatch(
            r"(?:vredsum|vredmaxu?|vredminu?|vredand|vredor|vredxor|"
            r"vwredsumu?|vfredosum|vfredusum|vfredmax|vfredmin|"
            r"vfwredosum|vfwredusum)",
            opcode,
        )
    )


def segment_field_count(opcode):
    match = re.match(r"^(?:vlseg|vsseg|vlsseg|vssseg)(\d+)e\d+(?:ff)?$", opcode)
    if match:
        return int(match.group(1))
    match = re.match(r"^(?:vluxseg|vloxseg|vsuxseg|vsoxseg)(\d+)ei\d+$", opcode)
    if match:
        return int(match.group(1))
    return None


def tuple_field_count(type_suffix):
    match = re.search(r"x(\d+)$", type_suffix)
    if not match:
        return None
    return int(match.group(1))


def expected_mask_suffix(type_suffix):
    match = re.fullmatch(r"[iuf](\d+)m(f?[1248]|[1248])(?:x\d+)?", type_suffix)
    if not match:
        return None
    sew = int(match.group(1))
    lmul_text = match.group(2)
    if lmul_text.startswith("f"):
        denominator = int(lmul_text[1:])
        ratio = sew * denominator
    else:
        ratio = sew // int(lmul_text)
    return f"b{ratio}"


def compute_intrinsic_accuracy(answer, expected_intrinsics, question_text):
    relax_opcode_params = should_relax_opcode_params(question_text)
    relax_vf_factor = should_relax_vf_factor(question_text)
    expected = {
        family
        for family in (
            normalize_intrinsic_family(
                value,
                relax_opcode_params=relax_opcode_params,
                relax_vf_factor=relax_vf_factor,
            )
            for value in expected_intrinsics
            )
        if family
    }
    if not expected:
        answer_lc = answer.lower()
        no_intrinsic_markers = (
            "no direct named intrinsic",
            "no direct named c intrinsic",
            "no standard c intrinsic",
            "no intrinsic family",
            "not documented here",
            "no named intrinsic",
        )
        return 1.0 if any(marker in answer_lc for marker in no_intrinsic_markers) else 0.0
    return (
        len(
            extract_intrinsic_families(
                answer,
                relax_opcode_params=relax_opcode_params,
                relax_vf_factor=relax_vf_factor,
            )
            & expected
        )
        / len(expected)
    )


def has_placeholder(text, name):
    return f"<{name.lower()}>" in text.lower()


def should_relax_opcode_params(question_text):
    return has_placeholder(question_text, "eew") or has_placeholder(question_text, "nf")


def should_relax_vf_factor(question_text):
    return has_placeholder(question_text, "nf")


def compute_instruction_accuracy(answer, expected_formats, question_text):
    expected = expected_instruction_families(expected_formats, question_text)
    if not expected:
        return None
    predicted = extract_instruction_families(answer, question_text)
    return len(predicted & expected) / len(expected)


def compute_set_recall(answer_values, expected_values):
    expected = {normalize_token(value) for value in expected_values if value}
    if not expected:
        return None
    return len(answer_values & expected) / len(expected)


def compute_set_support(answer_values, evidence_values):
    if not answer_values:
        return None
    return len(answer_values & evidence_values) / len(answer_values)


def parse_answer_formats(answer):
    formats = []
    for line in candidate_format_lines(answer):
        formats.extend(parse_formats_from_text(line))
    return formats


def candidate_format_lines(text):
    lines = []
    in_fence = False
    fence_lang = ""
    for raw_line in text.splitlines():
        line = raw_line.strip()
        fence_match = re.match(r"^```([A-Za-z0-9_-]*)", line)
        if fence_match:
            if in_fence:
                in_fence = False
                fence_lang = ""
            else:
                in_fence = True
                fence_lang = fence_match.group(1).lower()
            continue

        if in_fence:
            if not fence_lang or fence_lang in {"asm", "s", "riscv", "text"}:
                lines.append(raw_line)
            continue

        for cell in table_or_line_cells(raw_line):
            candidate = strip_format_label(cell)
            if looks_like_format_line(candidate):
                lines.append(candidate)
    return lines


def table_or_line_cells(line):
    if "|" not in line:
        return [line]
    return [
        cell
        for cell in (part.strip() for part in line.strip().strip("|").split("|"))
        if cell and not re.fullmatch(r"-+", cell.replace(":", "").strip())
    ]


def looks_like_format_line(line):
    text = line.strip()
    text = re.sub(r"^[-*+]\s+", "", text)
    text = re.sub(r"^\d+[.)]\s+", "", text)
    text = text.strip("` ")
    match = INSTRUCTION_RE.match(text)
    if not match:
        return False
    tail = text[match.end() :]
    return bool(re.match(r"\s+\S+\s*,", tail))


def strip_format_label(text):
    return re.sub(
        r"^\s*(?:assembly\s+)?(?:instruction\s+)?formats?\s*:\s*",
        "",
        text,
        flags=re.IGNORECASE,
    ).strip()


def parse_expected_formats(expected_formats):
    formats = []
    for item in expected_formats:
        if isinstance(item, str):
            formats.extend(parse_formats_from_text(item))
        elif isinstance(item, dict):
            formats.append(item)
    return formats


def parse_formats_from_text(text):
    results = []
    for match in INSTRUCTION_RE.finditer(text):
        instruction = normalize_token(match.group(0))
        tail = text[match.end() :]
        tail = tail.split("\n", 1)[0]
        next_instruction = INSTRUCTION_RE.search(tail)
        if next_instruction:
            tail = tail[: next_instruction.start()]
        tail = re.split(r"[#|;。；]|(?<=[A-Za-z0-9>)])\.(?:\s|$)", tail, maxsplit=1)[0]
        tail = re.split(r"\s+(?:and|where|which|with)\b", tail, maxsplit=1)[0]
        raw_operands = tail.strip()
        raw_operands = raw_operands.strip("` ")
        operands = []
        if "," in raw_operands:
            raw_parts = raw_operands.split(",")
        elif raw_operands:
            raw_parts = [raw_operands]
        else:
            raw_parts = []
        for operand in raw_parts:
            cleaned = normalize_operand_token(operand)
            if cleaned:
                operands.append(cleaned)
        if operands:
            results.append({"instruction": instruction, "operands": operands})
    return results


def compute_operand_accuracy(answer, expected_formats, question_text):
    expected_pairs = format_family_pairs(parse_expected_formats(expected_formats), question_text)
    if not expected_pairs:
        return None
    predicted_pairs = format_family_pairs(parse_answer_formats(answer), question_text)
    return len(predicted_pairs & expected_pairs) / len(expected_pairs)


def format_pairs(formats):
    return {
        (
            normalize_token(item.get("instruction", "")),
            canonical_operands(item.get("operands", [])),
        )
        for item in formats
    }


def format_family_pairs(formats, question_text):
    relax_opcode_params = should_relax_opcode_params(question_text)
    relax_vf_factor = should_relax_vf_factor(question_text)
    return {
        (
            normalize_instruction_family(
                item.get("instruction", ""),
                relax_opcode_params=relax_opcode_params,
                relax_vf_factor=relax_vf_factor,
            ),
            canonical_operands(item.get("operands", [])),
        )
        for item in formats
    }


def canonical_operands(operands):
    return tuple(
        operand
        for operand in (normalize_operand_token(op) for op in operands)
        if operand
    )


def expected_instruction_names(expected_formats):
    return {
        instruction
        for instruction, _operands in format_pairs(parse_expected_formats(expected_formats))
    }


def expected_instruction_families(expected_formats, question_text):
    relax_opcode_params = should_relax_opcode_params(question_text)
    relax_vf_factor = should_relax_vf_factor(question_text)
    return {
        normalize_instruction_family(
            instruction,
            relax_opcode_params=relax_opcode_params,
            relax_vf_factor=relax_vf_factor,
        )
        for instruction, _operands in format_pairs(parse_expected_formats(expected_formats))
    }


def instruction_family_variants(instruction):
    return {
        normalize_instruction_family(
            instruction,
            relax_opcode_params=relax_opcode_params,
            relax_vf_factor=relax_vf_factor,
        )
        for relax_opcode_params, relax_vf_factor in (
            (False, False),
            (True, False),
            (True, True),
        )
    }


def intrinsic_family_variants(intrinsic):
    return {
        family
        for family in (
            normalize_intrinsic_family(
                intrinsic,
                relax_opcode_params=relax_opcode_params,
                relax_vf_factor=relax_vf_factor,
            )
            for relax_opcode_params, relax_vf_factor in (
                (False, False),
                (True, False),
                (True, True),
            )
        )
        if family
    }


def format_family_pair_variants(formats):
    pairs = set()
    for item in formats:
        operands = canonical_operands(item.get("operands", []))
        for family in instruction_family_variants(item.get("instruction", "")):
            pairs.add((family, operands))
    return pairs


def load_rvv_claims(path=DEFAULT_RVV_JSON):
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    return build_rvv_claims(data)


def build_rvv_claims(data):
    instructions = set()
    operand_formats = set()
    intrinsic_families = set()

    for item in iter_rvv_instruction_items(data):
        all_text = "\n".join(
            value for value in item.values() if isinstance(value, str)
        )

        for instruction in extract_instruction_names(all_text):
            instructions.update(instruction_family_variants(instruction))

        format_text = "\n".join(
            str(item.get(field, ""))
            for field in ("instruction_formats", "assembly_examples")
        )
        parsed_formats = []
        for line in candidate_format_lines(format_text):
            parsed_formats.extend(parse_formats_from_text(line))
        operand_formats.update(format_family_pair_variants(parsed_formats))
        for instruction, _operands in format_pairs(parsed_formats):
            instructions.update(instruction_family_variants(instruction))
            intrinsic_families.update(instruction_intrinsic_family_variants(instruction))

        for intrinsic in extract_intrinsics(all_text):
            intrinsic_families.update(intrinsic_family_variants(intrinsic))

    return {
        "instructions": instructions,
        "operand_formats": operand_formats,
        "intrinsic_families": intrinsic_families,
    }


def iter_rvv_instruction_items(data):
    for chapter in data.get("chapters", []):
        for section in chapter.get("sections", []):
            yield from section.get("instructions", [])


def instruction_intrinsic_family_variants(instruction):
    families = set()
    for family in instruction_family_variants(instruction):
        if "." not in family:
            continue
        families.add("__riscv_" + family.replace(".", "_"))
    return families


def compute_supported_instruction_fraction(predicted, supported):
    if not predicted:
        return None
    return sum(
        bool(instruction_family_variants(instruction) & supported)
        for instruction in predicted
    ) / len(predicted)


def compute_supported_operand_fraction(predicted, supported):
    if not predicted:
        return None
    matched = 0
    for instruction, operands in predicted:
        variants = {
            (family, operands)
            for family in instruction_family_variants(instruction)
        }
        if variants & supported:
            matched += 1
    return matched / len(predicted)


def compute_supported_intrinsic_fraction(predicted, supported):
    if not predicted:
        return None
    return sum(
        bool(intrinsic_family_variants(intrinsic) & supported)
        for intrinsic in predicted
    ) / len(predicted)


def compute_answer_precision(answer, question_text, rvv_claims):
    instruction_precision = compute_supported_instruction_fraction(
        extract_instruction_families(answer, question_text),
        rvv_claims["instructions"],
    )
    operand_precision = compute_supported_operand_fraction(
        format_family_pairs(parse_answer_formats(answer), question_text),
        rvv_claims["operand_formats"],
    )
    intrinsic_precision = compute_supported_intrinsic_fraction(
        extract_intrinsic_families(
            answer,
            relax_opcode_params=should_relax_opcode_params(question_text),
            relax_vf_factor=should_relax_vf_factor(question_text),
        ),
        rvv_claims["intrinsic_families"],
    )
    return mean_non_null(
        [instruction_precision, operand_precision, intrinsic_precision]
    )


def compute_precision_breakdown(answer, question_text, rvv_claims):
    return {
        "instruction": compute_supported_instruction_fraction(
            extract_instruction_families(answer, question_text),
            rvv_claims["instructions"],
        ),
        "operand": compute_supported_operand_fraction(
            format_family_pairs(parse_answer_formats(answer), question_text),
            rvv_claims["operand_formats"],
        ),
        "intrinsic": compute_supported_intrinsic_fraction(
            extract_intrinsic_families(
                answer,
                relax_opcode_params=should_relax_opcode_params(question_text),
                relax_vf_factor=should_relax_vf_factor(question_text),
            ),
            rvv_claims["intrinsic_families"],
        ),
    }


def compute_answer_accuracy(answer, answer_key, question_text):
    expected_formats = answer_key.get("formats", [])
    return mean_non_null(
        [
            compute_instruction_accuracy(answer, expected_formats, question_text),
            compute_operand_accuracy(answer, expected_formats, question_text),
            compute_intrinsic_accuracy(
                answer,
                answer_key.get("intrinsics", []),
                question_text,
            ),
        ]
    )


def compute_accuracy_breakdown(answer, answer_key, question_text):
    expected_formats = answer_key.get("formats", [])
    return {
        "instruction": compute_instruction_accuracy(
            answer, expected_formats, question_text
        ),
        "operand": compute_operand_accuracy(answer, expected_formats, question_text),
        "intrinsic": compute_intrinsic_accuracy(
            answer,
            answer_key.get("intrinsics", []),
            question_text,
        ),
    }


def compute_f1(accuracy, precision):
    if accuracy is None or precision is None:
        return None
    if accuracy + precision == 0:
        return 0.0
    return 2 * accuracy * precision / (accuracy + precision)


def round_metric(value):
    if value is None:
        return None
    return f"{value:.4f}"


def join_evidence(retrieved_evidence):
    evidence_items = normalize_evidence_list(retrieved_evidence)
    if evidence_items is None:
        return ""
    return "\n".join(evidence_items)


def mean_non_null(values):
    non_null = [value for value in values if value is not None]
    if not non_null:
        return None
    return sum(non_null) / len(non_null)


def compute_faithfulness(answer, retrieved_evidence):
    evidence_text = join_evidence(retrieved_evidence)
    if not evidence_text:
        return None

    answer_instructions = extract_instruction_names(answer)
    evidence_instructions = extract_instruction_names(evidence_text)
    instruction_faithfulness = compute_set_support(
        answer_instructions,
        evidence_instructions,
    )

    answer_formats = format_pairs(parse_answer_formats(answer))
    evidence_formats = format_pairs(parse_answer_formats(evidence_text))
    operand_faithfulness = compute_set_support(answer_formats, evidence_formats)

    answer_intrinsics = extract_intrinsics(answer)
    evidence_intrinsics = extract_intrinsics(evidence_text)
    intrinsic_faithfulness = compute_set_support(
        answer_intrinsics,
        evidence_intrinsics,
    )

    return mean_non_null(
        [
            instruction_faithfulness,
            operand_faithfulness,
            intrinsic_faithfulness,
        ]
    )


def compute_faithfulness_breakdown(answer, retrieved_evidence):
    evidence_text = join_evidence(retrieved_evidence)
    if not evidence_text:
        return {
            "instruction": None,
            "operand": None,
            "intrinsic": None,
        }

    answer_instructions = extract_instruction_names(answer)
    evidence_instructions = extract_instruction_names(evidence_text)
    answer_formats = format_pairs(parse_answer_formats(answer))
    evidence_formats = format_pairs(parse_answer_formats(evidence_text))
    answer_intrinsics = extract_intrinsics(answer)
    evidence_intrinsics = extract_intrinsics(evidence_text)

    return {
        "instruction": compute_set_support(
            answer_instructions,
            evidence_instructions,
        ),
        "operand": compute_set_support(answer_formats, evidence_formats),
        "intrinsic": compute_set_support(
            answer_intrinsics,
            evidence_intrinsics,
        ),
    }


def round_metrics_block(faithfulness, accuracy, precision):
    return {
        "faithfulness": round_metric(faithfulness),
        "accuracy": round_metric(accuracy),
        "precision": round_metric(precision),
        "f1": round_metric(compute_f1(accuracy, precision)),
    }


def evaluate_one(question, prediction, rvv_claims):
    answer = prediction.get("answer", "")
    answer_key = question.get("answer_key", {})
    retrieved_evidence = prediction.get("retrieved_evidence")
    question_text = question.get("question", "")
    accuracy_breakdown = compute_accuracy_breakdown(answer, answer_key, question_text)
    precision_breakdown = compute_precision_breakdown(answer, question_text, rvv_claims)
    faithfulness_breakdown = compute_faithfulness_breakdown(answer, retrieved_evidence)

    accuracy = mean_non_null(list(accuracy_breakdown.values()))
    precision = mean_non_null(list(precision_breakdown.values()))
    faithfulness = mean_non_null(list(faithfulness_breakdown.values()))

    return {
        "id": question["id"],
        "method": prediction.get("method", ""),
        "instruction": round_metrics_block(
            faithfulness_breakdown["instruction"],
            accuracy_breakdown["instruction"],
            precision_breakdown["instruction"],
        ),
        "operand": round_metrics_block(
            faithfulness_breakdown["operand"],
            accuracy_breakdown["operand"],
            precision_breakdown["operand"],
        ),
        "intrinsic": round_metrics_block(
            faithfulness_breakdown["intrinsic"],
            accuracy_breakdown["intrinsic"],
            precision_breakdown["intrinsic"],
        ),
        "overall": round_metrics_block(
            faithfulness,
            accuracy,
            precision,
        ),
    }


def predictions_by_id(questions, predictions):
    question_by_id = {row["id"]: row for row in questions}
    prediction_by_id = {}
    matched_questions = []
    unknown = []

    for prediction in predictions:
        prediction_id = prediction["id"]
        question = question_by_id.get(prediction_id)
        if question is None:
            unknown.append(prediction_id)
            continue
        prediction_by_id[prediction_id] = prediction
        matched_questions.append(question)

    if unknown:
        raise ValueError(f"predictions contain unknown ids: {', '.join(unknown)}")
    if not matched_questions:
        raise ValueError("no overlapping question/prediction ids")

    return prediction_by_id, matched_questions


def main():
    parser = argparse.ArgumentParser(description="Evaluate QA predictions.")
    parser.add_argument("--method", default=None)
    parser.add_argument("--questions", default=None)
    parser.add_argument("--predictions", default=None)
    parser.add_argument("--output", default=None)
    parser.add_argument("--rvv-json", default=str(DEFAULT_RVV_JSON))
    args = parser.parse_args()

    questions_path = args.questions or str(DEFAULT_QUESTIONS)
    predictions_path = args.predictions
    output_path = args.output
    if args.method:
        predictions_path = predictions_path or str(DEFAULT_RESULTS_DIR / args.method / "predictions.jsonl")
        output_path = output_path or str(DEFAULT_RESULTS_DIR / args.method / "metrics.jsonl")
    if not predictions_path:
        parser.error("either --method or --predictions is required")
    if not output_path:
        parser.error("either --method or --output is required")

    questions = read_jsonl(questions_path)
    predictions = read_jsonl(predictions_path)
    try:
        validate_qa_questions(questions)
        validate_qa_predictions(predictions)
        prediction_by_id, eval_questions = predictions_by_id(
            questions,
            predictions,
        )
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)

    rvv_claims = load_rvv_claims(Path(args.rvv_json))
    metrics = [evaluate_one(row, prediction_by_id[row["id"]], rvv_claims) for row in eval_questions]
    write_jsonl(output_path, metrics)


if __name__ == "__main__":
    main()
