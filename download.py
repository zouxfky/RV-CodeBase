#!/usr/bin/env python3
"""Download RV-CodeBase artifacts from HuggingFace.

Each subset is fetched and placed at its canonical location in this repo.

Usage:
  python download.py                       # all subsets
  python download.py --subset benchmark    # one subset
  python download.py --subset rag sft      # multiple subsets
  python download.py --list                # show available subsets
  python download.py --force --subset sft  # re-download even if present

Authentication:
  The dataset repo is private. Provide an HF token with read access by either
  running `hf auth login` once, or exporting HF_TOKEN.
"""
import argparse
import shutil
import sys
from pathlib import Path

try:
    from huggingface_hub import snapshot_download
except ImportError:
    sys.exit("huggingface_hub not installed.\n  pip install huggingface_hub")


REPO_DIR = Path(__file__).resolve().parent
DATASET_REPO = "RV-CodeBase/dataset"

# subset -> (repo_id, repo_type, remote_prefix, local_target)
# remote_prefix "" means the entire repo (use for model checkpoints).
SUBSETS = {
    "benchmark": (DATASET_REPO, "dataset", "benchmark", REPO_DIR / "benchmark" / "data"),
    "rag":       (DATASET_REPO, "dataset", "rag",       REPO_DIR / "rag" / "data"),
    "sft":       (DATASET_REPO, "dataset", "sft",       REPO_DIR / "sft" / "data"),
    "pipeline":  (DATASET_REPO, "dataset", "data",      REPO_DIR / "data"),
    # Add model repos here when ready, e.g.:
    # "model-llama-8b": (
    #     "RV-CodeBase/Llama-3.1-8B-SFT", "model", "",
    #     REPO_DIR / "sft" / "results" / "llama-3.1-8b-sft",
    # ),
}

SKIP_NAMES = {".cache", ".gitattributes", ".huggingface", ".DS_Store"}


def fetch(name, repo_id, repo_type, remote_prefix, local_target, force=False):
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
        epilog="Subsets: " + ", ".join(SUBSETS.keys()),
    )
    parser.add_argument(
        "--subset",
        nargs="+",
        choices=list(SUBSETS.keys()),
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
        width = max(len(n) for n in SUBSETS)
        for name, (repo_id, repo_type, prefix, target) in SUBSETS.items():
            remote = f"{repo_id}:{prefix or '/'}"
            print(f"  {name:<{width}}  {remote:<40}  -> {target.relative_to(REPO_DIR)}")
        return 0

    targets = args.subset if args.subset else list(SUBSETS.keys())
    for name in targets:
        repo_id, repo_type, prefix, target = SUBSETS[name]
        fetch(name, repo_id, repo_type, prefix, target, force=args.force)


if __name__ == "__main__":
    sys.exit(main() or 0)
