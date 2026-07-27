#!/usr/bin/env python3
import argparse
import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from xml.sax.saxutils import escape


REPO_DIR = Path(__file__).resolve().parents[3]
DEFAULT_RESULTS_ROOT = REPO_DIR / "benchmark" / "results"
DEFAULT_OUTPUT = DEFAULT_RESULTS_ROOT / "performance_summary.xlsx"

BENCHMARKS = (
    ("tsvc", "TSVC", 151),
    ("polybenchc", "PolyBench/C", 30),
    ("rajaperf", "RAJAPerf", 46),
)

METRICS = (
    ("compile_pass_rate", "Comp. (%)", True),
    ("correct_pass_rate", "Corr. (%)", True),
    ("positive_rate", "S>1 (%)", True),
    ("geometric_mean_speedup", "Mean SR", False),
    ("max_speedup", "Max SR", False),
)

# A few historical result directories use inconsistent names. Keep that mapping
# explicit so every exported cell remains traceable in the Sources sheet.
MODELS = (
    ("CodeLlama-13B", "base", {"default": "codellama-13b"}),
    ("CodeLlama-13B-SFT", "sft", {"default": "codellama-13b-sft"}),
    (
        "CodeLlama-34B",
        "base",
        {
            "tsvc": "codellama-34b",
            "polybenchc": "codellama-31b",
            "rajaperf": "codellama-31b",
        },
    ),
    ("CodeLlama-34B-SFT", "sft", {"default": "codellama-34b-sft"}),
    ("DeepSeek-Coder-7B", "base", {"default": "deepseek-coder-7b"}),
    ("DeepSeek-Coder-7B-SFT", "sft", {"default": "deepseek-coder-7b-sft"}),
    ("DeepSeek-Coder-33B", "base", {"default": "deepseek-coder-33b"}),
    ("DeepSeek-Coder-33B-SFT", "sft", {"default": "deepseek-coder-33b-sft"}),
    (
        "Gemma4-12B",
        "base",
        {
            "tsvc": "gemma4-12b",
            "polybenchc": "gemma4-12b-base",
            "rajaperf": "gemma4-12b-base",
        },
    ),
    ("Gemma4-12B-SFT", "sft", {"default": "gemma4-12b-sft"}),
    ("Gemma4-31B", "base", {"default": "gemma4-31b"}),
    ("Gemma4-31B-SFT", "sft", {"default": "gemma4-31b-sft"}),
    ("Qwen3.5-9B", "base", {"default": "qwen3.5-9b"}),
    ("Qwen3.5-9B-SFT", "sft", {"default": "qwen3.5-9b-sft"}),
    ("Qwen3.5-27B", "base", {"default": "qwen3.5-27b"}),
    ("Qwen3.5-27B-SFT", "sft", {"default": "qwen3.5-27b-sft"}),
    ("DeepSeek-V4-Pro", "api", {"default": "deepseek"}),
    ("Kimi-K2.6", "api", {"default": "kimi"}),
    ("GPT-5.5", "api", {"default": "gpt"}),
)


def column_name(index):
    result = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        result = chr(65 + remainder) + result
    return result


def cell_ref(row, column):
    return f"{column_name(column)}{row}"


def string_cell(row, column, value, style=0):
    ref = cell_ref(row, column)
    text = escape(str(value))
    return f'<c r="{ref}" s="{style}" t="inlineStr"><is><t>{text}</t></is></c>'


def number_cell(row, column, value, style=0):
    ref = cell_ref(row, column)
    return f'<c r="{ref}" s="{style}"><v>{float(value):.10g}</v></c>'


def read_json(path):
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def result_dir_name(mapping, benchmark):
    return mapping.get(benchmark, mapping.get("default"))


def metric_value(block, key, percentage):
    raw = block.get(key)
    if raw is None:
        return 0.0
    value = float(raw)
    return value * 100.0 if percentage else value


def collect_data(results_root):
    records = []
    sources = []
    for model_name, category, mapping in MODELS:
        record = {"model": model_name, "category": category, "metrics": {}}
        for benchmark, label, expected in BENCHMARKS:
            directory_name = result_dir_name(mapping, benchmark)
            directory = results_root / benchmark / directory_name
            summary_path = directory / "summary.json"
            results_path = directory / "results.jsonl"
            if not summary_path.is_file():
                raise FileNotFoundError(f"missing summary: {summary_path}")
            summary = read_json(summary_path)
            samples = int(summary.get("num_samples", 0))
            result_lines = 0
            if results_path.is_file():
                with results_path.open(encoding="utf-8") as handle:
                    result_lines = sum(1 for _ in handle)
            record["metrics"][benchmark] = {
                "overall": summary.get("overall") or {},
                "round1": summary.get("round1") or {},
            }
            sources.append(
                {
                    "model": model_name,
                    "benchmark": label,
                    "directory": str(directory.relative_to(REPO_DIR)),
                    "samples": samples,
                    "result_lines": result_lines,
                    "expected": expected,
                    "complete": samples == expected and result_lines == expected,
                }
            )
        records.append(record)
    return records, sources


def best_values(records, phase):
    values = {}
    for benchmark, _, _ in BENCHMARKS:
        for key, _, percentage in METRICS:
            metric_values = [
                metric_value(item["metrics"][benchmark][phase], key, percentage)
                for item in records
            ]
            values[(benchmark, key)] = max(metric_values)
    return values


def performance_sheet(records, phase):
    rows = []
    rows.append(
        '<row r="1" ht="25" customHeight="1">'
        + string_cell(1, 1, "Model", 1)
        + string_cell(1, 2, "TSVC", 1)
        + string_cell(1, 7, "PolyBench/C", 1)
        + string_cell(1, 12, "RAJAPerf", 1)
        + "</row>"
    )
    header_cells = [string_cell(2, 1, "", 2)]
    column = 2
    for _benchmark, _label, _expected in BENCHMARKS:
        for _key, label, _percentage in METRICS:
            header_cells.append(string_cell(2, column, label, 2))
            column += 1
    rows.append(
        '<row r="2" ht="34" customHeight="1">'
        + "".join(header_cells)
        + "</row>"
    )

    best = best_values(records, phase)
    model_styles = {"base": 3, "sft": 4, "api": 5}
    for row_number, record in enumerate(records, start=3):
        cells = [
            string_cell(
                row_number,
                1,
                record["model"],
                model_styles[record["category"]],
            )
        ]
        column = 2
        for benchmark, _label, _expected in BENCHMARKS:
            block = record["metrics"][benchmark][phase]
            for key, _metric_label, percentage in METRICS:
                value = metric_value(block, key, percentage)
                is_best = abs(value - best[(benchmark, key)]) < 1e-9
                if percentage:
                    style = 10 if is_best else 6
                else:
                    style = 11 if is_best else 7
                cells.append(number_cell(row_number, column, value, style))
                column += 1
        rows.append(
            f'<row r="{row_number}" ht="19" customHeight="1">'
            + "".join(cells)
            + "</row>"
        )

    last_row = len(records) + 2
    return f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <sheetViews><sheetView workbookViewId="0" showGridLines="0"><pane xSplit="1" ySplit="2" topLeftCell="B3" activePane="bottomRight" state="frozen"/></sheetView></sheetViews>
  <sheetFormatPr defaultRowHeight="18"/>
  <cols><col min="1" max="1" width="29" customWidth="1"/><col min="2" max="16" width="12" customWidth="1"/></cols>
  <sheetData>{''.join(rows)}</sheetData>
  <mergeCells count="4"><mergeCell ref="A1:A2"/><mergeCell ref="B1:F1"/><mergeCell ref="G1:K1"/><mergeCell ref="L1:P1"/></mergeCells>
  <autoFilter ref="A2:P{last_row}"/>
  <pageMargins left="0.25" right="0.25" top="0.5" bottom="0.5" header="0.2" footer="0.2"/>
  <pageSetup orientation="landscape" fitToWidth="1" fitToHeight="0"/>
</worksheet>'''


def sources_sheet(sources):
    headers = (
        "Model",
        "Benchmark",
        "Source directory",
        "summary.num_samples",
        "results.jsonl rows",
        "Expected",
        "Complete",
    )
    rows = [
        '<row r="1" ht="25" customHeight="1">'
        + "".join(string_cell(1, index, value, 8) for index, value in enumerate(headers, 1))
        + "</row>"
    ]
    for row_number, source in enumerate(sources, start=2):
        cells = [
            string_cell(row_number, 1, source["model"], 9),
            string_cell(row_number, 2, source["benchmark"], 9),
            string_cell(row_number, 3, source["directory"], 9),
            number_cell(row_number, 4, source["samples"], 9),
            number_cell(row_number, 5, source["result_lines"], 9),
            number_cell(row_number, 6, source["expected"], 9),
            string_cell(row_number, 7, "Yes" if source["complete"] else "No", 9),
        ]
        rows.append(f'<row r="{row_number}">' + "".join(cells) + "</row>")
    last_row = len(sources) + 1
    return f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews>
  <sheetFormatPr defaultRowHeight="18"/>
  <cols><col min="1" max="1" width="27" customWidth="1"/><col min="2" max="2" width="16" customWidth="1"/><col min="3" max="3" width="62" customWidth="1"/><col min="4" max="7" width="20" customWidth="1"/></cols>
  <sheetData>{''.join(rows)}</sheetData>
  <autoFilter ref="A1:G{last_row}"/>
  <pageMargins left="0.4" right="0.4" top="0.5" bottom="0.5" header="0.2" footer="0.2"/>
</worksheet>'''


def styles_xml():
    return '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <numFmts count="2"><numFmt numFmtId="164" formatCode="0.00"/><numFmt numFmtId="165" formatCode="0.0000"/></numFmts>
  <fonts count="3">
    <font><sz val="10"/><name val="Aptos"/><family val="2"/></font>
    <font><b/><color rgb="FFFFFFFF"/><sz val="10"/><name val="Aptos Display"/><family val="2"/></font>
    <font><b/><sz val="10"/><name val="Aptos"/><family val="2"/></font>
  </fonts>
  <fills count="7">
    <fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill>
    <fill><patternFill patternType="solid"><fgColor rgb="FF17365D"/><bgColor indexed="64"/></patternFill></fill>
    <fill><patternFill patternType="solid"><fgColor rgb="FFDCE6F1"/><bgColor indexed="64"/></patternFill></fill>
    <fill><patternFill patternType="solid"><fgColor rgb="FFE2F0D9"/><bgColor indexed="64"/></patternFill></fill>
    <fill><patternFill patternType="solid"><fgColor rgb="FFFCE4D6"/><bgColor indexed="64"/></patternFill></fill>
    <fill><patternFill patternType="solid"><fgColor rgb="FFFFF2CC"/><bgColor indexed="64"/></patternFill></fill>
  </fills>
  <borders count="2">
    <border><left/><right/><top/><bottom/><diagonal/></border>
    <border><left style="thin"><color rgb="FFD9E1F2"/></left><right style="thin"><color rgb="FFD9E1F2"/></right><top style="thin"><color rgb="FFD9E1F2"/></top><bottom style="thin"><color rgb="FFD9E1F2"/></bottom><diagonal/></border>
  </borders>
  <cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>
  <cellXfs count="12">
    <xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>
    <xf numFmtId="0" fontId="1" fillId="2" borderId="1" xfId="0" applyAlignment="1"><alignment horizontal="center" vertical="center"/></xf>
    <xf numFmtId="0" fontId="1" fillId="2" borderId="1" xfId="0" applyAlignment="1"><alignment horizontal="center" vertical="center" wrapText="1"/></xf>
    <xf numFmtId="0" fontId="0" fillId="3" borderId="1" xfId="0" applyAlignment="1"><alignment vertical="center"/></xf>
    <xf numFmtId="0" fontId="2" fillId="4" borderId="1" xfId="0" applyAlignment="1"><alignment vertical="center"/></xf>
    <xf numFmtId="0" fontId="2" fillId="5" borderId="1" xfId="0" applyAlignment="1"><alignment vertical="center"/></xf>
    <xf numFmtId="164" fontId="0" fillId="0" borderId="1" xfId="0" applyNumberFormat="1" applyAlignment="1"><alignment horizontal="center" vertical="center"/></xf>
    <xf numFmtId="165" fontId="0" fillId="0" borderId="1" xfId="0" applyNumberFormat="1" applyAlignment="1"><alignment horizontal="center" vertical="center"/></xf>
    <xf numFmtId="0" fontId="1" fillId="2" borderId="1" xfId="0" applyAlignment="1"><alignment horizontal="center" vertical="center" wrapText="1"/></xf>
    <xf numFmtId="0" fontId="0" fillId="0" borderId="1" xfId="0" applyAlignment="1"><alignment vertical="center" wrapText="1"/></xf>
    <xf numFmtId="164" fontId="2" fillId="6" borderId="1" xfId="0" applyNumberFormat="1" applyAlignment="1"><alignment horizontal="center" vertical="center"/></xf>
    <xf numFmtId="165" fontId="2" fillId="6" borderId="1" xfId="0" applyNumberFormat="1" applyAlignment="1"><alignment horizontal="center" vertical="center"/></xf>
  </cellXfs>
  <cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>
  <dxfs count="0"/>
  <tableStyles count="0" defaultTableStyle="TableStyleMedium2" defaultPivotStyle="PivotStyleLight16"/>
</styleSheet>'''


def write_workbook(output, records, sources):
    output.parent.mkdir(parents=True, exist_ok=True)
    created = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    content_types = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
  <Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
  <Override PartName="/xl/worksheets/sheet2.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
  <Override PartName="/xl/worksheets/sheet3.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
  <Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>
  <Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>
  <Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>
</Types>'''
    root_rels = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>
  <Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/>
</Relationships>'''
    workbook = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <bookViews><workbookView xWindow="0" yWindow="0" windowWidth="24000" windowHeight="14000"/></bookViews>
  <sheets><sheet name="Overall" sheetId="1" r:id="rId1"/><sheet name="Round1" sheetId="2" r:id="rId2"/><sheet name="Sources" sheetId="3" r:id="rId3"/></sheets>
  <calcPr calcId="191029"/>
</workbook>'''
    workbook_rels = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet2.xml"/>
  <Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet3.xml"/>
  <Relationship Id="rId4" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
</Relationships>'''
    core = f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <dc:title>RISC-V Benchmark Performance Summary</dc:title><dc:creator>RV-CodeBase</dc:creator><cp:lastModifiedBy>RV-CodeBase</cp:lastModifiedBy><dcterms:created xsi:type="dcterms:W3CDTF">{created}</dcterms:created><dcterms:modified xsi:type="dcterms:W3CDTF">{created}</dcterms:modified>
</cp:coreProperties>'''
    app = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties" xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes"><Application>RV-CodeBase exporter</Application><AppVersion>1.0</AppVersion></Properties>'''

    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("_rels/.rels", root_rels)
        archive.writestr("docProps/core.xml", core)
        archive.writestr("docProps/app.xml", app)
        archive.writestr("xl/workbook.xml", workbook)
        archive.writestr("xl/_rels/workbook.xml.rels", workbook_rels)
        archive.writestr("xl/styles.xml", styles_xml())
        archive.writestr("xl/worksheets/sheet1.xml", performance_sheet(records, "overall"))
        archive.writestr("xl/worksheets/sheet2.xml", performance_sheet(records, "round1"))
        archive.writestr("xl/worksheets/sheet3.xml", sources_sheet(sources))


def main():
    parser = argparse.ArgumentParser(description="Export perf summaries to XLSX.")
    parser.add_argument("--results-root", default=str(DEFAULT_RESULTS_ROOT))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    args = parser.parse_args()

    results_root = Path(args.results_root).resolve()
    output = Path(args.output).resolve()
    records, sources = collect_data(results_root)
    write_workbook(output, records, sources)
    print(f"exported {len(records)} models to {output}")


if __name__ == "__main__":
    main()
