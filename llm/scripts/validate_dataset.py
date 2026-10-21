"""
validate_dataset.py - sanity-check the instruction-tuning dataset splits.

Checks:
  * Every record has instruction, input, output (non-empty strings)
  * Output contains all three required section headers
  * No duplicate (instruction, input) pairs within a split
  * Cross-split contamination (same input in train AND val/test)
  * Split distribution by fault_type
  * consecutive_failures <= 2 for non-UNREACHABLE faults
  * Severity consistent with metric thresholds
  * No 'minute(s)' pattern in output
  * 'sustained' only appears when duration >= SUSTAINED_MIN minutes
  * Top-N most repeated sentences (across all outputs)
"""
import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).parent.parent
REQUIRED_HEADERS = ["Explanation:", "Likely causes:", "Recommended actions:"]

# Mirrors generate_scenarios.py / build_dataset.py thresholds
T = {
    "latency_medium": 200.0,
    "latency_high":   500.0,
    "loss_medium":     20.0,
    "loss_high":       50.0,
    "cpu_high":        80.0,
    "cpu_critical":    90.0,
    "mem_high":        80.0,
    "mem_critical":    90.0,
    "unreachable_min_failures": 3,
}
SUSTAINED_MIN = 20  # minutes; 'sustained' is only valid at/above this duration

TOP_N_SENTENCES = 15  # report this many most-repeated sentences

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
            print(f"  [ERROR] {path.name} line {i}: bad JSON -- {e}")
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


def _parse_input_fields(inp: str) -> dict:
    """Parse the structured input block into a dict of field->value."""
    fields = {}
    for line in inp.splitlines():
        if ":" not in line:
            continue
        key, _, val = line.partition(":")
        fields[key.strip().lower()] = val.strip()
    return fields


def check_consecutive_failures(records: list[dict], name: str) -> int:
    """Non-UNREACHABLE faults must have consecutive_failures <= 2."""
    errors = 0
    for i, r in enumerate(records, 1):
        ft = fault_type_from_input(r)
        if "UNREACHABLE" in ft:
            continue  # UNREACHABLE faults can have any value; skip
        inp = r.get("input", "")
        m = re.search(r"Consecutive ICMP failures:\s*(\d+)", inp)
        if m:
            cf = int(m.group(1))
            if cf > 2:
                print(
                    f"  [ERROR] {name}:{i} non-UNREACHABLE fault '{ft}' "
                    f"has consecutive_failures={cf} (must be <= 2)"
                )
                errors += 1
    return errors


def check_severity(records: list[dict], name: str) -> int:
    """Severity in input block must be consistent with the metric thresholds."""
    errors = 0
    for i, r in enumerate(records, 1):
        ft  = fault_type_from_input(r)
        f   = _parse_input_fields(r.get("input", ""))
        sev = f.get("severity", "").lower()

        def _num(key: str) -> float | None:
            try:
                return float(f[key].rstrip("% ms").split()[0])
            except (KeyError, ValueError):
                return None

        lat  = _num("latency")
        loss = _num("packet loss")
        cpu  = _num("cpu usage")
        mem  = _num("memory usage")

        ok = True
        if ft == "DEVICE_UNREACHABLE" or ft == "DEVICE_UNREACHABLE+HIGH_PACKET_LOSS":
            ok = sev == "critical"
        elif ft == "HIGH_LATENCY":
            if sev == "medium":
                ok = lat is not None and T["latency_medium"] <= lat < T["latency_high"]
            elif sev == "high":
                ok = lat is not None and lat >= T["latency_high"]
        elif ft == "HIGH_PACKET_LOSS":
            if sev == "medium":
                ok = loss is not None and T["loss_medium"] <= loss < T["loss_high"]
            elif sev == "high":
                ok = loss is not None and loss >= T["loss_high"]
        elif ft == "HIGH_CPU_USAGE":
            if sev == "high":
                ok = cpu is not None and T["cpu_high"] <= cpu < T["cpu_critical"]
            elif sev == "critical":
                ok = cpu is not None and cpu >= T["cpu_critical"]
        elif ft == "HIGH_MEMORY_USAGE":
            if sev == "high":
                ok = mem is not None and T["mem_high"] <= mem < T["mem_critical"]
            elif sev == "critical":
                ok = mem is not None and mem >= T["mem_critical"]
        elif ft == "HIGH_CPU_USAGE+HIGH_MEMORY_USAGE":
            if sev == "critical":
                ok = (cpu is not None and cpu >= T["cpu_critical"]) or \
                     (mem is not None and mem >= T["mem_critical"])
            elif sev == "high":
                ok = (cpu is not None and T["cpu_high"] <= cpu < T["cpu_critical"]) and \
                     (mem is not None and T["mem_high"] <= mem < T["mem_critical"])
        # HIGH_LATENCY+* and SEED rows: skip detailed check (complex combined rules)

        if not ok:
            print(
                f"  [ERROR] {name}:{i} severity '{sev}' inconsistent with metrics "
                f"for fault '{ft}': lat={lat}, loss={loss}, cpu={cpu}, mem={mem}"
            )
            errors += 1
    return errors


def check_pluralization(records: list[dict], name: str) -> int:
    """Flag the 'minute(s)' hack -- should be replaced by proper conditional."""
    errors = 0
    for i, r in enumerate(records, 1):
        out = r.get("output", "")
        if "minute(s)" in out:
            print(f"  [ERROR] {name}:{i} output contains 'minute(s)' -- fix pluralization")
            errors += 1
    return errors


def _duration_from_input(inp: str) -> float | None:
    """Extract fault duration in minutes from the input block."""
    m = re.search(r"Fault duration:\s*(\d+)\s*minute", inp)
    if m:
        return float(m.group(1))
    return None


def check_sustained(records: list[dict], name: str) -> int:
    """'sustained' in Explanation section is only valid when duration >= SUSTAINED_MIN.

    Only scans the Explanation section (before 'Likely causes:') so that
    legitimate uses in causes/actions ("run a sustained ping test", "sustained
    queue-full drops") do not trigger false positives.
    """
    errors = 0
    for i, r in enumerate(records, 1):
        out = r.get("output", "")
        # Extract only the Explanation section text
        expl = out.lower().partition("likely causes:")[0]
        if "sustained" not in expl:
            continue
        dur = _duration_from_input(r.get("input", ""))
        if dur is not None and dur < SUSTAINED_MIN:
            print(
                f"  [ERROR] {name}:{i} Explanation uses 'sustained' but duration is "
                f"only {dur:.0f} min (threshold: {SUSTAINED_MIN} min)"
            )
            errors += 1
    return errors


def _sentences_from_output(out: str) -> list[str]:
    """Split an output block into individual sentences (rough split on '. ')."""
    # Tokenise on sentence-ending punctuation followed by a space or EOL
    raw = re.split(r"(?<=[.!?])\s+", out)
    return [s.strip() for s in raw if len(s.strip()) > 30]


def collect_repeated_sentences(all_records: list[dict], threshold: int = 10) -> list[tuple[str, int]]:
    """Return sentences that appear more than `threshold` times, sorted descending."""
    counter: Counter = Counter()
    for r in all_records:
        for sent in _sentences_from_output(r.get("output", "")):
            counter[sent] += 1
    return [(s, n) for s, n in counter.most_common(TOP_N_SENTENCES) if n > threshold]


def main() -> None:
    total_errors = 0
    split_inputs: dict[str, set[str]] = {}
    all_records_for_freq: list[dict] = []

    for split_name, path in SPLITS.items():
        print(f"\n=== {split_name} ({path.name}) ===")
        records = load(path)
        if not records:
            continue

        if split_name == "dataset":
            all_records_for_freq = records  # use full dataset for frequency check

        print(f"  Records : {len(records)}")

        errors  = check_fields(records, split_name)
        dupes   = check_duplicates(records, split_name)
        errors += check_consecutive_failures(records, split_name)
        errors += check_severity(records, split_name)
        errors += check_pluralization(records, split_name)
        errors += check_sustained(records, split_name)
        total_errors += errors

        # fault_type distribution
        counts = Counter(fault_type_from_input(r) for r in records)
        print("  Fault-type distribution:")
        for ft, n in sorted(counts.items()):
            print(f"    {ft:<50} {n:>4}")

        split_inputs[split_name] = {r.get("input", "") for r in records}

        if errors == 0 and dupes == 0:
            print("  [OK]")

    # cross-split contamination
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

    # repeated sentences
    print("\n=== Repeated sentences (top occurrences in dataset) ===")
    repeated = collect_repeated_sentences(all_records_for_freq, threshold=10)
    if repeated:
        print(f"  {'Count':>6}  Sentence")
        for sent, n in repeated:
            preview = sent[:100] + ("..." if len(sent) > 100 else "")
            print(f"  {n:>6}  {preview}")
        print(
            f"\n  {len(repeated)} sentence(s) appear >10 times -- "
            "each needs at least 3 alternative phrasings."
        )
    else:
        print("  [OK] No sentence appears more than 10 times.")

    print(f"\n{'='*40}")
    if total_errors:
        print(f"FAILED -- {total_errors} error(s) found")
        sys.exit(1)
    else:
        print("PASSED -- dataset looks clean")


if __name__ == "__main__":
    main()
