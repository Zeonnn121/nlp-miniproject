# Intelligent Network Device Monitoring and Fault Detection System with Domain-Specific QLoRA LLM Triage

[![Python 3.12](https://img.shields.io/badge/Python-3.12-blue.svg)](https://www.python.org/)
[![Django 5.0](https://img.shields.io/badge/Django-5.0-green.svg)](https://www.djangoproject.com/)
[![React 19](https://img.shields.io/badge/React-19.0-61dafb.svg)](https://react.dev/)
[![Tailwind CSS v4](https://img.shields.io/badge/TailwindCSS-v4.0-38bdf8.svg)](https://tailwindcss.com/)
[![Qwen2.5-1.5B](https://img.shields.io/badge/LLM-Qwen2.5--1.5B--Instruct-blueviolet.svg)](https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct)
[![PEFT QLoRA](https://img.shields.io/badge/PEFT-QLoRA%20(NF4)-orange.svg)](https://github.com/huggingface/peft)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

An intelligent, full-stack AIOps platform that unifies real-time asynchronous network device monitoring (**ICMP**, **SNMP v1/v2c**, and **HTTP**) with a domain-adapted, instruction-tuned **Large Language Model (Qwen2.5-1.5B-Instruct via QLoRA)** to automate incident triage, root-cause diagnosis, and actionable remediation recommendations.

---

## Academic Project & Report

* **Institution:** Department of Computer Engineering, Fr. Conceicao Rodrigues College of Engineering (CRCE), Mumbai, India
* **Team Members:**
  * Jeet Chavan (10584)
  * Zeon Dsouza (10598)
  * Dhruv Dsouza (10597)
  * Delisha Duarte (10599)
* **Academic Report Source:** [`paper.tex`](paper.tex) / [`miniproject report.tex`](miniproject%20report.tex) *(Conference Double-Column Format)*

---

## System Dashboard & Visual Overview

### 1. Web Operator Dashboard
Real-time device reachability, health status cards, active critical alarm notifications, and network inventory controls.

![Web Operator Dashboard](figures/dashboard.png)

---

### 2. Real-Time Telemetry & Metric Trends
Asynchronous polling engine capturing ICMP round-trip latency spikes and packet loss disruptions visualized via Recharts.

| (a) ICMP RTT Latency Spike (ms) | (b) Packet Loss Percentage (%) |
| :---: | :---: |
| ![ICMP Latency Trend](figures/latency_trend.png) | ![Packet Loss Trend](figures/packet_loss.png) |

---

### 3. AI-Powered Incident Triage Modal
When an anomaly triggers a fault, the fine-tuned LLM generates a structured 3-part diagnostic report directly inside the operator console.

![AI Incident Triage Modal](figures/fault_triage.png)

---

### 4. Actual QLoRA Fine-Tuning Loss Convergence
Actual Google Colab training results over 3 epochs on `Qwen2.5-1.5B-Instruct` using 4-bit NF4 quantization. Cross-entropy training loss converged from **1.37 to 0.16** (88.3% reduction) with validation loss dropping from **0.44 to 0.16**.

![QLoRA Loss Curve](figures/loss_curve.png)

---

## Architecture

```text
                        Browser
                           │
                   React 19 / TypeScript
                           │ (REST / JSON)
                           ▼
                  Django 5 REST API
                           │
         ┌─────────────────┼─────────────────┐
         │                 │                 │
    SQLite Database  Celery Beat       Celery Workers
 (Faults & Metrics)  (Scheduler)             │ (Redis Broker)
         │                 │                 ▼
         │                 └───────► Probing Subsystem
         │                           ├── ICMP Ping (RTT & Loss)
         │                           ├── SNMP v1/v2c (CPU & RAM)
         │                           └── HTTP Probe (Status & Latency)
         │                                   │
         ▼ (Fault Event Trigger)             ▼ (Metric Telemetry)
  QLoRA LLM Inference Engine <───────────────┘
   (Qwen2.5-1.5B-Instruct)
         │
         ▼
 Structured Triage Report
 (Explanation • Causes • Actions) ──► Saved to DB ──► Pushed to Dashboard
```

---

## Key Features

### 1. Multi-Protocol Telemetry Probing
* **ICMP Ping:** High-precision round-trip time (`T_rtt`) measurement and packet loss percentage (`Loss %`).
* **SNMP v1/v2c Polling:** Live OID collection for system CPU utilization and RAM occupancy.
* **HTTP Endpoint Probing:** Response status code verification (`2xx`/`3xx`) and timeout latency tracking (`T_resp < 5.0s`).

### 2. Deterministic Fault State Machine
* **Lifecycle:** `Active` &rarr; `Acknowledged` &rarr; `Resolved` (with automatic recovery)
* **Threshold Rules:**
  * **Latency:** Medium (`200 ms <= T_rtt < 500 ms`), High (`T_rtt >= 500 ms`).
  * **Packet Loss:** Medium (`20% <= Loss < 50%`), High (`Loss >= 50%`).
  * **Unreachable:** Triggered on 3 or more (`k >= 3`) consecutive ICMP echo timeouts.
  * **Resources:** High (`CPU/RAM >= 80%`), Critical (`CPU/RAM >= 90%`).
* **Auto-Resolution:** Active faults automatically transition to `Resolved` once consecutive probes return within safe operating limits.

### 3. NLP Curriculum & Dataset Engineering
* **Linguistic Preprocessing:**
  * **Regular Expressions (`re` module):** Strict IPv4 validation with `^(\d{1,3}\.){3}\d{1,3}$`, numerical duration/metric extraction with `re.search()`, multi-metric anomaly parsing with `re.findall()`, lookbehind sentence tokenization with `re.split(r"(?<=[.!?])\s+", text)`, and text sanitization with `re.sub()`.
  * **Tokenization:** Rule-based sentence and word tokenization contrasted against Byte-Pair Encoding (BPE) subword tokenization.
  * **Stemming & Lemmatization:** NLTK `PorterStemmer` and `WordNetLemmatizer` (verb-then-noun) in `validate_dataset.py` report top-N root/lemma frequencies and flag lemma-identical sentences that appear in more than one dataset split (*drops*, *dropped*, *dropping* &rarr; *drop*; *congested* &rarr; *congest*).
* **Dataset Splits (830 Total Records):**
  * **Train Split:** 664 records (80%)
  * **Validation Split:** 85 records (10%)
  * **Test Split:** 81 records (10%)
  * **Out-of-Domain (OOD) Test Set:** 20 stress-test compound fault records.

### 4. QLoRA LLM Fine-Tuning Pipeline
* **Base Model:** `Qwen/Qwen2.5-1.5B-Instruct`
* **Quantization:** 4-bit NormalFloat (NF4) with double quantization via `bitsandbytes`.
* **Adapter Architecture:** LoRA rank $r = 16$, scaling factor $\alpha = 32$, dropout $0.05$, targeting all linear projection modules (`q_proj`, `k_proj`, `v_proj`, `o_proj`, `gate_proj`, `up_proj`, `down_proj`).
* **Supervised Fine-Tuning (SFT):** TRL `SFTTrainer` with completion-only prompt-loss masking.
* **Trained Model Weights:** Saved directly in [`llm/outputs/adapter/`](llm/outputs/adapter/) (`adapter_model.safetensors`, 73.9 MB).

---

## Natural Language Processing (NLP) & Regex Foundations

This project integrates applied Natural Language Processing (NLP) and regular expressions into an end-to-end Network AIOps platform. Telemetry logs, fault notifications, and incident descriptions are processed through classical NLP pipelines, morphological normalization, and generative instruction-tuned LLMs.

### 1. Regular Expressions (Regex) & Common Metacharacters

Regular expressions (regex) define search patterns used for input validation, unstructured log parsing, metric telemetry extraction, and prompt sanitization.

#### Core Metacharacters & Concepts

| Metacharacter | Designation | Definition & Behavior | Network Telemetry Usage & Pattern Example |
| :---: | :--- | :--- | :--- |
| `.` | Dot (Wildcard) | Matches any single character except a newline (`\n`) | Matches log delimiters: `device.status` or `.*` payload match |
| `^` | Caret (Anchor) | Asserts position at the **start** of a string/line | Strict IPv4 start anchor: `^192\.168\.` |
| `$` | Dollar (Anchor) | Asserts position at the **end** of a string/line | Strict termination: `\.com$` or IPv4 end `\.\d{1,3}$` |
| `*` | Star (Quantifier) | Matches **0 or more** occurrences of the preceding token (greedy) | Matches arbitrary spacing or trailing logs: `\s*` or `.*` |
| `+` | Plus (Quantifier) | Matches **1 or more** occurrences of the preceding token | Captures consecutive digits: `\d+` (e.g., latency ms value) |
| `?` | Question Mark | Matches **0 or 1** occurrence (optional token) or lazy qualifier | Optional decimal fraction: `\d+(\.\d+)?` or protocol `https?` |
| `[]` | Character Class | Matches any single character enclosed within the brackets | Status code ranges: `[1-5]\d{2}` or hex digits `[0-9a-fA-F]` |
| `{}` | Explicit Bounds | Matches specified repetitions: `{n}` exact or `{min,max}` range | Octet length bounds `{1,3}` in IPv4 validation: `\d{1,3}` |
| `\d` | Digit Shorthand | Matches any decimal digit `[0-9]` | Port numbers, ping latency, packet loss percentage: `\d+` |
| `\w` | Word Character | Matches any alphanumeric character plus underscore `[a-zA-Z0-9_]` | Device identifiers, interface names: `eth\d+`, `\w+` |
| `\s` | Whitespace | Matches any whitespace character (space, tab, newline `[ \t\n\r\f\v]`) | Normalizing log indentation and spacing: `\s+` |

---

### 2. Python's `re` Module Functions & Practice

Python provides the built-in `re` module for compiling and executing regular expressions. Below are implementations and practical network monitoring examples for the primary functions:

#### A. `re.match(pattern, string)`
* **Concept:** Tests whether the pattern matches **strictly at the start** of the string.
* **Network Use Case:** Ingestion boundary validation for IPv4 addresses, hostnames, and protocol headers before storing device records in the database.
```python
import re

# Strict IPv4 Address Validation
def validate_ipv4(ip: str) -> bool:
    pattern = r"^(\d{1,3}\.){3}\d{1,3}$"
    if re.match(pattern, ip):
        # Validate that each octet is in the valid 0-255 range
        octets = [int(o) for o in ip.split(".")]
        return all(0 <= o <= 255 for o in octets)
    return False

# Test examples
print(validate_ipv4("192.168.1.1"))    # True
print(validate_ipv4("999.10.0.1"))      # False (octet > 255)
print(validate_ipv4("invalid_host"))   # False
```

#### B. `re.search(pattern, string)`
* **Concept:** Scans through the entire string to find the **first location** where the regular expression pattern matches.
* **Network Use Case:** Extracting fault duration, consecutive failure thresholds, and error codes from unstructured telemetry strings.
```python
import re

log_message = "CRITICAL [2026-10-28 14:22:01] core-router-01: High Latency detected. Fault duration: 25 minutes. Threshold exceeded."

# Extract continuous anomaly duration in minutes
match = re.search(r"Fault duration:\s*(\d+)\s*minute", log_message)
if match:
    duration_mins = int(match.group(1))
    print(f"Extracted Anomaly Duration: {duration_mins} minutes")
```

#### C. `re.findall(pattern, string)`
* **Concept:** Returns **all non-overlapping matches** of the pattern in the string as a list of strings or tuples.
* **Network Use Case:** Extracting multiple numeric metrics (RTT latency, packet loss, CPU utilization, RAM usage) from multi-line device alarm logs.
```python
import re

telemetry_stream = """
Interface gig0/1: CPU utilization: 94.2% | Memory: 89.1%
ICMP probe: RTT: 540.2ms | Loss: 35.0% | Status: DEGRADED
"""

# Extract all metric names, numerical values, and units
pattern = r"(\w+(?:\s+\w+)?):\s*(\d+(?:\.\d+)?)\s*(%|ms)"
extracted_metrics = re.findall(pattern, telemetry_stream)

for metric_name, val, unit in extracted_metrics:
    print(f"Parsed -> Metric: {metric_name:<16} Value: {float(val):<6} Unit: {unit}")
```

#### D. `re.split(pattern, string)`
* **Concept:** Splits the string by occurrences of the pattern.
* **Network Use Case:** Sentence boundary tokenization on terminal punctuation (`.`, `!`, `?`) using **positive lookbehinds** (`(?<=[.!?])\s+`) so punctuation marks remain attached to their originating diagnostic sentences.
```python
import re

diagnostic_report = "High packet loss observed on border gateway. Queue capacity reached 98%! Immediate route rerouting is advised."

# Split into sentences without stripping the punctuation marks
sentences = re.split(r"(?<=[.!?])\s+", diagnostic_report.strip())
for idx, sentence in enumerate(sentences, 1):
    print(f"Sentence {idx}: {sentence}")
```

#### E. `re.sub(pattern, replacement, string)`
* **Concept:** Replaces all occurrences of the pattern with a replacement string.
* **Network Use Case:** Sanitizing raw device logs by collapsing irregular whitespace, stripping ANSI escape codes, and redacting sensitive credentials.
```python
import re

raw_console_log = "Router-01   \t\n  auth failed for user 'admin'   \r\n  password=secretPass123!   "

# 1. Redact credentials
sanitized = re.sub(r"password=\S+", "password=[REDACTED]", raw_console_log)
# 2. Collapse irregular whitespace into single spaces
sanitized = re.sub(r"\s+", " ", sanitized).strip()

print(f"Sanitized Log: {sanitized}")
```

---

### 3. Stemming and Lemmatization using NLTK

When building training datasets for domain-specific language models, lexical variation (such as different verb tenses and plural forms) can introduce data sparsity and cause test-train leakage. The Natural Language Toolkit (**NLTK**) is employed for morphological normalization:

#### Stemming vs. Lemmatization Comparison

| Feature | Stemming (`nltk.stem.PorterStemmer`) | Lemmatization (`nltk.stem.WordNetLemmatizer`) |
| :--- | :--- | :--- |
| **Methodology** | Heuristic rule-based suffix stripping (e.g., removing *-ing*, *-ed*, *-s*) | Dictionary and morphological analysis using WordNet with Part-of-Speech (POS) tags |
| **Output Form** | Crude root stem; may not be a valid dictionary word (e.g., *satur-* from *saturation*) | Valid canonical headword / dictionary lemma (e.g., *saturate*, *drop*, *congest*) |
| **Context & POS** | Context-free; does not consider sentence grammar or grammatical category | Context-aware; uses POS parameters (`pos=wordnet.VERB`, `pos=wordnet.NOUN`) |
| **Execution Speed** | Extremely fast and computationally lightweight | Slower due to lexical database lookups and morphological rules |
| **Application in System** | High-throughput vocabulary frequency auditing in `validate_dataset.py` | Semantic deduplication across training, validation, and test dataset splits |

#### Hands-On Implementation with NLTK:
```python
import nltk
from nltk.stem import PorterStemmer, WordNetLemmatizer
from nltk.corpus import wordnet

# Download required NLTK lexical databases
nltk.download('wordnet', quiet=True)
nltk.download('omw-1.4', quiet=True)

stemmer = PorterStemmer()
lemmatizer = WordNetLemmatizer()

network_terms = [
    "drops", "dropped", "dropping",
    "congested", "congestion",
    "saturating", "saturates", "saturated",
    "failures", "failed", "failing"
]

print(f"{'Original Term':<16} | {'Porter Stem':<14} | {'WordNet Lemma (Verb)':<20}")
print("-" * 56)
for term in network_terms:
    stem = stemmer.stem(term)
    lemma = lemmatizer.lemmatize(term, pos=wordnet.VERB)
    print(f"{term:<16} | {stem:<14} | {lemma:<20}")
```

---

### 4. spaCy Natural Language Processing with Python

**spaCy** is an industrial-strength NLP library utilized for rich linguistic analysis, structured information extraction, and parsing unstructured network alarms into structured operational knowledge.

#### Core Pipeline Capabilities & Use Cases:
1. **Linguistic Tokenization:** Intelligently segments network-specific strings (such as hyphenated device hostnames `switch-core-01` and IP addresses) without corrupting domain syntax.
2. **Part-of-Speech (POS) Tagging:** Identifies operational verbs (*reboot*, *reroute*, *investigate*) and infrastructure nouns (*switch*, *transceiver*, *VLAN*).
3. **Syntactic Dependency Parsing:** Discovers root causes by mapping relationships between telemetry subjects and fault effects (e.g., `[Buffer exhaustion] --(causes)--> [packet drop]`).
4. **Named Entity Recognition (NER):** Detects domain entities (`NETWORK_DEVICE`, `IP_ADDRESS`, `METRIC`, `PROTOCOL`, `TIMESTAMP`).
5. **Sentence Segmentation:** Utilizes `doc.sents` to cleanly partition triage summaries into structured subsections (`Explanation`, `Likely causes`, `Recommended actions`).

#### Hands-On Implementation with spaCy:
```python
import spacy

# Load spaCy's standard English pipeline
nlp = spacy.load("en_core_web_sm")

fault_description = (
    "Core router rtr-nyc-01 at 10.0.4.1 experienced an unexpected BGP neighbor session reset. "
    "CPU utilization spiked to 96.5% during packet re-routing. "
    "Engineers must verify interface gig0/0 and inspect route flaps immediately."
)

doc = nlp(fault_description)

# 1. Tokenization, Part-of-Speech (POS), and Lemmatization
print("=== spaCy Linguistic & POS Analysis ===")
for token in doc:
    if not token.is_stop and not token.is_punct:
        print(f"Token: {token.text:<18} Lemma: {token.lemma_:<16} POS: {token.pos_:<8} Dep: {token.dep_}")

# 2. Sentence Segmentation
print("\n=== Sentence Segmentation ===")
for i, sent in enumerate(doc.sents, 1):
    print(f"[{i}] {sent.text.strip()}")

# 3. Named Entity Recognition
print("\n=== Named Entities ===")
for ent in doc.ents:
    print(f"Entity: {ent.text:<20} Label: {ent.label_}")
```

---

### 5. Traceability: Where NLP & Regex Concepts Are Applied in This Codebase

The following table provides full traceability across the repository, linking each NLP concept to its exact implementation file and role in the system:

| NLP / Regex Concept | Technique / Library | Source File Location | Operational Purpose in System |
| :--- | :--- | :--- | :--- |
| **Strict IPv4 Validation** | Python `re.match` | [`backend/network/models.py`](backend/network/models.py)<br>[`backend/network/serializers.py`](backend/network/serializers.py) | Validates IPv4 octet bounds on device registration and API requests. |
| **HTTP Endpoint URL Validation** | Python `re.match` | [`backend/network/httpcheck.py`](backend/network/httpcheck.py) | Checks HTTP/HTTPS URL syntax, port limits, and protocol bounds. |
| **Anomaly Metric Mining** | Python `re.search` | [`llm/scripts/validate_dataset.py`](llm/scripts/validate_dataset.py) | Extracts fault duration minutes and consecutive ICMP timeout counters. |
| **Multi-Metric Telemetry Parsing** | Python `re.findall` | [`llm/scripts/generate_scenarios.py`](llm/scripts/generate_scenarios.py) | Parses multi-metric anomaly telemetry across compound failure events. |
| **Sentence Boundary Segmentation** | Python `re.split` | [`llm/scripts/validate_dataset.py`](llm/scripts/validate_dataset.py) | Implements lookbehind sentence splitting on terminal punctuation. |
| **Log Sanitization & Whitespace Cleanup** | Python `re.sub` | [`llm/scripts/build_dataset.py`](llm/scripts/build_dataset.py) | Normalizes spacing, removes escape characters, and formats seed prompts. |
| **Stemming & Vocabulary Auditing** | NLTK `PorterStemmer` | [`llm/scripts/validate_dataset.py`](llm/scripts/validate_dataset.py) | `stem_tokens()` reduces every content word to its Porter root and reports the top-15 most frequent roots. |
| **Lemma-Based Cross-Split Deduplication** | NLTK `WordNetLemmatizer` | [`llm/scripts/validate_dataset.py`](llm/scripts/validate_dataset.py) | `check_cross_split_lemmas()` compares verb-then-noun lemma signatures to flag near-duplicate sentences shared between train, validation, and test. |
| **Industrial NLP & NER Analysis** | spaCy (`en_core_web_sm`) | [`llm/evaluate.py`](llm/evaluate.py) | Evaluates diagnostic text structure, entity preservation, and coherence. |
| **Domain-Specific Fine-Tuning** | Hugging Face TRL + PEFT | [`llm/train_lora.py`](llm/train_lora.py) | Fine-tunes `Qwen2.5-1.5B-Instruct` using 4-bit QLoRA for automated triage. |

---

## Repository Structure

```text
nlp-miniproject/
├── backend/                        # Django 5 REST backend & Celery monitoring engine
│   ├── backend/                    # Settings, WSGI, Celery configuration
│   └── network/                    # Models, Probes (ICMP, SNMP, HTTP), Fault engine, API
├── frontend/                       # React 19 + TypeScript + Vite + Tailwind CSS v4
│   └── src/                        # Dashboard, device inventory, history, faults UI
├── llm/                            # Applied NLP Subsystem
│   ├── data/                       # train.jsonl, val.jsonl, test.jsonl, ood_test.jsonl
│   ├── outputs/adapter/            # Trained QLoRA adapter weights (safetensors & config)
│   ├── scripts/                    # generate_scenarios.py, build_dataset.py, validate_dataset.py
│   ├── train_lora.py               # Hugging Face TRL QLoRA training pipeline
│   └── train_lora.ipynb            # Google Colab T4 GPU fine-tuning notebook
├── figures/                        # Publication figures & high-res dashboard screenshots
├── docs/                           # Architecture specs, database models, thesis chapters
├── deploy/                         # Nginx and systemd deployment templates
├── paper.tex                       # Conference double-column report source
├── miniproject report.tex          # LaTeX project report source
├── start.md                        # Quick developer runbook
└── README.md                       # Master documentation
```

---

## Quick-Start Guide

### Prerequisites
* Python 3.12+
* Node.js v20+ & npm
* Redis server

---

### Step 1: Backend Setup

```bash
cd backend
python3 -m venv env
source env/bin/activate       # On Windows: env\Scripts\activate
pip install -r requirements.txt
python manage.py migrate --noinput
python manage.py createsuperuser
python manage.py runserver
```
API endpoint: `http://127.0.0.1:8000/api/health/`

---

### Step 2: Background Monitoring (Celery & Redis)

In separate terminal tabs:

```bash
# Terminal A: Start Redis
redis-server

# Terminal B: Start Celery Worker
cd backend
source env/bin/activate
python -m celery -A backend worker -l info

# Terminal C: Start Celery Beat Scheduler
cd backend
source env/bin/activate
python -m celery -A backend beat -l info
```

---

### Step 3: Frontend Dashboard

```bash
cd frontend
npm install
npm run dev
```
Open your browser at `http://localhost:5173` (Login using your superuser credentials).

### Step 4: NLP Dataset Validation & LLM Fine-Tuning

```bash
# 1. Validate dataset integrity, headers, and regex constraints
python llm/scripts/validate_dataset.py

# 2. Run QLoRA training locally (requires CUDA GPU; alternatively run llm/train_lora.ipynb on Google Colab)
python llm/train_lora.py
```

---

## Monitoring Configuration

Every registered device automatically receives a `MonitoringConfiguration`.

Configuration includes:

- monitoring enabled/disabled
- interval in seconds
- SNMP enabled/disabled
- SNMP version
- SNMP community (stored server-side and not exposed by the configuration API)
- SNMP port
- SNMP timeout
- selected metrics
- HTTP endpoint monitoring enabled/disabled
- HTTP endpoint URL (`http://` or `https://`, no embedded credentials)
- HTTP request timeout
- optional exact expected HTTP status (any 2xx/3xx when unset)

The current device model accepts IPv4 addresses only.

## Fault Detection

The implemented deterministic rules cover:

- device unreachable
- high latency
- high packet loss
- high CPU usage from supported SNMP metrics
- high memory usage from supported SNMP metrics
- HTTP endpoint failure (connection failure, or an unexpected status code)
- HTTP slow response

The model also contains interface/connectivity fault types used by the domain model, but they are not represented as a claim of an independent automatic detection algorithm unless supported by the current monitoring path.

Faults have `critical`, `high`, `medium`, or `low` severity and follow:

```text
active → acknowledged → resolved
active → resolved
```

## LLM Fault Explainer

The optional fault explainer turns a detected fault into a structured `Explanation`, `Likely causes`, and `Recommended actions` using a locally fine-tuned Qwen2.5-1.5B LoRA adapter, with a deterministic fallback when the model is disabled or unavailable. It is exposed as `POST /api/faults/<id>/explain/` and surfaced as **Explain this fault** in the fault detail view.

See [`docs/LLM_FINE_TUNING.md`](docs/LLM_FINE_TUNING.md) for dataset design, training configuration, evaluation, integration, limitations, and reproduction steps.

## API Documentation

Start with [`docs/API.md`](docs/API.md) for device and monitoring endpoints.

Additional API references:

- [`docs/FAULT_API.md`](docs/FAULT_API.md)
- [`docs/HISTORICAL_API.md`](docs/HISTORICAL_API.md)
- [`docs/NOTIFICATIONS.md`](docs/NOTIFICATIONS.md)
- [`docs/AUTOMATED_MONITORING.md`](docs/AUTOMATED_MONITORING.md)

Authentication uses Django REST Framework token authentication:

```http
Authorization: Token <token>
```

Protected application endpoints require an authenticated staff administrator.

## Testing and Validation

Backend:
```bash
cd backend
python manage.py test
```

---

## Evaluation Results

| Metric | Zero-Shot Baseline | Fine-Tuned QLoRA Adapter | Relative Gain |
| :--- | :---: | :---: | :---: |
| **Structural Output Compliance** | 58.0% | **100.0%** | +42.0% |
| **Out-of-Domain Compliance (OOD)** | 45.0% | **100.0%** | +55.0% |
| **BLEU-4 Score (Overall)** | 0.09 | **0.38** | ~4.2x |
| **ROUGE-L Score (Overall)** | 0.21 | **0.54** | ~2.6x |
| **Final Cross-Entropy Loss** | 2.14 | **0.16** | -88.3% error reduction |

---

## License
This project is licensed under the MIT License — see the [LICENSE](LICENSE) file for details.
