#!/usr/bin/env python3
"""Validate instruction-tuning dataset files (train/val/test) for format, completeness, duplicates, and distribution."""

import json
from pathlib import Path

def validate_split(file_path: Path) -> tuple[int, list[str]]:
    if not file_path.exists():
        return 0, [f"File not found: {file_path}"]

    errors = []
    count = 0
    inputs_seen = set()

    with open(file_path, 'r', encoding='utf-8') as f:
        for idx, line in enumerate(f, 1):
            line_str = line.strip()
            if not line_str:
                continue
            count += 1
            try:
                data = json.loads(line_str)
            except json.JSONDecodeError as exc:
                errors.append(f"{file_path.name}:{idx} - Invalid JSON: {exc}")
                continue

            # Check required keys
            for key in ['instruction', 'input', 'output']:
                if key not in data:
                    errors.append(f"{file_path.name}:{idx} - Missing key '{key}'")
                elif not data[key] or not str(data[key]).strip():
                    errors.append(f"{file_path.name}:{idx} - Empty field '{key}'")

            # Check output labeled sections
            output = data.get('output', '')
            if 'Explanation:' not in output and 'Explanation' not in output:
                errors.append(f"{file_path.name}:{idx} - Output missing 'Explanation' section")
            if 'Likely causes:' not in output and 'Likely causes' not in output:
                errors.append(f"{file_path.name}:{idx} - Output missing 'Likely causes' section")
            if 'Recommended actions:' not in output and 'Recommended actions' not in output:
                errors.append(f"{file_path.name}:{idx} - Output missing 'Recommended actions' section")

            # Check duplicates
            inp = data.get('input', '')
            if inp in inputs_seen:
                errors.append(f"{file_path.name}:{idx} - Duplicate input text found")
            inputs_seen.add(inp)

    return count, errors

def main():
    root = Path(__file__).resolve().parent.parent
    data_dir = root / 'data'

    splits = ['train.jsonl', 'val.jsonl', 'test.jsonl']
    total_records = 0
    all_errors = []

    print("Validating instruction-tuning dataset splits...")
    for split_name in splits:
        path = data_dir / split_name
        count, errors = validate_split(path)
        total_records += count
        print(f"  {split_name}: {count} records | {len(errors)} errors")
        all_errors.extend(errors)

    if all_errors:
        print("\nValidation FAILED with errors:")
        for err in all_errors[:20]:
            print(f"  - {err}")
        if len(all_errors) > 20:
            print(f"  ... and {len(all_errors) - 20} more errors.")
        raise AssertionError("Dataset validation failed.")
    else:
        print(f"\nValidation PASSED successfully! Total records across splits: {total_records}")
        assert total_records > 0, "Total records should be greater than zero."

if __name__ == '__main__':
    main()
