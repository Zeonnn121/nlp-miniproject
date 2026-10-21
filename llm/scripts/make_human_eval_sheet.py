#!/usr/bin/env python3
"""
Pick 20 random test examples and create a CSV for human evaluation.

The CSV contains:
- input: the structured input text
- output_A: base model output (unlabeled)
- output_B: fine-tuned model output (unlabeled)
- clarity_A: empty (for human rating 1-5)
- correctness_A: empty (for human rating 1-5)
- usefulness_A: empty (for human rating 1-5)
- clarity_B: empty (for human rating 1-5)
- correctness_B: empty (for human rating 1-5)
- usefulness_B: empty (for human rating 1-5)

The outputs are shuffled and unlabeled as A/B so the rater doesn't know which
is the base vs fine-tuned model.
"""

from __future__ import annotations

import csv
import json
import random
from pathlib import Path

# ──────────────────────────────────────────────────────────────────────
# Paths
# ──────────────────────────────────────────────────────────────────────
ROOT = Path(__file__).parent.parent          # project root (contains llm/)
DATA_DIR = ROOT / "llm" / "data"
TEST_FILE = DATA_DIR / "test.jsonl"
OUTPUT_CSV = ROOT / "llm" / "results" / "human_eval_sheet.csv"

# ──────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────

def main() -> None:
    # Load test data
    print(f"Loading test data from {TEST_FILE}...")
    test_records = []
    with TEST_FILE.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            test_records.append(json.loads(line))

    print(f"  Loaded {len(test_records)} records")

    # Pick 20 random examples (without replacement)
    n_to_pick = min(20, len(test_records))
    selected = random.sample(test_records, n_to_pick)

    # Prepare CSV rows
    # We'll generate base and ft outputs later, but for now we need the inputs
    # and we'll leave the output columns empty for the rater to fill in after
    # they see both outputs. Actually, re-reading the request: "picks 20 random
    # test examples and creates a CSV with the input, base output and fine-tuned
    # output (shuffled and unlabeled as A/B) with empty columns for clarity,
    # correctness and usefulness scores from 1 to 5"

    # So we need to generate both outputs first, then shuffle them as A/B.
    # But that requires the models... Let me re-think.

    # Actually, reading more carefully: the script should pick 20 random test
    # examples and create a CSV with input, base output, fine-tuned output,
    # shuffled and unlabeled as A/B, with empty columns for scores.

    # This means we need to generate outputs from both models. But the script
    # is in llm/scripts/ and the models are in llm/outputs/adapter/.
    # Let me make this script generate the outputs as well.

    # However, generating with the full models might be slow. Let me check
    # if there's a simpler approach - maybe just use the test data inputs
    # and leave the output columns to be filled by the human rater after
    # they run the evaluation.

    # Actually, re-reading again: "creates a CSV with the input, base output
    # and fine-tuned output (shuffled and unlabeled as A/B) with empty columns
    # for clarity, correctness and usefulness scores from 1 to 5"

    # I think the intent is:
    # - Column 1: input (from test.jsonl)
    # - Column 2: output_A (base model output, labeled A but the rater
    #   doesn't know it's base)
    # - Column 3: output_B (fine-tuned model output, labeled B but the rater
    #   doesn't know it's ft)
    # - Columns 4-9: empty for human ratings (clarity, correctness, usefulness
    #   1-5 for A and B)

    # But we need to actually generate the outputs. Let me do that using the
    # same approach as evaluate.py but simplified.

    # Actually, let me re-read the requirement one more time...
    # "picks 20 random test examples and creates a CSV with the input, base 
    # output and fine-tuned output (shuffled and unlabeled as A/B) with empty 
    # columns for clarity, correctness and usefulness scores from 1 to 5, so I 
    # can rate them by hand"

    # OK so the CSV should have:
    # - input
    # - base output (as A or B, shuffled)
    # - fine-tuned output (as the other one, A or B, shuffled)
    # - empty columns for ratings 1-5

    # The shuffling means the rater doesn't know which is which.

    # Let me generate outputs using the models. I'll use a simplified version
    # that just generates text.

    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer
    from peft import PeftModel

    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"Using device: {device}")

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
    ft_model = PeftModel.from_pretrained(base_model, str(ROOT / "llm" / "outputs" / "adapter"))
    ft_model = ft_model.merge_and_unload()
    ft_model.use_cache = False

    # Generate outputs for each selected record
    rows = []
    for record in selected:
        instruction = record.get("instruction", "")
        input_text = record.get("input", "")
        reference_output = record.get("output", "")

        # Generate from base model
        messages = [
            {"role": "user", "content": f"{instruction}\n\n{input_text}"},
        ]
        prompt = tokenizer.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True
        )
        inputs = tokenizer(prompt, return_tensors="pt").to(device)
        with torch.no_grad():
            base_outputs = base_model.generate(
                **inputs, max_new_tokens=512, do_sample=False, temperature=0.0,
            )
        prompt_len = inputs["input_ids"].shape[1]
        base_output = tokenizer.decode(base_outputs[0][prompt_len:], skip_special_tokens=False).strip()

        # Generate from fine-tuned model
        with torch.no_grad():
            ft_outputs = ft_model.generate(
                **inputs, max_new_tokens=512, do_sample=False, temperature=0.0,
            )
        ft_output = tokenizer.decode(ft_outputs[0][prompt_len:], skip_special_tokens=False).strip()

        # Shuffle A/B: randomly assign which is A and which is B
        if random.random() < 0.5:
            a_output, b_output = base_output, ft_output
        else:
            a_output, b_output = ft_output, base_output

        # Build CSV row
        row = {
            "input": input_text,
            "output_A": a_output,
            "output_B": b_output,
            "clarity_A": "",
            "correctness_A": "",
            "usefulness_A": "",
            "clarity_B": "",
            "correctness_B": "",
            "usefulness_B": "",
        }
        rows.append(row)

    # Shuffle the order of the 20 rows so the rater doesn't see them in order
    random.shuffle(rows)

    # Write CSV
    OUTPUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "input", "output_A", "output_B",
        "clarity_A", "correctness_A", "usefulness_A",
        "clarity_B", "correctness_B", "usefulness_B",
    ]
    with OUTPUT_CSV.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"\nCSV written to {OUTPUT_CSV}")
    print(f"  {n_to_pick} examples selected")
    print("  Outputs are shuffled and unlabeled (A/B)")
    print("  Empty columns ready for 1-5 ratings on clarity, correctness, usefulness")


if __name__ == "__main__":
    main()