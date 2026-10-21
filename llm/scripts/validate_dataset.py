"""
validate_dataset.py - sanity-check the instruction-tuning dataset splits.

Checks:
  * Every record has instruction, input, output (non-empty strings)
  * Output contains all three required section headers
  * No duplicate (instruction, input) pairs within a split
  * Cross-split contamination (same input in train AND val/test)
  * Split distribution by fault_type
"""
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).parent.parent
REQUIRED_HEADERS = ["Explanation:", "Likely causes:", "Recommended actions:"]

SPLITS = {
    "dataset": ROOT / "data" / "dataset.jsonl",
    "train":   ROOT / "data" / "train.jsonl",
    "val":     ROOT / "data" / "val.jsonl",
    "test":    ROOT / "data" / "test.jsonl",
}


def load(path: Path) -> list[dict]:
    if not path.exists():
        print(f"  [SKIP] {path.name} not found")
        return []
    records = []
    for i, line in enumerate(path.open(encoding="utf-8"), 1):
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError as e:
            print(f"  [ERROR] {path.name} line {i}: bad JSON — {e}")
    return records


def check_fields(records: list[dict], name: str) -> int:
    errors = 0
    for i, r in enumerate(records, 1):
        for field in ("instruction", "input", "output"):
            if not isinstance(r.get(field), str) or not r[field].strip():
                print(f"  [ERROR] {name}:{i} empty/missing field '{field}'")
                errors += 1
        if "output" in r and r["output"].strip():
            for h in REQUIRED_HEADERS:
                if h not in r["output"]:
                    print(f"  [ERROR] {name}:{i} output missing section '{h}'")
                    errors += 1
    return errors


def check_duplicates(records: list[dict], name: str) -> int:
    seen: set[str] = set()
    dupes = 0
    for i, r in enumerate(records, 1):
        key = r.get("input", "")
        if key in seen:
            print(f"  [WARN]  {name}:{i} duplicate input (device/fault already in split)")
            dupes += 1
        seen.add(key)
    return dupes


def fault_type_from_input(r: dict) -> str:
    for line in r.get("input", "").splitlines():
        if line.startswith("Fault type:"):
            return line.split(":", 1)[1].strip()
    return "UNKNOWN"


def main() -> None:
    total_errors = 0
    split_inputs: dict[str, set[str]] = {}

    for split_name, path in SPLITS.items():
        print(f"\n=== {split_name} ({path.name}) ===")
        records = load(path)
        if not records:
            continue

        print(f"  Records : {len(records)}")

        errors  = check_fields(records, split_name)
        dupes   = check_duplicates(records, split_name)
        total_errors += errors

        # fault_type distribution
        counts = Counter(fault_type_from_input(r) for r in records)
        print("  Fault-type distribution:")
        for ft, n in sorted(counts.items()):
            print(f"    {ft:<45} {n:>4}")

        split_inputs[split_name] = {r.get("input", "") for r in records}

        if errors == 0 and dupes == 0:
            print("  [OK]")

    # cross-split contamination: any train input also in val or test?
    if "train" in split_inputs and "val" in split_inputs and "test" in split_inputs:
        print("\n=== Cross-split contamination check ===")
        train_in_val  = split_inputs["train"] & split_inputs["val"]
        train_in_test = split_inputs["train"] & split_inputs["test"]
        val_in_test   = split_inputs["val"]   & split_inputs["test"]
        for label, overlap in [
            ("train+val overlap",  train_in_val),
            ("train+test overlap", train_in_test),
            ("val+test overlap",   val_in_test),
        ]:
            if overlap:
                print(f"  [ERROR] {label}: {len(overlap)} shared inputs")
                total_errors += len(overlap)
            else:
                print(f"  [OK]    {label}: no overlap")

    print(f"\n{'='*40}")
    if total_errors:
        print(f"FAILED — {total_errors} error(s) found")
        sys.exit(1)
    else:
        print("PASSED — dataset looks clean")


if __name__ == "__main__":
    main()
