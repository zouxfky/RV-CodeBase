#!/usr/bin/env python3
import argparse
import itertools
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path


BENCHMARK_DIR = Path(__file__).resolve().parents[3]
REPO_DIR = BENCHMARK_DIR.parent
METHOD_DIR = Path(__file__).resolve().parent
DEFAULT_MATERIALS = REPO_DIR / "materials/RVV.json"
DEFAULT_QUESTIONS = BENCHMARK_DIR / "datasets/questions.jsonl"
DEFAULT_ARTIFACTS_DIR = METHOD_DIR / "artifacts"
DEFAULT_NODES = DEFAULT_ARTIFACTS_DIR / "graph_nodes.jsonl"
DEFAULT_EDGES = DEFAULT_ARTIFACTS_DIR / "graph_edges.jsonl"
DEFAULT_ALIAS_INDEX = DEFAULT_ARTIFACTS_DIR / "alias_index.json"
DEFAULT_QUESTION_HINTS = DEFAULT_ARTIFACTS_DIR / "question_hints.jsonl"
DEFAULT_SUMMARY = DEFAULT_ARTIFACTS_DIR / "summary.json"
if str(BENCHMARK_DIR) not in sys.path:
    sys.path.insert(0, str(BENCHMARK_DIR))

from common.io import read_json, read_jsonl, write_json, write_jsonl
from common.qa_schema import validate_qa_questions
from methods.qa.text_rag.build_index import instruction_names_from_title, render_instruction_chunk


EEW_VALUES = ("8", "16", "32", "64")
SEGMENT_NF_VALUES = ("2", "3", "4", "5", "6", "7", "8")
EXTENSION_NF_VALUES = ("2", "4", "8")
WHOLE_REGISTER_NF_VALUES = ("1", "2", "4", "8")

INTENT_RULES = (
    ("format", re.compile(r"\b(assembly|format|operand order|syntax)\b", re.I)),
    ("operand_roles", re.compile(r"\b(role|roles|meaning|identify|operand|vd|vs1|vs2|vs3|rs1|rs2|imm|vm|v0\.t)\b", re.I)),
    ("intrinsic", re.compile(r"\b(intrinsic|__riscv_)\b", re.I)),
    ("verify_claim", re.compile(r"\b(check|verify|reviewer|says|claim|claims|note|incorrect|correct)\b", re.I)),
    ("contrast", re.compile(r"\b(distinguish|compare|difference|versus|ordered|unordered|widening|narrowing|rather than|not)\b", re.I)),
    ("memory", re.compile(r"\b(load|store|memory|stride|indexed|segment|mask|fault-only-first)\b|vlseg|vsseg|vlux|vlox|vsux|vsox|vle|vse", re.I)),
    ("policy", re.compile(r"\b(tail|mask policy|ta|tu|ma|mu|SEW|LMUL|vtype|AVL|vl)\b", re.I)),
)

CONCEPT_RULES = (
    ("configuration", (r"\bvsetvli\b", r"\bvsetivli\b", r"\bvsetvl\b", r"\bconfiguration\b", r"\bvtype\b")),
    ("strip_mining", (r"strip-mining", r"\bAVL\b")),
    ("vl", (r"\bvl\b",)),
    ("vtype", (r"\bvtype\b",)),
    ("SEW", (r"\bSEW\b", r"e\{SEW\}")),
    ("LMUL", (r"\bLMUL\b", r"m\{LMUL\}")),
    ("tail_policy", (r"tail policy", r"\bta\b", r"\btu\b", r"tail agnostic", r"tail undisturbed")),
    ("mask_policy", (r"mask policy", r"\bma\b", r"\bmu\b", r"mask agnostic", r"mask undisturbed")),
    ("unit_stride", (r"unit-stride", r"contiguous memory")),
    ("strided", (r"strided", r"byte stride", r"\bbstride\b")),
    ("indexed", (r"indexed", r"byte offset", r"\bbindex\b")),
    ("ordered", (r"\bordered\b",)),
    ("unordered", (r"\bunordered\b",)),
    ("segment", (r"\bsegment", r"\btuple\b", r"<nf>", r"x<nf>")),
    ("fault_only_first", (r"fault-only-first", r"ff\.v", r"\bnew_vl\b")),
    ("byte_stride", (r"byte stride", r"\bbstride\b")),
    ("byte_offset", (r"byte offset", r"\bbindex\b")),
    ("mask", (r"\bmask\b", r"\bv0\.t\b", r"\bvm\b")),
    ("packed_mask", (r"packed mask", r"\bvlm\.v\b", r"\bvsm\.v\b")),
    ("tuple", (r"\btuple\b", r"x<nf>", r"x[2-8]_t")),
    ("binary_arithmetic", (r"binary arithmetic", r"\bvop\.", r"\bvadd\.", r"\bvsub\.")),
    ("single_width", (r"single-width",)),
    ("widening", (r"\bwidening\b", r"\bvw", r"\bvfw")),
    ("narrowing", (r"\bnarrowing\b", r"\bvn", r"\bvfn")),
    ("wide_vs2", (r"already-wide `?vs2`?", r"double-width `?vs2`?", r"\.wv", r"\.wx")),
    ("narrow_source", (r"narrow source", r"narrow sources")),
    ("wraparound", (r"wraparound", r"wraps on overflow")),
    ("saturation", (r"saturat", r"\bvxsat\b")),
    ("fixed_point", (r"fixed-point", r"\bvxrm\b")),
    ("reduction", (r"reduction", r"\.vs\b", r"vred", r"vfred")),
    ("slide", (r"\bslide", r"vslide")),
    ("gather", (r"\bgather", r"vrgather")),
    ("compress", (r"\bcompress", r"vcompress")),
    ("float_to_integer_conversion", (r"convert floating-point vector elements to .*integer", r"\.x\.f", r"\.xu\.f")),
    ("integer_to_float_conversion", (r"convert .*integer vector elements to .*floating-point", r"\.f\.x", r"\.f\.xu")),
    ("float_to_float_conversion", (r"floating-point vector elements to .*floating-point", r"\.f\.f")),
    ("round_towards_zero", (r"round-towards-zero", r"\brtz\b")),
    ("round_to_odd", (r"round-to-odd", r"\brod\b")),
)

CONCEPT_CONTRASTS = (
    ("ordered", "unordered"),
    ("widening", "narrowing"),
    ("wraparound", "saturation"),
    ("byte_stride", "byte_offset"),
    ("mask", "mask_policy"),
    ("wide_vs2", "narrow_source"),
    ("float_to_integer_conversion", "integer_to_float_conversion"),
    ("round_towards_zero", "fixed_point"),
    ("round_to_odd", "round_towards_zero"),
)

CONCEPT_ALIASES = {
    "configuration": ("configuration", "configure", "vset", "vsetvl", "vsetvli", "vsetivli"),
    "strip_mining": ("strip-mining", "strip mining", "AVL", "avl"),
    "vl": ("vl", "new_vl", "vl-1"),
    "vtype": ("vtype", "vtypei"),
    "SEW": ("SEW", "2 * SEW", "EEW = 2 * SEW"),
    "LMUL": ("LMUL", "EMUL"),
    "tail_policy": ("tail", "tail policy", "ta", "tu"),
    "mask_policy": ("mask policy", "ma", "mu"),
    "unit_stride": ("unit-stride", "unit stride", "contiguous"),
    "strided": ("strided", "stride", "byte stride", "bstride"),
    "indexed": ("indexed", "index", "byte offset", "bindex"),
    "ordered": ("ordered",),
    "unordered": ("unordered",),
    "segment": ("segment", "nf", "<nf>", "x<nf>", "tuple"),
    "fault_only_first": ("fault-only-first", "fault first", "ff", "new_vl"),
    "byte_stride": ("byte stride", "bstride"),
    "byte_offset": ("byte offset", "bindex"),
    "mask": ("mask", "v0.t", "vm", "vm=0", "vm=1", "vm=0/1"),
    "packed_mask": ("packed mask", "vlm.v", "vsm.v"),
    "tuple": ("tuple", "x<nf>"),
    "binary_arithmetic": ("binary arithmetic", ".vv", ".vx", ".vi", ".vf"),
    "single_width": ("single-width", "single width"),
    "widening": ("widening", "wide", ".wv", ".wx", ".wf", "2 * SEW"),
    "narrowing": ("narrowing", ".wv", ".wx", ".wi", ".w"),
    "wide_vs2": ("wide vs2", "wide source", "already-wide vs2", "double-width vs2", ".wv", ".wx", ".wf"),
    "narrow_source": ("narrow source", "narrow sources"),
    "wraparound": ("wraparound", "wraps on overflow"),
    "saturation": ("saturation", "saturating", "vxsat"),
    "fixed_point": ("fixed-point", "fixed point", "vxrm", "rounding"),
    "reduction": ("reduction", ".vs", "vred", "vfred"),
    "slide": ("slide", "vslide", "vl-1"),
    "gather": ("gather", "vrgather"),
    "compress": ("compress", "vcompress"),
    "float_to_integer_conversion": ("float-to-integer", "float to integer", "floating-point to integer", "float-to-int", "float to int"),
    "integer_to_float_conversion": ("integer-to-float", "integer to float", "integer to floating-point", "int-to-float", "int to float"),
    "float_to_float_conversion": ("float-to-float", "floating-point to floating-point"),
    "round_towards_zero": ("round-towards-zero", "round towards zero", "rtz"),
    "round_to_odd": ("round-to-odd", "round to odd", "rod"),
}

QUESTION_CONCEPT_RULES = (
    ("configuration", re.compile(r"\b(configuration|configure|vtype|vset|strip-mining|strip mining)\b", re.I)),
    ("strip_mining", re.compile(r"strip-mining|strip mining|\bAVL\b", re.I)),
    ("vl", re.compile(r"\bvl\b|\bnew_vl\b", re.I)),
    ("vtype", re.compile(r"\bvtype\b|\bvtypei\b", re.I)),
    ("SEW", re.compile(r"\bSEW\b|\bEEW\b|2\s*\*\s*SEW", re.I)),
    ("LMUL", re.compile(r"\bLMUL\b|\bEMUL\b", re.I)),
    ("tail_policy", re.compile(r"\btail\b|\bta\b|\btu\b", re.I)),
    ("mask_policy", re.compile(r"mask policy|\bma\b|\bmu\b", re.I)),
    ("unit_stride", re.compile(r"unit-stride|unit stride|contiguous memory", re.I)),
    ("strided", re.compile(r"\bstrided\b|\bstride\b|byte-strided|byte stride|\bbstride\b", re.I)),
    ("indexed", re.compile(r"\bindexed\b|\bindex\b|byte-offset|byte offset|\bbindex\b", re.I)),
    ("ordered", re.compile(r"\bordered\b", re.I)),
    ("unordered", re.compile(r"\bunordered\b", re.I)),
    ("segment", re.compile(r"\bsegment\b|\bnf\b|<nf>|\btuple\b", re.I)),
    ("fault_only_first", re.compile(r"fault-only-first|fault first|\bnew_vl\b", re.I)),
    ("byte_stride", re.compile(r"byte-strided|byte stride|\bbstride\b", re.I)),
    ("byte_offset", re.compile(r"byte-offset|byte offset|\bbindex\b", re.I)),
    ("mask", re.compile(r"\bmask\b|\bv0\.t\b|\bvm\b|vm=0|vm=1", re.I)),
    ("packed_mask", re.compile(r"packed mask|mask bits|mask transfer", re.I)),
    ("tuple", re.compile(r"\btuple\b|x<nf>", re.I)),
    ("binary_arithmetic", re.compile(r"binary arithmetic|\.vv|\.vx|\.vi|\.vf", re.I)),
    ("single_width", re.compile(r"single-width|single width", re.I)),
    ("widening", re.compile(r"\bwidening\b|double-width|2\s*\*\s*SEW|\.wv|\.wx|\.wf", re.I)),
    ("narrowing", re.compile(r"\bnarrowing\b|single-width destination|\.wi|\.w\b", re.I)),
    ("wide_vs2", re.compile(r"wide `?vs2`?|wide source|already-wide|double-width `?vs2`?|\.wv|\.wx|\.wf", re.I)),
    ("narrow_source", re.compile(r"narrow source|narrow operand", re.I)),
    ("wraparound", re.compile(r"wraparound|wraps on overflow", re.I)),
    ("saturation", re.compile(r"saturat|\bvxsat\b", re.I)),
    ("fixed_point", re.compile(r"fixed-point|fixed point|\bvxrm\b|rounding", re.I)),
    ("reduction", re.compile(r"\breduction\b|\.vs\b", re.I)),
    ("slide", re.compile(r"\bslide\b|sliding", re.I)),
    ("gather", re.compile(r"\bgather\b", re.I)),
    ("compress", re.compile(r"\bcompress\b", re.I)),
    ("float_to_integer_conversion", re.compile(r"float-to-integer|float to integer|floating-point to .*integer|float-to-int|float to int", re.I)),
    ("integer_to_float_conversion", re.compile(r"integer-to-float|integer to float|integer to floating-point|integer .* to floating-point|int-to-float|int to float", re.I)),
    ("float_to_float_conversion", re.compile(r"float-to-float|floating-point to floating-point", re.I)),
    ("round_towards_zero", re.compile(r"round-towards-zero|round towards zero|\brtz\b", re.I)),
    ("round_to_odd", re.compile(r"round-to-odd|round to odd|\brod\b", re.I)),
)


def norm_key(value):
    return value.strip().lower()


def clean_code_line(line):
    return re.sub(r"\s+", " ", line.strip())


def extract_code_block_lines(text, language=None):
    if not text:
        return []
    if language:
        pattern = rf"```{re.escape(language)}\s*\n(.*?)```"
    else:
        pattern = r"```[a-zA-Z0-9_+-]*\s*\n(.*?)```"
    lines = []
    for block in re.findall(pattern, text, flags=re.S):
        for line in block.splitlines():
            stripped = clean_code_line(line)
            if stripped:
                lines.append(stripped)
    return lines


def split_operands(operand_text):
    if not operand_text:
        return []
    return [part.strip() for part in operand_text.split(",") if part.strip()]


def operand_ref(operand):
    stripped = operand.strip()
    stripped = stripped.strip("()")
    stripped = stripped.replace("`", "")
    if stripped.endswith(".t") and stripped != "v0.t":
        return stripped
    return stripped


def extract_format_rows(instruction):
    rows = []
    for line in extract_code_block_lines(instruction.get("instruction_formats", ""), "asm"):
        parts = line.split(None, 1)
        mnemonic = parts[0] if parts else ""
        operands = split_operands(parts[1] if len(parts) > 1 else "")
        rows.append(
            {
                "text": line,
                "mnemonic": mnemonic,
                "operands": operands,
                "operand_refs": [operand_ref(item) for item in operands],
            }
        )
    return rows


def extract_parameter_rows(markdown_table):
    rows = []
    if not markdown_table:
        return rows
    for line in markdown_table.splitlines():
        line = line.strip()
        if not line.startswith("|") or "---" in line or "Parameter" in line:
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if len(cells) < 2:
            continue
        parameter = cells[0].strip()
        meaning = cells[1].strip()
        if not parameter or not meaning:
            continue
        tokens = re.findall(r"`([^`]+)`", parameter) or [parameter]
        refs = []
        for token in tokens:
            for part in re.split(r"\s*/\s*", token):
                part = part.strip()
                if part:
                    refs.append(part)
        rows.append(
            {
                "parameter": parameter,
                "meaning": meaning,
                "operand_refs": refs,
            }
        )
    return rows


def extract_intrinsics(text):
    if not text:
        return []
    return sorted(set(re.findall(r"__riscv_[A-Za-z0-9_]+", text)))


def context_text(chapter, section, instruction):
    parts = [
        chapter.get("title", ""),
        section.get("title", ""),
        instruction.get("title", ""),
        instruction.get("function", ""),
        instruction.get("instruction_formats", ""),
        instruction.get("parameters", ""),
        instruction.get("semantics", ""),
        instruction.get("assembly_examples", ""),
        instruction.get("intrinsics", ""),
        instruction.get("notes", ""),
    ]
    return "\n".join(part for part in parts if part)


def extract_concepts(chapter, section, instruction):
    text = context_text(chapter, section, instruction)
    concepts = set()
    for concept, patterns in CONCEPT_RULES:
        if any(re.search(pattern, text, flags=re.I) for pattern in patterns):
            concepts.add(concept)
    return sorted(concepts)


def nf_values_for_template(symbol):
    if ".vf<nf>" in symbol:
        return EXTENSION_NF_VALUES
    if re.search(r"vl<nf>re|vs<nf>r", symbol):
        return WHOLE_REGISTER_NF_VALUES
    return SEGMENT_NF_VALUES


def expand_template_aliases(symbol):
    symbols = [symbol]
    if "<nf>" in symbol:
        symbols = [
            item.replace("<nf>", nf_value)
            for item in symbols
            for nf_value in nf_values_for_template(symbol)
        ]
    if "<eew>" in symbol:
        symbols = [
            item.replace("<eew>", eew_value)
            for item in symbols
            for eew_value in EEW_VALUES
        ]
    return sorted(set(symbols) - {symbol})


def normalize_instruction_symbol(symbol):
    value = symbol.strip().strip("`")
    replacements = (
        (r"^(vluxseg)([2-8])ei(8|16|32|64)\.v$", r"\1<nf>ei<eew>.v"),
        (r"^(vloxseg)([2-8])ei(8|16|32|64)\.v$", r"\1<nf>ei<eew>.v"),
        (r"^(vsuxseg)([2-8])ei(8|16|32|64)\.v$", r"\1<nf>ei<eew>.v"),
        (r"^(vsoxseg)([2-8])ei(8|16|32|64)\.v$", r"\1<nf>ei<eew>.v"),
        (r"^(vlseg)([2-8])e(8|16|32|64)ff\.v$", r"\1<nf>e<eew>ff.v"),
        (r"^(vlseg)([2-8])e(8|16|32|64)\.v$", r"\1<nf>e<eew>.v"),
        (r"^(vsseg)([2-8])e(8|16|32|64)\.v$", r"\1<nf>e<eew>.v"),
        (r"^(vlsseg)([2-8])e(8|16|32|64)\.v$", r"\1<nf>e<eew>.v"),
        (r"^(vssseg)([2-8])e(8|16|32|64)\.v$", r"\1<nf>e<eew>.v"),
        (r"^(vl)([1248])re(8|16|32|64)\.v$", r"vl<nf>re<eew>.v"),
        (r"^(vs)([1248])r\.v$", r"vs<nf>r.v"),
        (r"^(vle)(8|16|32|64)ff\.v$", r"\1<eew>ff.v"),
        (r"^(vle)(8|16|32|64)\.v$", r"\1<eew>.v"),
        (r"^(vse)(8|16|32|64)\.v$", r"\1<eew>.v"),
        (r"^(vlse)(8|16|32|64)\.v$", r"\1<eew>.v"),
        (r"^(vsse)(8|16|32|64)\.v$", r"\1<eew>.v"),
        (r"^(vluxei)(8|16|32|64)\.v$", r"\1<eew>.v"),
        (r"^(vloxei)(8|16|32|64)\.v$", r"\1<eew>.v"),
        (r"^(vsuxei)(8|16|32|64)\.v$", r"\1<eew>.v"),
        (r"^(vsoxei)(8|16|32|64)\.v$", r"\1<eew>.v"),
        (r"^(vzext\.vf)(2|4|8)$", r"\1<nf>"),
        (r"^(vsext\.vf)(2|4|8)$", r"\1<nf>"),
    )
    for pattern, replacement in replacements:
        normalized = re.sub(pattern, replacement, value)
        if normalized != value:
            return normalized
    return value


def symbol_family_aliases(symbol):
    aliases = set()
    value = symbol.strip().strip("`")
    if not value:
        return []

    aliases.add(value)
    normalized = normalize_instruction_symbol(value)
    aliases.add(normalized)
    for candidate in (value, normalized):
        dotted_parts = candidate.split(".")
        if len(dotted_parts) > 1:
            for index in range(1, len(dotted_parts)):
                aliases.add(".".join(dotted_parts[:index]))
            suffix = "." + dotted_parts[-1]
            if suffix != ".v":
                aliases.add(suffix)

    collapsed = re.sub(r"<[^>]+>", "", normalized)
    if collapsed:
        aliases.add(collapsed)
    if "." in collapsed:
        aliases.add(collapsed.split(".", 1)[0])

    if normalized.startswith(("vluxei", "vloxei", "vsuxei", "vsoxei")):
        aliases.add(normalized.split("<", 1)[0])
    if normalized.startswith(("vlseg", "vsseg", "vlsseg", "vssseg")):
        aliases.add(normalized.split("<", 1)[0])
    if normalized.startswith(("vluxseg", "vloxseg", "vsuxseg", "vsoxseg")):
        aliases.add(normalized.split("<", 1)[0])
    if normalized.startswith(("vle", "vse", "vlse", "vsse")):
        aliases.add(normalized.split("<", 1)[0])
    if normalized.startswith(("vzext.vf", "vsext.vf")):
        aliases.add(normalized.replace("<nf>", ""))

    return sorted(alias for alias in aliases if alias)


def concept_id(name):
    return f"concept:{name}"


class GraphBuilder:
    def __init__(self):
        self.nodes = {}
        self.edges = {}
        self.alias_index = defaultdict(set)
        self.symbol_to_instruction_ids = defaultdict(set)
        self.symbols_by_instruction = defaultdict(list)
        self.instruction_ids_by_section = defaultdict(list)
        self.concepts_by_instruction = defaultdict(set)

    def add_node(self, node_id, node_type, label, **extra):
        node = {
            "node_id": node_id,
            "type": node_type,
            "label": label,
        }
        node.update({key: value for key, value in extra.items() if value is not None})
        if node_id in self.nodes:
            self.nodes[node_id].update(node)
        else:
            self.nodes[node_id] = node
        return node_id

    def add_edge(self, source, target, edge_type, weight=1.0, **extra):
        edge_id = f"{edge_type}:{source}->{target}"
        edge = {
            "edge_id": edge_id,
            "source": source,
            "target": target,
            "type": edge_type,
            "weight": weight,
        }
        edge.update({key: value for key, value in extra.items() if value is not None})
        self.edges[edge_id] = edge
        return edge_id

    def add_alias_mapping(self, alias, instruction_id, symbol_id=None):
        key = norm_key(alias)
        if not key:
            return
        self.alias_index[key].add(instruction_id)
        if symbol_id:
            self.alias_index[key].add(symbol_id)

    def build_from_materials(self, materials):
        for chapter in materials.get("chapters", []):
            chapter_id = f"chapter:{chapter['number']}"
            self.add_node(
                chapter_id,
                "chapter",
                chapter["title"],
                number=chapter["number"],
            )
            for section in chapter.get("sections", []):
                section_id = f"section:{section['number']}"
                self.add_node(
                    section_id,
                    "section",
                    section["title"],
                    number=section["number"],
                    chapter_number=chapter["number"],
                )
                self.add_edge(chapter_id, section_id, "CONTAINS_SECTION", 1.0)
                self.add_edge(section_id, chapter_id, "BELONGS_TO_CHAPTER", 1.0)
                for instruction in section.get("instructions", []):
                    self.add_instruction(chapter, section, instruction, chapter_id, section_id)
        self.add_family_edges()
        self.add_concept_contrasts()

    def add_instruction(self, chapter, section, instruction, chapter_id, section_id):
        instruction_id = f"instruction:{instruction['number']}"
        text = render_instruction_chunk(chapter, section, instruction)
        self.add_node(
            instruction_id,
            "instruction",
            instruction["title"].replace("`", ""),
            number=instruction["number"],
            chapter_number=chapter["number"],
            chapter_title=chapter["title"],
            section_number=section["number"],
            section_title=section["title"],
            text=text,
        )
        self.instruction_ids_by_section[section_id].append(instruction_id)
        self.add_edge(section_id, instruction_id, "CONTAINS_INSTRUCTION", 1.0)
        self.add_edge(instruction_id, section_id, "BELONGS_TO_SECTION", 1.0)

        for symbol in instruction_names_from_title(instruction["title"]):
            self.add_symbol(instruction_id, symbol)

        for index, format_row in enumerate(extract_format_rows(instruction)):
            self.add_format(instruction_id, instruction["number"], index, format_row)

        for parameter_row in extract_parameter_rows(instruction.get("parameters", "")):
            self.add_operand_role(instruction_id, instruction["number"], parameter_row)

        intrinsic_text = "\n".join(
            instruction.get(field, "")
            for field in ("intrinsics", "notes", "semantics", "assembly_examples")
        )
        for intrinsic in extract_intrinsics(intrinsic_text):
            intrinsic_id = f"intrinsic:{intrinsic}"
            self.add_node(intrinsic_id, "intrinsic", intrinsic)
            self.add_edge(instruction_id, intrinsic_id, "HAS_INTRINSIC", 1.0)
            self.add_edge(intrinsic_id, instruction_id, "INTRINSIC_OF", 1.0)
            self.add_alias_mapping(intrinsic, instruction_id, intrinsic_id)
            self.add_intrinsic_prefix_aliases(intrinsic, instruction_id, intrinsic_id)

        for concept in extract_concepts(chapter, section, instruction):
            self.add_concept(instruction_id, concept)

    def add_symbol(self, instruction_id, symbol):
        symbol = symbol.strip()
        symbol_id = f"symbol:{symbol}"
        self.add_node(symbol_id, "symbol", symbol, normalized=normalize_instruction_symbol(symbol))
        self.add_edge(instruction_id, symbol_id, "HAS_SYMBOL", 1.0)
        self.add_edge(symbol_id, instruction_id, "SYMBOL_OF", 1.0)
        self.symbol_to_instruction_ids[norm_key(symbol)].add(instruction_id)
        self.symbols_by_instruction[instruction_id].append(symbol_id)
        for alias in symbol_family_aliases(symbol):
            self.add_alias_mapping(alias, instruction_id, symbol_id)

        for alias in expand_template_aliases(symbol):
            alias_id = f"alias:{alias}"
            self.add_node(alias_id, "alias", alias, canonical=symbol)
            self.add_edge(alias_id, symbol_id, "ALIAS_OF", 1.0)
            self.add_edge(symbol_id, alias_id, "HAS_ALIAS", 0.9)
            for alias_key in symbol_family_aliases(alias):
                self.add_alias_mapping(alias_key, instruction_id, symbol_id)

    def add_intrinsic_prefix_aliases(self, intrinsic, instruction_id, intrinsic_id):
        parts = intrinsic.split("_")
        for end in range(2, len(parts)):
            prefix = "_".join(parts[:end])
            self.add_alias_mapping(prefix, instruction_id, intrinsic_id)
            self.add_alias_mapping(prefix + "_", instruction_id, intrinsic_id)
            self.add_alias_mapping(prefix + "_*", instruction_id, intrinsic_id)

    def add_format(self, instruction_id, instruction_number, index, format_row):
        format_id = f"format:{instruction_number}:{index}"
        self.add_node(
            format_id,
            "format",
            format_row["text"],
            mnemonic=format_row["mnemonic"],
            operands=format_row["operands"],
            operand_refs=format_row["operand_refs"],
        )
        self.add_edge(instruction_id, format_id, "HAS_FORMAT", 1.0)
        for alias in symbol_family_aliases(format_row["mnemonic"]):
            self.add_alias_mapping(alias, instruction_id, format_id)
        for operand in format_row["operand_refs"]:
            if operand:
                operand_id = f"operand:{operand}"
                self.add_node(operand_id, "operand", operand)
                self.add_edge(format_id, operand_id, "USES_OPERAND", 0.8)

    def add_operand_role(self, instruction_id, instruction_number, parameter_row):
        parameter_label = parameter_row["parameter"].replace("`", "")
        role_id = f"operand_role:{instruction_number}:{parameter_label}"
        self.add_node(
            role_id,
            "operand_role",
            parameter_label,
            parameter=parameter_label,
            meaning=parameter_row["meaning"].replace("`", ""),
            operand_refs=parameter_row["operand_refs"],
        )
        self.add_edge(instruction_id, role_id, "HAS_OPERAND_ROLE", 1.0)
        for operand in parameter_row["operand_refs"]:
            operand_id = f"operand:{operand}"
            self.add_node(operand_id, "operand", operand)
            self.add_edge(role_id, operand_id, "DESCRIBES_OPERAND", 0.9)
            self.add_alias_mapping(operand, instruction_id, role_id)

    def add_concept(self, instruction_id, concept):
        cid = concept_id(concept)
        self.add_node(cid, "concept", concept.replace("_", " "))
        self.add_edge(instruction_id, cid, "HAS_CONCEPT", 0.8)
        self.add_edge(cid, instruction_id, "CONCEPT_OF", 0.8)
        self.concepts_by_instruction[instruction_id].add(concept)
        for alias in CONCEPT_ALIASES.get(concept, (concept, concept.replace("_", " "))):
            self.add_alias_mapping(alias, instruction_id, cid)

    def add_family_edges(self):
        for instruction_id, symbol_ids in self.symbols_by_instruction.items():
            for left, right in itertools.permutations(sorted(set(symbol_ids)), 2):
                self.add_edge(left, right, "SAME_FAMILY_AS", 0.8, reason="same_instruction_record")

        for section_id, instruction_ids in self.instruction_ids_by_section.items():
            for left, right in itertools.permutations(sorted(set(instruction_ids)), 2):
                self.add_edge(left, right, "SAME_SECTION_AS", 0.3, section_id=section_id)

        for concept, instruction_ids in self.instructions_grouped_by_concept().items():
            if len(instruction_ids) > 20:
                continue
            for left, right in itertools.permutations(sorted(instruction_ids), 2):
                self.add_edge(left, right, "SHARES_CONCEPT_WITH", 0.25, concept=concept)

        for symbol_id in list(self.nodes):
            if not symbol_id.startswith("symbol:"):
                continue
            label = self.nodes[symbol_id]["label"]
            for other_id in list(self.nodes):
                if other_id <= symbol_id or not other_id.startswith("symbol:"):
                    continue
                other_label = self.nodes[other_id]["label"]
                if self.is_symbol_contrast(label, other_label):
                    self.add_edge(symbol_id, other_id, "CONTRASTS_WITH", 0.9)
                    self.add_edge(other_id, symbol_id, "CONTRASTS_WITH", 0.9)

    def instructions_grouped_by_concept(self):
        grouped = defaultdict(list)
        for instruction_id, concepts in self.concepts_by_instruction.items():
            for concept in concepts:
                grouped[concept].append(instruction_id)
        return grouped

    def is_symbol_contrast(self, left, right):
        pairs = (
            ("vluxei", "vloxei"),
            ("vsuxei", "vsoxei"),
            ("vluxseg", "vloxseg"),
            ("vsuxseg", "vsoxseg"),
            ("vwop.vv", "vwop.wv"),
            ("vwop.vx", "vwop.wx"),
            ("vnop.wv", "vwop.wv"),
            ("vnop.wx", "vwop.wx"),
        )
        for left_prefix, right_prefix in pairs:
            if left.startswith(left_prefix) and right.startswith(right_prefix):
                return True
            if left.startswith(right_prefix) and right.startswith(left_prefix):
                return True
        return False

    def add_concept_contrasts(self):
        for left, right in CONCEPT_CONTRASTS:
            left_id = concept_id(left)
            right_id = concept_id(right)
            self.add_node(left_id, "concept", left.replace("_", " "))
            self.add_node(right_id, "concept", right.replace("_", " "))
            self.add_edge(left_id, right_id, "CONTRASTS_WITH", 1.0)
            self.add_edge(right_id, left_id, "CONTRASTS_WITH", 1.0)

    def build_question_hints(self, questions):
        hints = []
        for row in questions:
            question = row["question"]
            symbols = extract_query_symbols(question)
            intents = [
                intent
                for intent, pattern in INTENT_RULES
                if pattern.search(question)
            ]
            matched_nodes = defaultdict(set)
            for symbol in symbols:
                for key in candidate_alias_keys(symbol):
                    for node_id in self.alias_index.get(norm_key(key), set()):
                        matched_nodes[symbol].add(node_id)
            for concept in extract_question_concepts(question):
                cid = concept_id(concept)
                if cid in self.nodes:
                    matched_nodes[f"concept:{concept}"].add(cid)
                for node_id in self.alias_index.get(norm_key(concept), set()):
                    matched_nodes[f"concept:{concept}"].add(node_id)
            hints.append(
                {
                    "id": row["id"],
                    "symbols": symbols,
                    "concepts": extract_question_concepts(question),
                    "intents": intents,
                    "matched_nodes": {
                        symbol: sorted(node_ids)
                        for symbol, node_ids in sorted(matched_nodes.items())
                    },
                }
            )
        return hints

    def write_artifacts(self, nodes_path, edges_path, alias_index_path, summary_path):
        nodes = sorted(self.nodes.values(), key=lambda item: item["node_id"])
        edges = sorted(self.edges.values(), key=lambda item: item["edge_id"])
        alias_index = {
            key: sorted(value)
            for key, value in sorted(self.alias_index.items())
        }
        write_jsonl(nodes_path, nodes)
        write_jsonl(edges_path, edges)
        write_json(alias_index_path, alias_index)
        summary = {
            "node_count": len(nodes),
            "edge_count": len(edges),
            "alias_count": len(alias_index),
            "nodes_by_type": dict(Counter(node["type"] for node in nodes)),
            "edges_by_type": dict(Counter(edge["type"] for edge in edges)),
        }
        write_json(summary_path, summary)
        return summary


def extract_query_symbols(question):
    symbols = set(re.findall(r"`([^`]+)`", question))
    symbols.update(re.findall(r"__riscv_[A-Za-z0-9_]+", question))
    symbols.update(re.findall(r"\b[v][a-z0-9]+(?:\.[a-z0-9]+)?(?:ff)?\.v\b", question, flags=re.I))
    symbols.update(re.findall(r"\b[v][a-z0-9]+(?:\.[a-z0-9]+)\b", question, flags=re.I))
    symbols.update(re.findall(r"\b(?:vd|vs1|vs2|vs3|rs1|rs2|imm|vm|v0\.t|SEW|LMUL|EEW|AVL|vl|vtype|vxrm|vxsat)\b", question))
    return sorted(symbol.strip() for symbol in symbols if symbol.strip())


def extract_question_concepts(question):
    return sorted(
        concept
        for concept, pattern in QUESTION_CONCEPT_RULES
        if pattern.search(question)
    )


def candidate_alias_keys(symbol):
    cleaned = symbol.strip().strip("`")
    keys = set()
    for part in re.split(r"\s*/\s*", cleaned):
        if not part:
            continue
        if part.startswith("."):
            keys.add(part)
            continue
        normalized = normalize_instruction_symbol(part)
        keys.add(part)
        keys.add(normalized)
        for candidate in (part, normalized):
            if "." in candidate:
                keys.add(candidate.split(".", 1)[0])
        collapsed = re.sub(r"<[^>]+>", "", normalized)
        if collapsed:
            keys.add(collapsed)
    return sorted(set(keys))


def build_graph(materials_path, questions_path):
    materials = read_json(materials_path)
    questions = read_jsonl(questions_path)
    validate_qa_questions(questions)
    builder = GraphBuilder()
    builder.build_from_materials(materials)
    question_hints = builder.build_question_hints(questions)
    return builder, question_hints


def main():
    parser = argparse.ArgumentParser(description="Build deterministic GraphRAG artifacts for RVV QA.")
    parser.add_argument("--materials", default=str(DEFAULT_MATERIALS))
    parser.add_argument("--questions", default=str(DEFAULT_QUESTIONS))
    parser.add_argument("--nodes-output", default=str(DEFAULT_NODES))
    parser.add_argument("--edges-output", default=str(DEFAULT_EDGES))
    parser.add_argument("--alias-index-output", default=str(DEFAULT_ALIAS_INDEX))
    parser.add_argument("--question-hints-output", default=str(DEFAULT_QUESTION_HINTS))
    parser.add_argument("--summary-output", default=str(DEFAULT_SUMMARY))
    args = parser.parse_args()

    builder, question_hints = build_graph(
        materials_path=Path(args.materials),
        questions_path=Path(args.questions),
    )
    summary = builder.write_artifacts(
        nodes_path=Path(args.nodes_output),
        edges_path=Path(args.edges_output),
        alias_index_path=Path(args.alias_index_output),
        summary_path=Path(args.summary_output),
    )
    write_jsonl(args.question_hints_output, question_hints)
    matched = sum(1 for row in question_hints if row["matched_nodes"])
    print(
        "graph artifacts written: "
        f"nodes={summary['node_count']} edges={summary['edge_count']} "
        f"aliases={summary['alias_count']} question_hints={len(question_hints)} "
        f"questions_with_matches={matched}",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
