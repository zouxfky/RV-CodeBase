#!/usr/bin/env python3
"""Render pairs.jsonl into alpaca-style SFT training data for Llama-Factory.

Input:
  - sft/data/pairs.jsonl
    rows: {pid, label, speedup, baseline, optimized}

Outputs:
  - sft/data/train.jsonl
  - sft/data/eval.jsonl
    rows: {pid, label, speedup, instruction, input, output}

Rendering rule:
  instruction = generate.md prompt template with {baseline_code} filled in
  input       = ""
  output      = positive: "<code>\\n" + optimized + "\\n</code>"
                negative: REJECT_MESSAGE + "\\n\\n<code>\\n" + baseline + "\\n</code>"

Train/eval split is stable per-pid (md5 bucket), so re-running with the same
--eval-ratio is reproducible.

Rows whose chat-templated total length exceeds --max-tokens (default 8192) are
dropped to match cutoff_len in the LoRA configs. Pass --max-tokens 0 to disable
the filter (no tokenizer load, faster).
"""
import argparse
import hashlib
import json
import random
import sys
from collections import Counter
from pathlib import Path


REPO_DIR = Path(__file__).resolve().parents[2]
DEFAULT_PAIRS = REPO_DIR / "sft" / "data" / "pairs.jsonl"
DEFAULT_PROMPT = REPO_DIR / "benchmark" / "common" / "prompts" / "generate.md"
DEFAULT_OUT_DIR = REPO_DIR / "sft" / "data"

REJECT_MESSAGE = (
    "No beneficial RVV optimization found; returning the original code unchanged."
)


def read_jsonl(path):
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            yield json.loads(line)


def write_jsonl(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def stable_split(pid, eval_ratio):
    h = hashlib.md5(pid.encode("utf-8")).hexdigest()
    bucket = int(h[:8], 16) / 0xFFFFFFFF
    return "eval" if bucket < eval_ratio else "train"


def render_instruction(template, baseline):
    return template.replace("{baseline_code}", baseline)


def render_output(label, baseline, optimized):
    body = optimized if label == "positive" else baseline
    prefix = "" if label == "positive" else REJECT_MESSAGE + "\n\n"
    return f"{prefix}<code>\n{body}\n</code>"


def build(args):
    template = Path(args.prompt).read_text(encoding="utf-8")

    tokenizer = None
    if args.max_tokens > 0:
        try:
            from transformers import AutoTokenizer
        except ImportError:
            sys.exit("--max-tokens requires `pip install transformers`. "
                     "Pass --max-tokens 0 to disable.")
        print(f"loading tokenizer for length filter: {args.tokenizer}")
        tokenizer = AutoTokenizer.from_pretrained(args.tokenizer, trust_remote_code=True)

    def too_long(instruction, output):
        if tokenizer is None:
            return False
        chat = [
            {"role": "user", "content": instruction},
            {"role": "assistant", "content": output},
        ]
        text = tokenizer.apply_chat_template(chat, tokenize=False, add_generation_prompt=False)
        return len(tokenizer.encode(text, add_special_tokens=False)) > args.max_tokens

    train_rows, eval_rows = [], []
    label_total = Counter()
    train_labels = Counter()
    eval_labels = Counter()
    dropped_long = 0

    for row in read_jsonl(args.pairs):
        pid = row["pid"]
        label = row["label"]
        baseline = row["baseline"]
        optimized = row["optimized"]

        instruction = render_instruction(template, baseline)
        output = render_output(label, baseline, optimized)

        if too_long(instruction, output):
            dropped_long += 1
            continue

        sample = {
            "pid": pid,
            "label": label,
            "speedup": row.get("speedup", 0.0),
            "instruction": instruction,
            "input": "",
            "output": output,
        }
        label_total[label] += 1
        if stable_split(pid, args.eval_ratio) == "eval":
            eval_rows.append(sample)
            eval_labels[label] += 1
        else:
            train_rows.append(sample)
            train_labels[label] += 1

    if args.shuffle:
        random.Random(args.seed_value).shuffle(train_rows)

    out_dir = Path(args.out_dir)
    write_jsonl(out_dir / "train.jsonl", train_rows)
    write_jsonl(out_dir / "eval.jsonl", eval_rows)

    print(f"pairs read:    {sum(label_total.values()) + dropped_long}")
    if dropped_long:
        print(f"  dropped (> {args.max_tokens} tokens): {dropped_long}")
    print(f"")
    print(f"train.jsonl    {len(train_rows):>6}  "
          f"(pos={train_labels['positive']}, neg={train_labels['negative']})  -> {out_dir / 'train.jsonl'}")
    print(f"eval.jsonl     {len(eval_rows):>6}  "
          f"(pos={eval_labels['positive']}, neg={eval_labels['negative']})  -> {out_dir / 'eval.jsonl'}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pairs", default=str(DEFAULT_PAIRS))
    ap.add_argument("--prompt", default=str(DEFAULT_PROMPT))
    ap.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    ap.add_argument("--eval-ratio", type=float, default=0.02,
                    help="fraction of pids routed to eval split (default: 0.02)")
    ap.add_argument("--max-tokens", type=int, default=8192,
                    help="drop rows whose chat-templated length exceeds this; "
                         "set to 0 to disable (default: 8192, matches LoRA cutoff_len)")
    ap.add_argument("--tokenizer", default="Qwen/Qwen2.5-7B",
                    help="tokenizer used for length check (default: Qwen/Qwen2.5-7B)")
    ap.add_argument("--shuffle", action="store_true",
                    help="shuffle train rows after split")
    ap.add_argument("--seed-value", type=int, default=42)
    args = ap.parse_args()
    build(args)


if __name__ == "__main__":
    sys.exit(main())
