#!/usr/bin/env python3
"""Download RV-CodeBase artifacts from HuggingFace.

Each subset is fetched and placed at its canonical location in this repo.

Usage:
  python download.py                       # all subsets
  python download.py --subset sft          # one subset
  python download.py --subset sft pipeline # multiple subsets
  python download.py --subset models       # all merged SFT models
  python download.py --list                # show available subsets
  python download.py --force --subset sft  # re-download even if present

Authentication:
  Some dataset/model repos are private. Provide an HF token with read access by
  either running `hf auth login` once, or exporting HF_TOKEN.
"""
import argparse
import shutil
import sys
from pathlib import Path

try:
    from huggingface_hub import snapshot_download
except ImportError:
    snapshot_download = None


REPO_DIR = Path(__file__).resolve().parent
DATASET_REPO = "RV-CodeBase/dataset"
MODEL_REPOS = {
    "qwen3.5-9b-sft": "RV-CodeBase/qwen3.5-9b-sft",
    "qwen3.5-27b-sft": "RV-CodeBase/qwen3.5-27b-sft",
    "gemma4-12b-sft": "RV-CodeBase/gemma4-12b-sft",
    "gemma4-31b-sft": "RV-CodeBase/gemma4-31b-sft",
    "deepseek-coder-7b-sft": "RV-CodeBase/deepseek-coder-7b-sft",
    "deepseek-coder-33b-sft": "RV-CodeBase/deepseek-coder-33b-sft",
    "codellama-13b-sft": "RV-CodeBase/codellama-13b-sft",
    "codellama-34b-sft": "RV-CodeBase/codellama-34b-sft",
}

# subset -> (repo_id, repo_type, remote_prefix, local_target)
# remote_prefix "" means the entire repo (use for model checkpoints).
SUBSETS = {
    "sft":       (DATASET_REPO, "dataset", "sft",       REPO_DIR / "sft" / "data"),
    "pipeline":  (DATASET_REPO, "dataset", "data",      REPO_DIR / "data"),
    "model-qwen3.5-9b-sft": (
        MODEL_REPOS["qwen3.5-9b-sft"], "model", "",
        REPO_DIR / "sft" / "results" / "qwen3.5-9b-merged",
    ),
    "model-qwen3.5-27b-sft": (
        MODEL_REPOS["qwen3.5-27b-sft"], "model", "",
        REPO_DIR / "sft" / "results" / "qwen3.5-27b-merged",
    ),
    "model-gemma4-12b-sft": (
        MODEL_REPOS["gemma4-12b-sft"], "model", "",
        REPO_DIR / "sft" / "results" / "gemma-4-12b-it-merged",
    ),
    "model-gemma4-31b-sft": (
        MODEL_REPOS["gemma4-31b-sft"], "model", "",
        REPO_DIR / "sft" / "results" / "gemma-4-31b-it-merged",
    ),
    "model-deepseek-coder-7b-sft": (
        MODEL_REPOS["deepseek-coder-7b-sft"], "model", "",
        REPO_DIR / "sft" / "results" / "deepseek-coder-7b-instruct-v1.5-merged",
    ),
    "model-deepseek-coder-33b-sft": (
        MODEL_REPOS["deepseek-coder-33b-sft"], "model", "",
        REPO_DIR / "sft" / "results" / "deepseek-coder-33b-instruct-merged",
    ),
    "model-codellama-13b-sft": (
        MODEL_REPOS["codellama-13b-sft"], "model", "",
        REPO_DIR / "sft" / "results" / "codellama-13b-instruct-merged",
    ),
    "model-codellama-34b-sft": (
        MODEL_REPOS["codellama-34b-sft"], "model", "",
        REPO_DIR / "sft" / "results" / "codellama-34b-instruct-merged",
    ),
}

GROUPS = {
    "models": [
        "model-qwen3.5-9b-sft",
        "model-qwen3.5-27b-sft",
        "model-gemma4-12b-sft",
        "model-gemma4-31b-sft",
        "model-deepseek-coder-7b-sft",
        "model-deepseek-coder-33b-sft",
        "model-codellama-13b-sft",
        "model-codellama-34b-sft",
    ],
}

SKIP_NAMES = {".cache", ".gitattributes", ".huggingface", ".DS_Store"}


def fetch(name, repo_id, repo_type, remote_prefix, local_target, force=False):
    if snapshot_download is None:
        sys.exit("huggingface_hub not installed.\n  pip install huggingface_hub")

    populated = local_target.exists() and any(local_target.iterdir())
    if populated and not force:
        print(f"[skip] {name}: {local_target.relative_to(REPO_DIR)} already populated (--force to redownload)")
        return

    rel_target = local_target.relative_to(REPO_DIR)
    print(f"[fetch] {name}: {repo_id}:{remote_prefix or '/'} -> {rel_target}")

    local_target.parent.mkdir(parents=True, exist_ok=True)
    staging = local_target.parent / f".hf-staging-{name}"
    if staging.exists():
        shutil.rmtree(staging)

    allow_patterns = None
    if remote_prefix:
        allow_patterns = [f"{remote_prefix}/*", f"{remote_prefix}/**"]

    snapshot_download(
        repo_id=repo_id,
        repo_type=repo_type,
        allow_patterns=allow_patterns,
        local_dir=str(staging),
    )

    source_root = staging / remote_prefix if remote_prefix else staging
    if not source_root.is_dir():
        shutil.rmtree(staging)
        sys.exit(f"[error] {name}: nothing at '{remote_prefix}' in {repo_id}")

    local_target.mkdir(parents=True, exist_ok=True)
    for item in source_root.iterdir():
        if item.name in SKIP_NAMES:
            continue
        dest = local_target / item.name
        if dest.exists():
            if dest.is_dir():
                shutil.rmtree(dest)
            else:
                dest.unlink()
        shutil.move(str(item), str(dest))

    shutil.rmtree(staging)
    print(f"[done] {name}")


def main():
    parser = argparse.ArgumentParser(
        description="Download RV-CodeBase data and models from HuggingFace.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Subsets: " + ", ".join(list(SUBSETS.keys()) + list(GROUPS.keys())),
    )
    parser.add_argument(
        "--subset",
        nargs="+",
        choices=list(SUBSETS.keys()) + list(GROUPS.keys()),
        help="which subsets to download (default: all)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="redownload even if the local target is non-empty",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="list available subsets and exit",
    )
    args = parser.parse_args()

    if args.list:
        width = max(len(n) for n in list(SUBSETS) + list(GROUPS))
        for name, (repo_id, repo_type, prefix, target) in SUBSETS.items():
            remote = f"{repo_id}:{prefix or '/'}"
            print(f"  {name:<{width}}  {remote:<40}  -> {target.relative_to(REPO_DIR)}")
        for name, members in GROUPS.items():
            print(f"  {name:<{width}}  group: {', '.join(members)}")
        return 0

    requested = args.subset if args.subset else list(SUBSETS.keys())
    targets = []
    seen = set()
    for name in requested:
        expanded = GROUPS.get(name, [name])
        for target in expanded:
            if target not in seen:
                targets.append(target)
                seen.add(target)

    for name in targets:
        repo_id, repo_type, prefix, target = SUBSETS[name]
        fetch(name, repo_id, repo_type, prefix, target, force=args.force)


if __name__ == "__main__":
    sys.exit(main() or 0)
