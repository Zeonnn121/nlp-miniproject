#!/usr/bin/env python3
"""
Evaluate base model vs fine-tuned (base + LoRA adapter) on llm/data/test.jsonl.

Computes ROUGE-1, ROUGE-2, ROUGE-L and BLEU, plus a structure check
(does the output contain Explanation, Likely causes and Recommended actions).

Saves generations from both models to llm/results/generations.jsonl,
and writes a metrics comparison table to llm/results/metrics.md and metrics.json.
"""

from __future__ import annotations

import json
import os
import re
from collections import defaultdict
from pathlib import Path

import torch
from datasets import Dataset, load_from_disk
from peft import PeftModel, PeftConfig
from rouge_score import rouge_scorer
from sacrebleu import sentence_bleu
from transformers import AutoModelForCausalLM, AutoTokenizer

# ──────────────────────────────────────────────────────────────────────
# Paths
# ──────────────────────────────────────────────────────────────────────
ROOT = Path(__file__).parent          # llm/
DATA_DIR = ROOT / "data"
RES_DIR = ROOT / "results"
ADAPTER_DIR = ROOT / "outputs" / "adapter"

TEST_FILE = DATA_DIR / "test.jsonl"
GENERATIONS_FILE = RES_DIR / "generations.jsonl"
METRICS_MD = RES_DIR / "metrics.md"
METRICS_JSON = RES_DIR / "metrics.json"

# ──────────────────────────────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────────────────────────────
REQUIRED_SECTIONS = ["Explanation:", "Likely causes:", "Recommended actions:"]


# ──────────────────────────────────────────────────────────────────────
# Utility functions
# ──────────────────────────────────────────────────────────────────────

def load_test_data(path: Path) -> list[dict]:
    """Load the JSONL test set."""
    records = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            records.append(json.loads(line))
    return records


def check_structure(output: str) -> dict:
    """
    Check if the output contains the three required sections.
    Returns a dict with per-section presence and overall pass/fail.
    """
    presence = {}
    for section in REQUIRED_SECTIONS:
        presence[section] = section in output
    all_present = all(presence.values())
    return {
        "pass": all_present,
        "details": presence,
    }


def extract_sections(output: str) -> dict:
    """Extract the three labeled sections from the output."""
    sections = {}
    # Match "Explanation:\n...Likely causes:\n...Recommended actions:"
    # The section content goes until the next section header or end of string
    current_section = None
    current_text = []

    for line in output.splitlines():
        stripped = line.strip()
        # Check if this line is a section header
        for sec in REQUIRED_SECTIONS:
            if stripped.startswith(sec):
                # Save previous section
                if current_section is not None:
                    sections[current_section] = "\n".join(current_text).strip()
                current_section = stripped.split(":")[0]  # e.g. "Explanation"
                current_text = []
                # Check if there's content on the same line after the colon
                after_colon = stripped[len(sec) + 1:].strip()
                if after_colon:
                    current_text.append(after_colon)
                break
        else:
            # Not a header line
            if current_section is not None:
                current_text.append(stripped)

    # Save last section
    if current_section is not None:
        sections[current_section] = "\n".join(current_text).strip()

    return sections


def compute_rouge(reference: str, candidate: str) -> dict:
    """Compute ROUGE-1, ROUGE-2, ROUGE-L scores using rouge-score."""
    scorer = rouge_scorer.RougeScorer(
        ["rouge1", "rouge2", "rougeL"], use_stemmer=True
    )
    scores = scorer.score(reference, candidate)
    return {
        "rouge1": scores["rouge1"].fmeasure,
        "rouge2": scores["rouge2"].fmeasure,
        "rougeL": scores["rougeL"].fmeasure,
    }


def compute_bleu(reference: str, candidate: str) -> float:
    """Compute BLEU score using sacrebleu."""
    # sacrebleu expects a list of references (even for single reference)
    bleu_score = sentence_bleu(
        candidate,
        [reference.split()],
        smooth_method="exp",
    )
    return bleu_score.score


def generate_text(
    model: torch.nn.Module,
    tokenizer: AutoTokenizer,
    instruction: str,
    input_text: str,
    max_new_tokens: int = 512,
    device: str = "cpu",
) -> str:
    """
    Generate text using the model with the standard chat template.
    Format: user instruction + input, then assistant generates the output.
    """
    # Build the chat format matching the training format
    messages = [
        {"role": "user", "content": f"{instruction}\n\n{input_text}"},
    ]

    # Apply chat template
    prompt = tokenizer.apply_chat_template(
        messages, tokenize=False, add_generation_prompt=True
    )

    # Tokenize
    inputs = tokenizer(
        prompt,
        return_tensors="pt",
    ).to(device)

    # Generate
    with torch.no_grad():
        outputs = model.generate(
            **inputs,
            max_new_tokens=max_new_tokens,
            do_sample=False,
            temperature=0.0,
            pad_token_id=tokenizer.eos_token_id,
        )

    # Decode only the newly generated tokens
    prompt_len = inputs["input_ids"].shape[1]
    generated_ids = outputs[0][prompt_len:]
    generated_text = tokenizer.decode(generated_ids, skip_special_tokens=False)

    # Clean up any remaining prompt artifacts
    # Remove the <|channel|> assistant markers if present
    generated_text = re.sub(r"<\|channel\|>.*?", "", generated_text, flags=re.DOTALL)
    # Remove any trailing prompt leftovers
    generated_text = generated_text.strip()

    return generated_text


def load_base_model():
    """Load the base Qwen2.5-1.5B-Instruct model."""
    model_name = "Qwen/Qwen2.5-1.5B-Instruct"
    tokenizer = AutoTokenizer.from_pretrained(
        model_name, trust_remote_code=True
    )
    model = AutoModelForCausalLM.from_pretrained(
        model_name,
        trust_remote_code=True,
        torch_dtype=torch.bfloat16,
        device_map="auto",
    )
    model.use_cache = False
    return model, tokenizer


def load_finetuned_model():
    """Load the base model with LoRA adapter fused."""
    model_name = "Qwen/Qwen2.5-1.5B-Instruct"
    tokenizer = AutoTokenizer.from_pretrained(
        model_name, trust_remote_code=True
    )
    base_model = AutoModelForCausalLM.from_pretrained(
        model_name,
        trust_remote_code=True,
        torch_dtype=torch.bfloat16,
        device_map="auto",
    )
    base_model.use_cache = False
    # Load LoRA adapter on top of base model
    from peft import PeftModel
    model = PeftModel.from_pretrained(base_model, str(ADAPTER_DIR))
    # Merge adapter weights into base model for generation
    model = model.merge_and_unload()
    model.use_cache = False
    return model, tokenizer


# ──────────────────────────────────────────────────────────────────────
# Main evaluation
# ──────────────────────────────────────────────────────────────────────

def main() -> None:
    # Ensure output directory exists
    RES_DIR.mkdir(parents=True, exist_ok=True)

    # Load test data
    print(f"Loading test data from {TEST_FILE}...")
    test_records = load_test_data(TEST_FILE)
    print(f"  Loaded {len(test_records)} records")

    # Load models
    print("Loading base model...")
    base_model, base_tokenizer = load_base_model()

    print("Loading fine-tuned model (base + LoRA)...")
    ft_model, ft_tokenizer = load_finetuned_model()

    # Ensure tokenizers match
    assert base_tokenizer.eos_token_id == ft_tokenizer.eos_token_id

    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"Using device: {device}")

    # Move models to device
    base_model.to(device)
    ft_model.to(device)

    # ────────────────────────────────────────────────────────────────────
    # Generate for each test example
    # ────────────────────────────────────────────────────────────────────
    generations = []  # list of dicts: {input, reference, base_output, ft_output, structure_check}

    rouge_scorer_local = rouge_scorer.RougeScorer(
        ["rouge1", "rouge2", "rougeL"], use_stemmer=True
    )

    rouge_scores_base = {"rouge1": 0.0, "rouge2": 0.0, "rougeL": 0.0}
    rouge_scores_ft = {"rouge1": 0.0, "rouge2": 0.0, "rougeL": 0.0}
    bleu_scores_base = 0.0
    bleu_scores_ft = 0.0
    structure_pass_base = 0
    structure_pass_ft = 0

    for i, record in enumerate(test_records):
        instruction = record.get("instruction", "")
        input_text = record.get("input", "")
        reference_output = record.get("output", "")

        # Generate from base model
        print(f"  [{i+1}/{len(test_records)}] Generating base model output...")
        base_output = generate_text(
            base_model, base_tokenizer, instruction, input_text,
            max_new_tokens=512, device=device,
        )

        # Generate from fine-tuned model
        print(f"  [{i+1}/{len(test_records)}] Generating fine-tuned model output...")
        ft_output = generate_text(
            ft_model, ft_tokenizer, instruction, input_text,
            max_new_tokens=512, device=device,
        )

        # Check structure
        base_structure = check_structure(base_output)
        ft_structure = check_structure(ft_output)

        if base_structure["pass"]:
            structure_pass_base += 1
        if ft_structure["pass"]:
            structure_pass_ft += 1

        # Compute ROUGE against reference
        rouge_base = compute_rouge(reference_output, base_output)
        rouge_ft = compute_rouge(reference_output, ft_output)

        # Compute BLEU against reference
        bleu_base = compute_bleu(reference_output, base_output)
        bleu_ft = compute_bleu(reference_output, ft_output)

        # Accumulate
        for key in rouge_scores_base:
            rouge_scores_base[key] += rouge_base[key]
            rouge_scores_ft[key] += rouge_ft[key]
        bleu_scores_base += bleu_base
        bleu_scores_ft += bleu_ft

        # Save generation record
        gen_entry = {
            "input": input_text,
            "reference_output": reference_output,
            "base_output": base_output,
            "ft_output": ft_output,
            "structure_base": base_structure["details"],
            "structure_ft": ft_structure["details"],
            "rouge1_base": rouge_base["rouge1"],
            "rouge2_base": rouge_base["rouge2"],
            "rougeL_base": rouge_base["rougeL"],
            "rouge1_ft": rouge_ft["rouge1"],
            "rouge2_ft": rouge_ft["rouge2"],
            "rougeL_ft": rouge_ft["rougeL"],
            "bleu_base": bleu_base,
            "bleu_ft": bleu_ft,
        }
        generations.append(gen_entry)

    # Average metrics over all records
    n = len(test_records)
    for key in rouge_scores_base:
        rouge_scores_base[key] /= n
        rouge_scores_ft[key] /= n
    bleu_scores_base /= n
    bleu_scores_ft /= n

    print("\n" + "=" * 60)
    print("ROUGE Scores (averaged over all test examples)")
    print("=" * 60)
    print(f"Base model:   ROUGE-1: {rouge_scores_base['rouge1']:.4f}, ROUGE-2: {rouge_scores_base['rouge2']:.4f}, ROUGE-L: {rouge_scores_base['rougeL']:.4f}")
    print(f"FT model:     ROUGE-1: {rouge_scores_ft['rouge1']:.4f}, ROUGE-2: {rouge_scores_ft['rouge2']:.4f}, ROUGE-L: {rouge_scores_ft['rougeL']:.4f}")
    print()
    print("BLEU Scores (averaged over all test examples)")
    print(f"Base model:   BLEU = {bleu_scores_base:.2f}")
    print(f"FT model:     BLEU = {bleu_scores_ft:.2f}")
    print()
    print(f"Structure check: Base model passed on {structure_pass_base}/{n} examples ({100*structure_pass_base/n:.1f}%)")
    print(f"Structure check: FT model passed on {structure_pass_ft}/{n} examples ({100*structure_pass_ft/n:.1f}%)")

    # ────────────────────────────────────────────────────────────────────
    # Save generations to JSONL
    # ────────────────────────────────────────────────────────────────────
    print(f"\nSaving generations to {GENERATIONS_FILE}...")
    with GENERATIONS_FILE.open("w", encoding="utf-8") as f:
        for gen in generations:
            f.write(json.dumps(gen, ensure_ascii=False) + "\n")

    # ────────────────────────────────────────────────────────────────────
    # Write metrics comparison table to metrics.md
    # ────────────────────────────────────────────────────────────────────
    print(f"Writing metrics table to {METRICS_MD}...")

    # Format the metrics table
    md_lines = [
        "# Model Evaluation: Base vs Fine-Tuned\n",
        "",
        "| Metric | Base Model | Fine-Tuned Model |",
        "|--------|------------|------------------|",
        f"| ROUGE-1 | {rouge_scores_base['rouge1']:.4f} | {rouge_scores_ft['rouge1']:.4f} |",
        f"| ROUGE-2 | {rouge_scores_base['rouge2']:.4f} | {rouge_scores_ft['rouge2']:.4f} |",
        f"| ROUGE-L | {rouge_scores_base['rougeL']:.4f} | {rouge_scores_ft['rougeL']:.4f} |",
        f"| BLEU | {bleu_scores_base:.2f} | {bleu_scores_ft:.2f} |",
        f"| Structure Pass | {structure_pass_base}/{n} ({100*structure_pass_base/n:.1f}%) | {structure_pass_ft}/{n} ({100*structure_pass_ft/n:.1f}%) |",
        "",
        "*Lowercase ROUGE values are f-measure (0 to 1). BLEU is percentage (0 to 100).*\n",
    ]

    with METRICS_MD.open("w", encoding="utf-8") as f:
        f.writelines(md_lines)

    # ────────────────────────────────────────────────────────────────────
    # Write metrics.json
    # ────────────────────────────────────────────────────────────────────
    metrics_data = {
        "rouge1_base": float(f"{rouge_scores_base['rouge1']:.6f}"),
        "rouge2_base": float(f"{rouge_scores_base['rouge2']:.6f}"),
        "rougeL_base": float(f"{rouge_scores_base['rougeL']:.6f}"),
        "bleu_base": float(f"{bleu_scores_base:.4f}"),
        "rouge1_ft": float(f"{rouge_scores_ft['rouge1']:.6f}"),
        "rouge2_ft": float(f"{rouge_scores_ft['rouge2']:.6f}"),
        "rougeL_ft": float(f"{rouge_scores_ft['rougeL']:.6f}"),
        "bleu_ft": float(f"{bleu_scores_ft:.4f}"),
        "structure_pass_base_pct": float(f"{100*structure_pass_base/n:.2f}"),
        "structure_pass_ft_pct": float(f"{100*structure_pass_ft/n:.2f}"),
        "num_examples": n,
    }

    with METRICS_JSON.open("w", encoding="utf-8") as f:
        json.dump(metrics_data, f, indent=2)

    print(f"Written metrics.json:")
    print(json.dumps(metrics_data, indent=2))

    print("\n✅ Evaluation complete!")


if __name__ == "__main__":
    main()