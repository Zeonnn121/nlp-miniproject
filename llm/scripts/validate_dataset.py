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
  * Porter-stem and WordNet-lemma frequency audits over all outputs
  * Cross-split duplicate sentences detected after lemmatization
"""
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

try:  # NLTK is optional: the structural checks below run without it.
    from nltk.corpus import wordnet
    from nltk.stem import PorterStemmer, WordNetLemmatizer
    from nltk.tokenize import RegexpTokenizer
    NLTK_AVAILABLE = True
except ImportError:
    NLTK_AVAILABLE = False

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
TOP_N_ROOTS = 15  # report this many most-frequent stems / lemmas
LEMMA_DUPLICATE_MIN_TOKENS = 6  # ignore short sentences in cross-split lemma matching
NLTK_HINT = "python -m nltk.downloader wordnet omw-1.4"

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


# ---------------------------------------------------------------------------
# Morphological normalization: Porter stemming + WordNet lemmatization
# ---------------------------------------------------------------------------

TOKEN_PATTERN = r"[A-Za-z][A-Za-z0-9]*(?:[-'][A-Za-z0-9]+)*"
STOPWORDS = frozenset("""
    a about above after again against all also an and any are as at be been before
    being below between both but by can could did do does doing down during each few
    for from further had has have having he her here hers him his how i if in into is
    it its itself just me might more most must my no nor not now of off on once only or
    other our out over own same she should so some such than that the their them then
    there these they this those through to too under until up very was we were what
    when where which while who whom why will with would you your
""".split())

_MORPH_TOOLS = None
_MORPH_UNAVAILABLE = False


def _morphology_tools():
    """Build the NLTK tokenizer/stemmer/lemmatizer once, or return None."""
    global _MORPH_TOOLS, _MORPH_UNAVAILABLE
    if _MORPH_TOOLS is not None or _MORPH_UNAVAILABLE:
        return _MORPH_TOOLS
    if not NLTK_AVAILABLE:
        print("  [SKIP] NLTK not installed -- run: pip install nltk")
        _MORPH_UNAVAILABLE = True
        return None
    try:
        wordnet.synsets("network")  # force-loads the WordNet corpus
    except LookupError:
        print(f"  [SKIP] NLTK WordNet corpus missing -- run: {NLTK_HINT}")
        _MORPH_UNAVAILABLE = True
        return None
    _MORPH_TOOLS = (
        RegexpTokenizer(TOKEN_PATTERN),
        PorterStemmer(),
        WordNetLemmatizer(),
    )
    return _MORPH_TOOLS


def _content_tokens(text: str, tokenizer) -> list[str]:
    """Lowercase word tokens with stopwords and bare numbers removed."""
    return [tok.lower() for tok in tokenizer.tokenize(text) if tok.lower() not in STOPWORDS]


def _lemma(token: str, lemmatizer) -> str:
    """Verb-first, then noun -- triage text is dominated by actions and devices."""
    return lemmatizer.lemmatize(lemmatizer.lemmatize(token, pos=wordnet.VERB), pos=wordnet.NOUN)


def stem_tokens(text: str) -> list[str]:
    """Porter stems of the content words: saturates / saturated / saturating -> satur."""
    tools = _morphology_tools()
    if tools is None:
        return []
    tokenizer, stemmer, _ = tools
    return [stemmer.stem(tok) for tok in _content_tokens(text, tokenizer)]


def lemma_tokens(text: str) -> list[str]:
    """WordNet lemmas of the content words: drops / dropped / dropping -> drop."""
    tools = _morphology_tools()
    if tools is None:
        return []
    tokenizer, _, lemmatizer = tools
    return [_lemma(tok, lemmatizer) for tok in _content_tokens(text, tokenizer)]


def collect_root_frequencies(
    records: list[dict], kind: str = "stem"
) -> list[tuple[str, int, list[str]]]:
    """Count stems (or lemmas) across all outputs, keeping sample surface forms."""
    tools = _morphology_tools()
    if tools is None:
        return []
    tokenizer, stemmer, lemmatizer = tools
    counter: Counter = Counter()
    forms: dict[str, set[str]] = defaultdict(set)
    for r in records:
        for tok in _content_tokens(r.get("output", ""), tokenizer):
            root = stemmer.stem(tok) if kind == "stem" else _lemma(tok, lemmatizer)
            counter[root] += 1
            forms[root].add(tok)
    return [(root, n, sorted(forms[root])[:3]) for root, n in counter.most_common(TOP_N_ROOTS)]


def _lemma_signature(text: str) -> tuple[str, ...]:
    """Ordered lemma sequence used to compare sentences semantically."""
    return tuple(lemma_tokens(text))


def check_cross_split_lemmas(records_by_split: dict[str, list[dict]]) -> int:
    """Warn when a sentence is identical after lemmatization but used in two splits."""
    if _morphology_tools() is None:
        return 0
    owners: dict[tuple[str, ...], set[str]] = defaultdict(set)
    previews: dict[tuple[str, ...], str] = {}
    for split_name, records in records_by_split.items():
        for r in records:
            for sent in _sentences_from_output(r.get("output", "")):
                signature = _lemma_signature(sent)
                if len(signature) < LEMMA_DUPLICATE_MIN_TOKENS:
                    continue
                owners[signature].add(split_name)
                previews.setdefault(signature, sent)
    leaks = {sig: splits for sig, splits in owners.items() if len(splits) > 1}
    for signature, splits in list(leaks.items())[:TOP_N_SENTENCES]:
        preview = previews[signature][:100] + ("..." if len(previews[signature]) > 100 else "")
        print(f"  [WARN]  lemma-identical sentence in {'+'.join(sorted(splits))}: {preview}")
    if not leaks:
        print("  [OK]    no sentence is lemma-identical across splits")
    elif len(leaks) > TOP_N_SENTENCES:
        print(f"  ... {len(leaks) - TOP_N_SENTENCES} more lemma-identical sentence(s)")
    return len(leaks)


def main() -> None:
    total_errors = 0
    split_inputs: dict[str, set[str]] = {}
    split_records: dict[str, list[dict]] = {}
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
        if split_name != "dataset":
            split_records[split_name] = records

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

    # vocabulary roots (Porter stemming)
    print("\n=== Vocabulary roots (Porter stemming) ===")
    stem_counts = collect_root_frequencies(all_records_for_freq, kind="stem")
    if stem_counts:
        print(f"  {'Root':<24} {'Count':>6}  Surface forms")
        for root, n, forms in stem_counts:
            print(f"  {root:<24} {n:>6}  {', '.join(forms)}")
    else:
        print("  [SKIP] stemming audit unavailable")

    # canonical lemmas (WordNet)
    print("\n=== Canonical lemmas (WordNet lemmatization) ===")
    lemma_counts = collect_root_frequencies(all_records_for_freq, kind="lemma")
    if lemma_counts:
        print(f"  {'Lemma':<24} {'Count':>6}  Surface forms")
        for lemma, n, forms in lemma_counts:
            print(f"  {lemma:<24} {n:>6}  {', '.join(forms)}")
    else:
        print("  [SKIP] lemmatization audit unavailable")

    # semantic (lemma-level) duplication across splits
    print("\n=== Cross-split lemma duplicates ===")
    check_cross_split_lemmas(split_records)

    print(f"\n{'='*40}")
    if total_errors:
        print(f"FAILED -- {total_errors} error(s) found")
        sys.exit(1)
    else:
        print("PASSED -- dataset looks clean")


if __name__ == "__main__":
    main()
