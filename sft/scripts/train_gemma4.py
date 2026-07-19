#!/usr/bin/env python3
"""Text-only LoRA fine-tuning for Gemma 4 unified models."""

import argparse
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import torch
import torch.distributed as dist
import yaml
from peft import LoraConfig, TaskType, get_peft_model
from torch.utils.data import Dataset
from transformers import (
    AutoModelForMultimodalLM,
    AutoProcessor,
    Trainer,
    TrainingArguments,
    set_seed,
)
from transformers.trainer_utils import get_last_checkpoint


class JsonlSftDataset(Dataset):
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        with self.path.open(encoding="utf-8") as handle:
            self.rows = [json.loads(line) for line in handle if line.strip()]

    def __len__(self) -> int:
        return len(self.rows)

    def __getitem__(self, index: int) -> dict[str, Any]:
        return self.rows[index]


@dataclass
class Gemma4TextCollator:
    tokenizer: Any
    max_length: int
    min_response_tokens: int
    pad_to_multiple_of: int = 8

    def _encode(self, row: dict[str, Any]) -> tuple[list[int], list[int]]:
        instruction = str(row.get("instruction", "")).strip()
        query = str(row.get("input", "")).strip()
        response = str(row.get("output", "")).strip()
        user_text = instruction if not query else f"{instruction}\n\n{query}"

        messages = [{"role": "user", "content": user_text}]
        prompt = self.tokenizer.apply_chat_template(
            messages,
            tokenize=False,
            add_generation_prompt=True,
            enable_thinking=False,
        )

        prompt_ids = self.tokenizer(prompt, add_special_tokens=False).input_ids
        response_ids = self.tokenizer(
            response + "<turn|>\n", add_special_tokens=False
        ).input_ids

        if len(prompt_ids) + len(response_ids) > self.max_length:
            response_budget = min(
                len(response_ids),
                max(self.min_response_tokens, self.max_length // 4),
            )
            prompt_budget = self.max_length - response_budget
            prompt_ids = prompt_ids[:prompt_budget]
            response_ids = response_ids[: self.max_length - len(prompt_ids)]

        input_ids = prompt_ids + response_ids
        labels = [-100] * len(prompt_ids) + response_ids
        return input_ids, labels

    def __call__(self, rows: list[dict[str, Any]]) -> dict[str, torch.Tensor]:
        encoded = [self._encode(row) for row in rows]
        max_len = max(len(input_ids) for input_ids, _ in encoded)
        if self.pad_to_multiple_of:
            multiple = self.pad_to_multiple_of
            max_len = ((max_len + multiple - 1) // multiple) * multiple

        pad_id = self.tokenizer.pad_token_id
        if pad_id is None:
            pad_id = self.tokenizer.eos_token_id

        input_batch = []
        attention_batch = []
        label_batch = []
        for input_ids, labels in encoded:
            padding = max_len - len(input_ids)
            input_batch.append(input_ids + [pad_id] * padding)
            attention_batch.append([1] * len(input_ids) + [0] * padding)
            label_batch.append(labels + [-100] * padding)

        return {
            "input_ids": torch.tensor(input_batch, dtype=torch.long),
            "attention_mask": torch.tensor(attention_batch, dtype=torch.long),
            "labels": torch.tensor(label_batch, dtype=torch.long),
        }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True, help="Gemma 4 training YAML")
    parser.add_argument("--model", help="override model_name_or_path")
    parser.add_argument(
        "--resume",
        nargs="?",
        const="auto",
        help="resume from a checkpoint path, or latest checkpoint when omitted",
    )
    return parser.parse_args()


def load_config(path: str | Path) -> dict[str, Any]:
    with Path(path).open(encoding="utf-8") as handle:
        config = yaml.safe_load(handle)
    if not isinstance(config, dict):
        raise ValueError(f"Expected a YAML mapping in {path}")
    return config


def resolve_resume(output_dir: Path, requested: str | None) -> str | None:
    if requested and requested != "auto":
        return requested
    if not output_dir.is_dir():
        return None
    return get_last_checkpoint(str(output_dir))


def configure_fsdp_loading(config: dict[str, Any]) -> bool:
    if not config.get("fsdp"):
        return False
    if "LOCAL_RANK" not in os.environ:
        raise RuntimeError("FSDP training must be launched with torchrun.")

    local_rank = int(os.environ["LOCAL_RANK"])
    torch.cuda.set_device(local_rank)
    if not dist.is_initialized():
        dist.init_process_group(backend="nccl")

    fsdp_config = config.get("fsdp_config", {})
    os.environ["ACCELERATE_USE_FSDP"] = "true"
    os.environ["FSDP_CPU_RAM_EFFICIENT_LOADING"] = str(
        fsdp_config.get("cpu_ram_efficient_loading", True)
    ).lower()
    os.environ["FSDP_SYNC_MODULE_STATES"] = "true"
    layer_classes = fsdp_config.get("transformer_layer_cls_to_wrap", [])
    if layer_classes:
        os.environ["FSDP_TRANSFORMER_CLS_TO_WRAP"] = ",".join(layer_classes)
    return True


def main() -> None:
    args = parse_args()
    config = load_config(args.config)
    model_path = args.model or config["model_name_or_path"]
    output_dir = Path(config["output_dir"])
    seed = int(config.get("seed", 42))
    set_seed(seed)
    use_fsdp = configure_fsdp_loading(config)

    processor = AutoProcessor.from_pretrained(
        model_path,
        local_files_only=bool(config.get("local_files_only", True)),
        trust_remote_code=bool(config.get("trust_remote_code", True)),
    )
    tokenizer = processor.tokenizer
    tokenizer.padding_side = "right"

    model = AutoModelForMultimodalLM.from_pretrained(
        model_path,
        dtype=torch.bfloat16,
        attn_implementation=config.get("attn_implementation", "sdpa"),
        low_cpu_mem_usage=True,
        local_files_only=bool(config.get("local_files_only", True)),
        trust_remote_code=bool(config.get("trust_remote_code", True)),
    )
    model.config.use_cache = False

    target_modules = config.get(
        "lora_target_modules",
        (
            r"model\.language_model\.layers\.\d+\."
            r"(self_attn\.(q_proj|k_proj|v_proj|o_proj)|"
            r"mlp\.(gate_proj|up_proj|down_proj))"
        ),
    )
    lora_config = LoraConfig(
        task_type=TaskType.CAUSAL_LM,
        r=int(config.get("lora_rank", 16)),
        lora_alpha=int(config.get("lora_alpha", 32)),
        lora_dropout=float(config.get("lora_dropout", 0.05)),
        target_modules=target_modules,
        bias="none",
    )
    model = get_peft_model(model, lora_config)
    model.enable_input_require_grads()
    model.print_trainable_parameters()

    train_dataset = JsonlSftDataset(config["train_file"])
    eval_dataset = JsonlSftDataset(config["eval_file"])
    collator = Gemma4TextCollator(
        tokenizer=tokenizer,
        max_length=int(config.get("cutoff_len", 8192)),
        min_response_tokens=int(config.get("min_response_tokens", 1024)),
    )

    training_args = TrainingArguments(
        output_dir=str(output_dir),
        do_train=True,
        do_eval=True,
        num_train_epochs=float(config.get("num_train_epochs", 3.0)),
        per_device_train_batch_size=int(config.get("per_device_train_batch_size", 1)),
        per_device_eval_batch_size=int(config.get("per_device_eval_batch_size", 1)),
        gradient_accumulation_steps=int(config.get("gradient_accumulation_steps", 4)),
        learning_rate=float(config.get("learning_rate", 1.0e-4)),
        weight_decay=float(config.get("weight_decay", 0.01)),
        warmup_steps=float(config.get("warmup_steps", 0)),
        lr_scheduler_type=config.get("lr_scheduler_type", "cosine"),
        max_grad_norm=float(config.get("max_grad_norm", 1.0)),
        bf16=True,
        tf32=bool(config.get("tf32", True)),
        gradient_checkpointing=not use_fsdp,
        gradient_checkpointing_kwargs={"use_reentrant": False},
        logging_steps=int(config.get("logging_steps", 10)),
        eval_strategy="steps",
        eval_steps=int(config.get("eval_steps", 250)),
        save_strategy="steps",
        save_steps=int(config.get("save_steps", 250)),
        save_total_limit=int(config.get("save_total_limit", 3)),
        report_to=config.get("report_to", ["tensorboard"]),
        dataloader_num_workers=int(config.get("dataloader_num_workers", 4)),
        dataloader_pin_memory=True,
        remove_unused_columns=False,
        ddp_find_unused_parameters=False,
        fsdp=config.get("fsdp"),
        fsdp_config=config.get("fsdp_config"),
        seed=seed,
        data_seed=seed,
    )

    trainer = Trainer(
        model=model,
        args=training_args,
        train_dataset=train_dataset,
        eval_dataset=eval_dataset,
        data_collator=collator,
        processing_class=tokenizer,
    )
    resume = resolve_resume(output_dir, args.resume or config.get("resume_from_checkpoint"))
    result = trainer.train(resume_from_checkpoint=resume)
    trainer.save_model()
    trainer.save_state()
    trainer.log_metrics("train", result.metrics)
    trainer.save_metrics("train", result.metrics)

    eval_metrics = trainer.evaluate()
    trainer.log_metrics("eval", eval_metrics)
    trainer.save_metrics("eval", eval_metrics)

    if trainer.is_world_process_zero():
        processor.save_pretrained(output_dir)


if __name__ == "__main__":
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
    try:
        main()
    finally:
        if dist.is_available() and dist.is_initialized():
            dist.destroy_process_group()
