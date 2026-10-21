"""QLoRA fine-tuning for the network-fault LLM explainer.

Pipeline overview
-----------------
1. Load base model in 4-bit NF4 quantisation (BitsAndBytes).
2. Wrap it with a LoRA adapter via PEFT (targets every linear layer).
3. Format each {instruction, input, output} example into the model's own
   chat template so the model learns the correct prompt/response boundary.
4. Train with TRL's SFTTrainer (Supervised Fine-Tuning Trainer), which
   handles masking loss on the prompt tokens so we only learn on the answer.
5. Log train + val loss to the console and save a loss-curve PNG.
6. Save the LoRA adapter weights (NOT the full model — they're tiny).

Usage
-----
  python llm/train_lora.py                # uses defaults below
  BASE_MODEL=Qwen/Qwen2.5-0.5B-Instruct python llm/train_lora.py

Directory layout produced
--------------------------
  llm/outputs/adapter/   — LoRA adapter (load with PeftModel.from_pretrained)
  llm/results/loss_curve.png
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import matplotlib.pyplot as plt
import torch
from datasets import Dataset
from peft import LoraConfig, TaskType, get_peft_model
from transformers import (
    AutoModelForCausalLM,
    AutoTokenizer,
    BitsAndBytesConfig,
    TrainerCallback,
    TrainingArguments,
)
from trl import SFTConfig, SFTTrainer

# ---------------------------------------------------------------------------
# ── Configuration ──────────────────────────────────────────────────────────
# All tuneable knobs are at the top so they're easy to find during a defence.
# ---------------------------------------------------------------------------

# Base model — any chat-finetuned causal LM that fits in 16 GB VRAM works.
# Qwen2.5-1.5B-Instruct is a good default: small enough for a free Colab T4,
# capable enough to learn structured fault explanations.
BASE_MODEL: str = os.getenv("BASE_MODEL", "Qwen/Qwen2.5-1.5B-Instruct")

# Whether to load the model in 4-bit NF4 (QLoRA).  Set False for CPU testing.
QUANTIZE: bool = True

# LoRA hyper-parameters
LORA_R: int          = 16    # rank — controls adapter expressiveness vs size
LORA_ALPHA: int      = 32    # scaling factor; alpha/r = 2 is a common default
LORA_DROPOUT: float  = 0.05  # light regularisation on the adapter weights

# Training hyper-parameters tuned for a T4 (16 GB VRAM)
NUM_EPOCHS: int      = 3
LEARNING_RATE: float = 2e-4
BATCH_SIZE: int      = 2     # per-device micro-batch; keep small for T4
GRAD_ACCUM: int      = 8     # effective batch = BATCH_SIZE × GRAD_ACCUM = 16
MAX_SEQ_LEN: int     = 512   # truncate longer examples to save memory
WARMUP_RATIO: float  = 0.05  # fraction of total steps used for LR warm-up

# Paths — derived from this file's location so the script works from any cwd
_HERE    = Path(__file__).parent          # llm/
DATA_DIR = _HERE / "data"
OUT_DIR  = _HERE / "outputs" / "adapter"
RES_DIR  = _HERE / "results"

TRAIN_FILE = DATA_DIR / "train.jsonl"
VAL_FILE   = DATA_DIR / "val.jsonl"


# ---------------------------------------------------------------------------
# ── 1.  Load and format dataset ────────────────────────────────────────────
# ---------------------------------------------------------------------------

def load_jsonl(path: Path) -> list[dict]:
    """Read a JSONL file into a list of dicts."""
    with path.open(encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def format_example(example: dict, tokenizer: AutoTokenizer) -> dict:
    """Convert one {instruction, input, output} dict into a chat-formatted string.

    We use the model's own chat template (apply_chat_template) so the model
    sees the same [INST] / <|im_start|> markers it was pre-trained with.
    Mixing instruction + input into the 'user' turn is standard practice.
    """
    user_content = f"{example['instruction']}\n\n{example['input']}"
    messages = [
        {"role": "user",      "content": user_content},
        {"role": "assistant", "content": example["output"]},
    ]
    # tokenize=False → we get back the raw string; SFTTrainer tokenises later
    text = tokenizer.apply_chat_template(
        messages, tokenize=False, add_generation_prompt=False
    )
    return {"text": text}


def build_hf_dataset(path: Path, tokenizer: AutoTokenizer) -> Dataset:
    """Load a JSONL split and return a Hugging Face Dataset of formatted strings."""
    rows = load_jsonl(path)
    formatted = [format_example(r, tokenizer) for r in rows]
    return Dataset.from_list(formatted)


# ---------------------------------------------------------------------------
# ── 2.  Quantisation config (BitsAndBytes 4-bit NF4) ──────────────────────
# ---------------------------------------------------------------------------

def make_bnb_config() -> BitsAndBytesConfig:
    """4-bit NF4 quantisation — the 'Q' in QLoRA.

    NF4 (Normal Float 4) is a data type introduced by the QLoRA paper that
    minimises quantisation error for normally distributed weights.
    double_quant further quantises the quantisation constants themselves,
    saving ~0.4 bits per parameter at negligible accuracy cost.
    """
    return BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",       # NF4: best quality for normal weights
        bnb_4bit_use_double_quant=True,  # compress the quant constants too
        bnb_4bit_compute_dtype=torch.bfloat16,  # actual computation in bf16
    )


# ---------------------------------------------------------------------------
# ── 3.  LoRA adapter config ────────────────────────────────────────────────
# ---------------------------------------------------------------------------

def make_lora_config() -> LoraConfig:
    """LoRA (Low-Rank Adaptation) config.

    Instead of updating all weights (billions of params), LoRA injects two
    small trainable matrices A (d×r) and B (r×d) beside each target layer.
    Only A and B are trained; the original weights are frozen.

    target_modules="all-linear" applies LoRA to every nn.Linear in the model
    (q_proj, k_proj, v_proj, o_proj, gate_proj, up_proj, down_proj for Qwen).
    This is more thorough than the traditional {q,v}-only approach and usually
    gives better results at the same rank.
    """
    return LoraConfig(
        task_type=TaskType.CAUSAL_LM,
        r=LORA_R,
        lora_alpha=LORA_ALPHA,
        lora_dropout=LORA_DROPOUT,
        target_modules="all-linear",  # target every linear layer
        bias="none",                  # don't adapt bias terms (saves memory)
    )


# ---------------------------------------------------------------------------
# ── 4.  Callback: collect per-epoch validation loss ────────────────────────
# ---------------------------------------------------------------------------

class LossLogger(TrainerCallback):
    """Harvest train_loss and eval_loss from the trainer log and store them.

    The Trainer calls on_log() after each logging step.  We accumulate all
    logged values and extract per-epoch averages in get_epoch_losses() once
    training is done.
    """

    def __init__(self):
        self.logs: list[dict] = []   # raw log dicts from the trainer

    def on_log(self, args, state, control, logs=None, **kwargs):
        if logs:
            self.logs.append(dict(logs))

    def get_epoch_losses(self) -> tuple[list[float], list[float]]:
        """Return (train_losses, val_losses) averaged per epoch.

        The trainer logs at every `logging_steps` step plus at each eval.
        We bucket by epoch, average within each bucket, and return one value
        per epoch for the plot.
        """
        # Collect all entries that have a loss value
        train_entries: dict[int, list[float]] = {}  # epoch → [loss, ...]
        eval_entries:  dict[int, list[float]] = {}

        for log in self.logs:
            epoch = int(log.get("epoch", 0))
            if "loss" in log:
                train_entries.setdefault(epoch, []).append(log["loss"])
            if "eval_loss" in log:
                eval_entries.setdefault(epoch, []).append(log["eval_loss"])

        epochs = sorted(set(list(train_entries) + list(eval_entries)))
        train_losses = [
            sum(train_entries[e]) / len(train_entries[e])
            for e in epochs if e in train_entries
        ]
        val_losses = [
            sum(eval_entries[e]) / len(eval_entries[e])
            for e in epochs if e in eval_entries
        ]
        return train_losses, val_losses


# ---------------------------------------------------------------------------
# ── 5.  Loss-curve plot ────────────────────────────────────────────────────
# ---------------------------------------------------------------------------

def save_loss_curve(
    train_losses: list[float],
    val_losses:   list[float],
    out_path:     Path,
) -> None:
    """Plot training and validation loss per epoch and save to disk."""
    RES_DIR.mkdir(parents=True, exist_ok=True)

    epochs = list(range(1, max(len(train_losses), len(val_losses)) + 1))

    fig, ax = plt.subplots(figsize=(7, 4))
    if train_losses:
        ax.plot(epochs[:len(train_losses)], train_losses,
                marker="o", label="Train loss",  color="#2563eb")
    if val_losses:
        ax.plot(epochs[:len(val_losses)],   val_losses,
                marker="s", label="Val loss",    color="#dc2626", linestyle="--")

    ax.set_xlabel("Epoch")
    ax.set_ylabel("Cross-entropy loss")
    ax.set_title(f"QLoRA fine-tuning — {Path(BASE_MODEL).name}")
    ax.legend()
    ax.grid(True, linestyle=":", alpha=0.5)
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
    print(f"Loss curve saved to {out_path}")


# ---------------------------------------------------------------------------
# ── 6.  Main training loop ─────────────────────────────────────────────────
# ---------------------------------------------------------------------------

def main() -> None:
    print(f"Base model : {BASE_MODEL}")
    print(f"Quantised  : {QUANTIZE}")
    print(f"LoRA r={LORA_R}, alpha={LORA_ALPHA}")
    print(f"Epochs={NUM_EPOCHS}, LR={LEARNING_RATE}, batch={BATCH_SIZE}×{GRAD_ACCUM}")

    # ── 6a. Tokeniser ───────────────────────────────────────────────────────
    # trust_remote_code is required for Qwen2.5's custom tokeniser files.
    tokenizer = AutoTokenizer.from_pretrained(
        BASE_MODEL, trust_remote_code=True
    )
    # Many causal LMs don't set a pad token by default; eos works fine for SFT.
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
    tokenizer.padding_side = "right"  # pad on the right for causal LM training

    # ── 6b. Datasets ────────────────────────────────────────────────────────
    print("Loading datasets …")
    train_ds = build_hf_dataset(TRAIN_FILE, tokenizer)
    val_ds   = build_hf_dataset(VAL_FILE,   tokenizer)
    print(f"  train={len(train_ds)}, val={len(val_ds)}")

    # ── 6c. Model (4-bit) ───────────────────────────────────────────────────
    print("Loading base model …")
    model = AutoModelForCausalLM.from_pretrained(
        BASE_MODEL,
        quantization_config=make_bnb_config() if QUANTIZE else None,
        device_map="auto",       # spread across all available GPUs / CPU
        trust_remote_code=True,
        torch_dtype=torch.bfloat16 if not QUANTIZE else None,
    )
    # Disable caching during training — it's incompatible with gradient checkpointing
    model.config.use_cache = False

    # ── 6d. Apply LoRA ──────────────────────────────────────────────────────
    # prepare_model_for_kbit_training casts layer norms to float32 (stable
    # training) and enables gradient checkpointing *before* PEFT wrapping.
    # It's only needed when the model is quantised.
    if QUANTIZE:
        from peft import prepare_model_for_kbit_training
        model = prepare_model_for_kbit_training(model)

    model = get_peft_model(model, make_lora_config())
    model.print_trainable_parameters()  # shows how few params we're training

    # ── 6e. Training arguments ──────────────────────────────────────────────
    # SFTConfig extends TrainingArguments with SFT-specific knobs.
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    training_args = SFTConfig(
        output_dir=str(OUT_DIR),

        # Training schedule
        num_train_epochs=NUM_EPOCHS,
        per_device_train_batch_size=BATCH_SIZE,
        per_device_eval_batch_size=BATCH_SIZE,
        gradient_accumulation_steps=GRAD_ACCUM,
        learning_rate=LEARNING_RATE,
        warmup_ratio=WARMUP_RATIO,
        lr_scheduler_type="cosine",   # decay LR on a cosine curve after warmup

        # Memory optimisations for T4
        gradient_checkpointing=True,  # trade compute for memory (recompute fwd pass)
        fp16=False,                   # bfloat16 is safer on modern GPUs
        bf16=torch.cuda.is_available() and torch.cuda.is_bf16_supported(),

        # Evaluation
        eval_strategy="epoch",        # evaluate after each epoch
        save_strategy="epoch",        # save checkpoint after each epoch
        load_best_model_at_end=True,  # keep the checkpoint with lowest val loss
        metric_for_best_model="eval_loss",
        greater_is_better=False,

        # Logging
        logging_steps=10,             # log every 10 optimiser steps
        report_to="none",             # no wandb / tensorboard by default

        # SFT-specific: truncate to MAX_SEQ_LEN and pack nothing
        max_seq_length=MAX_SEQ_LEN,
        dataset_text_field="text",    # column produced by build_hf_dataset
        packing=False,                # no sequence packing — keeps examples separate
    )

    # ── 6f. Loss logger callback ────────────────────────────────────────────
    loss_logger = LossLogger()

    # ── 6g. SFTTrainer ──────────────────────────────────────────────────────
    # SFTTrainer wraps the Hugging Face Trainer with automatic prompt masking:
    # tokens belonging to the prompt (user turn) are set to -100 so they don't
    # contribute to the cross-entropy loss.  We learn only the assistant turn.
    trainer = SFTTrainer(
        model=model,
        args=training_args,
        train_dataset=train_ds,
        eval_dataset=val_ds,
        tokenizer=tokenizer,
        callbacks=[loss_logger],
    )

    # ── 6h. Train ──────────────────────────────────────────────────────────
    print("\nStarting training …")
    trainer.train()
    print("Training complete.")

    # ── 6i. Save the LoRA adapter ──────────────────────────────────────────
    # We save ONLY the adapter (a few MB), not the full 1.5B-param model.
    # To do inference: load the base model, then call PeftModel.from_pretrained
    # with the adapter path, or merge_and_unload() to bake the adapters in.
    trainer.model.save_pretrained(str(OUT_DIR))
    tokenizer.save_pretrained(str(OUT_DIR))
    print(f"LoRA adapter saved to {OUT_DIR}")

    # ── 6j. Plot loss curve ────────────────────────────────────────────────
    train_losses, val_losses = loss_logger.get_epoch_losses()
    print(f"Train losses per epoch : {[round(l, 4) for l in train_losses]}")
    print(f"Val   losses per epoch : {[round(l, 4) for l in val_losses]}")
    save_loss_curve(train_losses, val_losses, RES_DIR / "loss_curve.png")


if __name__ == "__main__":
    main()
