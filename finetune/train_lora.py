"""LoRA fine-tune Qwen3-VL-2B-Instruct on page images, then merge the adapter into the base.

    uv run --group finetune python -m finetune.train_lora train --model finetune/out/base \
        --data finetune/data --set evals/datasets/spike-v0 --out finetune/out/adapter
    uv run --group finetune python -m finetune.train_lora merge --model finetune/out/base \
        --adapter finetune/out/adapter --out finetune/out/merged

Plain PyTorch loop, batch size 1, so the same file runs on a Mac (MPS) and on a Colab T4 (CUDA).
The loss counts only the answer tokens. LoRA goes on the language model's attention and MLP
projections; the vision tower and the projector stay frozen, so the vision projector that
llama.cpp converts later is the base model's own.
"""

from __future__ import annotations

import argparse
import json
import random
import time
from pathlib import Path
from typing import Any

from household_vault.safety import assert_safe_path

DPI = 200
TARGETS = r".*language_model.*\.(q_proj|k_proj|v_proj|o_proj|gate_proj|up_proj|down_proj)"


def pick_device() -> tuple[str, Any]:
    import torch

    if torch.cuda.is_available():
        # a free T4 has no bf16, so fp16 there
        return "cuda", torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16
    if torch.backends.mps.is_available():
        return "mps", torch.bfloat16
    return "cpu", torch.float32


def load_page(set_dir: Path, name: str, max_pixels: int) -> Any:
    from PIL import Image

    src = set_dir / name
    if src.suffix == ".pdf":
        import pypdfium2 as pdfium

        img = pdfium.PdfDocument(str(src))[0].render(scale=DPI / 72).to_pil().convert("RGB")
    else:
        img = Image.open(src).convert("RGB")
    if img.width * img.height > max_pixels:
        scale = (max_pixels / (img.width * img.height)) ** 0.5
        img = img.resize((int(img.width * scale), int(img.height * scale)), Image.LANCZOS)
    return img


def encode(processor: Any, ex: dict[str, Any], set_dir: Path, max_pixels: int) -> dict[str, Any]:
    """Token ids, pixel inputs and labels (-100 everywhere but the assistant's answer)."""
    system, user, answer = ex["messages"]
    content: list[dict[str, Any]] = [
        {"type": "image", "image": load_page(set_dir, n, max_pixels)} for n in ex["images"]
    ]
    content.append({"type": "text", "text": user["content"]})
    prompt = [system, {"role": "user", "content": content}]
    kw = {"tokenize": True, "return_dict": True, "return_tensors": "pt"}
    head = processor.apply_chat_template(prompt, add_generation_prompt=True, **kw)
    full = processor.apply_chat_template([*prompt, answer], **kw)
    labels = full["input_ids"].clone()
    labels[:, : head["input_ids"].shape[1]] = -100
    full["labels"] = labels
    return full


def train(args: argparse.Namespace) -> None:
    import psutil
    import torch
    from peft import LoraConfig, get_peft_model
    from transformers import AutoProcessor, Qwen3VLForConditionalGeneration

    from finetune.stages import PeakRss, write_stage

    device, dtype = pick_device()
    start = time.perf_counter()
    status, error, losses, step_s = "ok", None, [], []
    peak_device = 0.0
    with PeakRss() as rss:
        try:
            processor = AutoProcessor.from_pretrained(args.model)
            model = Qwen3VLForConditionalGeneration.from_pretrained(args.model, dtype=dtype)
            model.to(device)
            model.gradient_checkpointing_enable()
            model.enable_input_require_grads()
            cfg = LoraConfig(
                r=args.rank,
                lora_alpha=2 * args.rank,
                lora_dropout=0.05,
                target_modules=TARGETS,
                task_type="CAUSAL_LM",
            )
            model = get_peft_model(model, cfg)
            params = [p for p in model.parameters() if p.requires_grad]
            opt = torch.optim.AdamW(params, lr=args.lr)
            scaler = torch.amp.GradScaler("cuda") if dtype == torch.float16 else None
            rows = [json.loads(ln) for ln in (args.data / "train.jsonl").read_text().splitlines()]
            random.Random(args.seed).shuffle(rows)
            model.train()
            for step in range(args.steps):
                if time.perf_counter() - start > args.max_seconds:
                    raise TimeoutError(f"stopped at the {args.max_seconds:.0f} s cap")
                t0 = time.perf_counter()
                batch = encode(processor, rows[step % len(rows)], args.set, args.max_pixels)
                batch = {k: v.to(device) for k, v in batch.items()}
                with torch.autocast(device, dtype=dtype, enabled=device == "cuda"):
                    loss = model(**batch).loss
                (scaler.scale(loss) if scaler else loss).backward()
                if scaler:
                    scaler.step(opt)
                    scaler.update()
                else:
                    opt.step()
                opt.zero_grad(set_to_none=True)
                losses.append(round(float(loss), 4))
                if device == "mps":
                    torch.mps.synchronize()
                    peak_device = max(peak_device, torch.mps.driver_allocated_memory() / 2**20)
                elif device == "cuda":
                    peak_device = max(peak_device, torch.cuda.max_memory_allocated() / 2**20)
                step_s.append(round(time.perf_counter() - t0, 2))
                print(f"step {step + 1}/{args.steps} loss {losses[-1]} {step_s[-1]} s", flush=True)
            model.save_pretrained(assert_safe_path(args.out))
        except Exception as exc:  # the spike records the failure instead of crashing
            status, error = "failed", f"{type(exc).__name__}: {str(exc)[:1200]}"
    write_stage(
        args.stage,
        {
            "status": status,
            "error": error,
            "seconds": round(time.perf_counter() - start, 1),
            "max_pixels": args.max_pixels,
            "lora_rank": args.rank,
            "steps_requested": args.steps,
            "device": device,
            "dtype": str(dtype),
            "steps_done": len(losses),
            "loss_first": losses[0] if losses else None,
            "loss_last": losses[-1] if losses else None,
            "step_seconds": step_s,
            "peak_rss_mib": round(rss.peak_mib, 1),
            "peak_device_mib": round(peak_device, 1) if peak_device else None,
            "memory_note": "peak_rss_mib: resident memory of this process, psutil every 0.25 s. "
            "peak_device_mib: highest torch.mps.driver_allocated_memory() (or CUDA max allocated) "
            f"read after each step; machine RAM is {psutil.virtual_memory().total / 2**30:.0f} GiB",
        },
    )
    if status == "failed":
        raise SystemExit(error)


def merge(args: argparse.Namespace) -> None:
    import torch
    from peft import PeftModel
    from transformers import AutoProcessor, Qwen3VLForConditionalGeneration

    from finetune.stages import PeakRss, write_stage

    start = time.perf_counter()
    status, error = "ok", None
    with PeakRss() as rss:
        try:
            # Merge on the CPU in bf16: nothing here needs a GPU and it keeps training memory free.
            base = Qwen3VLForConditionalGeneration.from_pretrained(args.model, dtype=torch.bfloat16)
            merged = PeftModel.from_pretrained(base, args.adapter).merge_and_unload()
            out = assert_safe_path(args.out)
            merged.save_pretrained(out)
            AutoProcessor.from_pretrained(args.model).save_pretrained(out)
        except Exception as exc:
            status, error = "failed", f"{type(exc).__name__}: {str(exc)[:1200]}"
    write_stage(
        "merge",
        {
            "status": status,
            "error": error,
            "seconds": round(time.perf_counter() - start, 1),
            "peak_rss_mib": round(rss.peak_mib, 1),
            "memory_note": "peak resident memory of this process, psutil every 0.25 s",
        },
    )
    if status == "failed":
        raise SystemExit(error)


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("train")
    t.add_argument("--model", type=Path, required=True)
    t.add_argument("--data", type=Path, default=Path("finetune/data"))
    t.add_argument("--set", type=Path, default=Path("evals/datasets/spike-v0"))
    t.add_argument("--out", type=Path, default=Path("finetune/out/adapter"))
    t.add_argument("--steps", type=int, default=20)
    t.add_argument("--rank", type=int, default=8)
    t.add_argument("--lr", type=float, default=2e-4)
    t.add_argument("--max-pixels", type=int, default=786_432)
    t.add_argument("--seed", type=int, default=7)
    t.add_argument("--max-seconds", type=float, default=1800, help="stop and record after this")
    t.add_argument("--stage", default="train", help="name of the stage record to write")
    m = sub.add_parser("merge")
    m.add_argument("--model", type=Path, required=True)
    m.add_argument("--adapter", type=Path, default=Path("finetune/out/adapter"))
    m.add_argument("--out", type=Path, default=Path("finetune/out/merged"))
    args = ap.parse_args()
    for name in ("model", "data", "set", "adapter"):
        if hasattr(args, name):
            setattr(args, name, assert_safe_path(getattr(args, name)))
    train(args) if args.cmd == "train" else merge(args)


if __name__ == "__main__":
    main()
