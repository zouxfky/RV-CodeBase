"""Evaluation metrics, computed over all tasks of a benchmark.

    CR   correctness rate: share of tasks whose generated program compiles and
         passes the functional tests (result status "success"; "pass" in
         manual-mode rows).
    PSR  positive speedup rate: share of tasks that are correct and faster than
         the original program (speedup > 1).
    SR   speedup: geometric mean of original/generated execution time over all
         tasks; tasks that fail compilation or the functional tests, or have no
         result, count as 1.
"""
import math


def is_correct(row: dict | None) -> bool:
    return bool(row) and str(row.get("status", "")).strip() in ("success", "pass")


def speedup(row: dict | None) -> float:
    """Speedup of one task; 1.0 for failed or missing tasks."""
    if not is_correct(row):
        return 1.0
    try:
        value = float(row.get("best_speedup_ratio") or 0.0)
    except (TypeError, ValueError):
        return 1.0
    return value if value > 0 else 1.0


def compute(results: dict[str, dict], task_ids) -> dict:
    """CR / PSR in percent and SR for the given tasks.

    `results` maps task id to result row; tasks without a row count as failed.
    SR is None when no task is correct (shown as "--" in the tables).
    """
    ids = list(task_ids)
    if not ids:
        return {"tasks": 0, "cr": None, "psr": None, "sr": None}
    rows = [results.get(i) for i in ids]
    correct = sum(is_correct(r) for r in rows)
    positive = sum(is_correct(r) and speedup(r) > 1.0 for r in rows)
    sr = math.exp(sum(math.log(speedup(r)) for r in rows) / len(rows)) if correct else None
    return {
        "tasks": len(ids),
        "cr": 100.0 * correct / len(ids),
        "psr": 100.0 * positive / len(ids),
        "sr": sr,
    }
