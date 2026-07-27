#!/usr/bin/env python3
import argparse
import json
import re
from collections import defaultdict
from pathlib import Path


BENCHMARK_DIR = Path(__file__).resolve().parents[2]
REPO_DIR = BENCHMARK_DIR.parent
DEFAULT_QUESTIONS = BENCHMARK_DIR / "data/questions.jsonl"
DEFAULT_RESULTS_DIR = BENCHMARK_DIR / "results/qa"
DEFAULT_CATEGORIES_OUTPUT = DEFAULT_RESULTS_DIR / "question_categories.jsonl"
DEFAULT_SUMMARY_OUTPUT = DEFAULT_RESULTS_DIR / "category_summary.json"

CATEGORY_DESCRIPTIONS = {
    "scenario_selection": (
        "场景选型：根据 kernel、compiler、runtime 或行为线索选择指令族"
    ),
    "verification_correction": (
        "校验纠错：检查 reviewer、claim、note 或已有说法是否正确"
    ),
    "comparison_relation": (
        "对比关系：区分、比较、分组或解释多个指令/指令族之间的关系"
    ),
    "direct_lookup": (
        "直接查询：围绕一个指令或指令族给出格式、语义、operand 和 intrinsic"
    ),
}

# These patterns describe the question's information need, not the RVV topic.
SCENARIO_RE = re.compile(
    r"\b(?:kernel|compiler|runtime|code generator|data-layout|streaming-window|"
    r"table-lookup|scalar/vector bridge|floating-point reduction|"
    r"a reviewer needs|needs to|needs vector|choose the|select the|which rvv|"
    r"behavior clue|behaviour clue)\b",
    re.IGNORECASE,
)
VERIFICATION_RE = re.compile(
    r"\b(?:reviewer|review|code review|claim|claims|verify|check that|"
    r"correct or incorrect|simplification|statement|note says|note describes|"
    r"summary says|table claims|slide note|compiler note)\b",
    re.IGNORECASE,
)
COMPARISON_RE = re.compile(
    r"\b(?:compare|comparison|distinguish|difference|differentiate|versus|"
    r"interchangeable|not interchangeable|contrast|grouped overview|family overview|"
    r"related forms|both sides|from .* from|among)\b",
    re.IGNORECASE,
)

METRIC_BLOCKS = ("instruction", "operand", "intrinsic", "overall")
METRICS = ("accuracy", "precision", "f1", "faithfulness")


def classify_question(question):
    if SCENARIO_RE.search(question):
        return "scenario_selection", "scenario_keywords"
    if VERIFICATION_RE.search(question):
        return "verification_correction", "verification_keywords"
    if COMPARISON_RE.search(question):
        return "comparison_relation", "comparison_keywords"
    return "direct_lookup", "default_direct_lookup"


def load_jsonl(path):
    with Path(path).open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def write_jsonl(path, rows):
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def classify_questions(questions):
    classified = []
    for question in questions:
        category, rule = classify_question(question["question"])
        classified.append(
            {
                "id": question["id"],
                "category": category,
                "classification_rule": rule,
                "question": question["question"],
            }
        )
    return classified


def mean(values):
    if not values:
        return None
    return round(sum(values) / len(values), 4)


def summarize_method(metrics, categories_by_id):
    grouped = defaultdict(list)
    for row in metrics:
        category = categories_by_id.get(row.get("id"))
        if category:
            grouped[category].append(row)

    summary = {}
    for category in CATEGORY_DESCRIPTIONS:
        rows = grouped.get(category, [])
        category_summary = {
            "num_questions": len(rows),
            "coverage": round(len(rows) / len(categories_by_id), 4)
            if categories_by_id
            else 0.0,
        }
        for block in METRIC_BLOCKS:
            category_summary[block] = {
                metric: mean(
                    [
                        float(row[block][metric])
                        for row in rows
                        if isinstance(row.get(block), dict)
                        and row[block].get(metric) is not None
                    ]
                )
                for metric in METRICS
            }
        summary[category] = category_summary
    return summary


def load_method_metrics(results_dir, requested_methods):
    root = Path(results_dir)
    if requested_methods:
        method_names = requested_methods
    else:
        method_names = sorted(
            path.name for path in root.iterdir() if (path / "metrics.jsonl").exists()
        )

    loaded = {}
    for method in method_names:
        path = root / method / "metrics.jsonl"
        if not path.exists():
            raise FileNotFoundError(f"metrics file not found: {path}")
        loaded[method] = load_jsonl(path)
    return loaded


def main():
    parser = argparse.ArgumentParser(
        description="Classify QA questions and aggregate QA metrics by category."
    )
    parser.add_argument("--questions", default=str(DEFAULT_QUESTIONS))
    parser.add_argument("--results-dir", default=str(DEFAULT_RESULTS_DIR))
    parser.add_argument("--categories-output", default=str(DEFAULT_CATEGORIES_OUTPUT))
    parser.add_argument("--summary-output", default=str(DEFAULT_SUMMARY_OUTPUT))
    parser.add_argument(
        "--methods",
        default=None,
        help="Comma-separated method directory names; default: every method with metrics.jsonl",
    )
    args = parser.parse_args()

    questions = load_jsonl(args.questions)
    classified = classify_questions(questions)
    write_jsonl(args.categories_output, classified)
    categories_by_id = {row["id"]: row["category"] for row in classified}

    requested_methods = None
    if args.methods:
        requested_methods = [method.strip() for method in args.methods.split(",") if method.strip()]
    method_metrics = load_method_metrics(args.results_dir, requested_methods)

    category_counts = {
        category: sum(row["category"] == category for row in classified)
        for category in CATEGORY_DESCRIPTIONS
    }
    output = {
        "num_questions": len(classified),
        "categories": {
            category: {
                "description": CATEGORY_DESCRIPTIONS[category],
                "num_questions": category_counts[category],
                "fraction": round(category_counts[category] / len(classified), 4)
                if classified
                else 0.0,
            }
            for category in CATEGORY_DESCRIPTIONS
        },
        "methods": {
            method: summarize_method(metrics, categories_by_id)
            for method, metrics in method_metrics.items()
        },
    }
    output_path = Path(args.summary_output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(output, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    print(f"classified={len(classified)} -> {args.categories_output}")
    for category, count in category_counts.items():
        print(f"{category}: {count}")
    print(f"methods={len(method_metrics)} -> {args.summary_output}")


if __name__ == "__main__":
    main()
