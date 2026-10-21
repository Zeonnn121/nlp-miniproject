# LLM Fine-Tuning and Fault Explainer

This document describes the optional local language-model component: how the instruction dataset was built, how the Qwen2.5 LoRA adapter was trained, how it is evaluated, how it is integrated into the Django/React application, and what its limitations are.

The LLM is **not** part of the deterministic fault-detection path. Detection remains rule-based; the model only turns an already-detected `FaultEvent` into a structured explanation. When the model is disabled or unavailable, the application returns a deterministic template explanation instead.

## 1. Motivation and problem statement

The monitoring backend already detects faults deterministically from thresholds (latency, packet loss, CPU, memory, reachability, HTTP probes). A detected fault, however, is a short record: a type, a severity, a device, and a one-line description such as `Latency is 640.000 ms, above 500.000 ms.` An administrator still has to interpret what that means, form hypotheses about the cause, and decide what to check first.

The fine-tuned model addresses that interpretation gap:

- **Explain** what the metrics mean and why the condition matters.
- **Rank likely causes** appropriate to the device type and fault pattern.
- **Recommend concrete actions** in priority order.

The goal is an operator-assistance feature, not autonomous diagnosis. The model is small enough to run locally, so fault data does not need to leave the deployment host. The deterministic fallback ensures the UI never breaks when the model or its GPU dependencies are absent.

## 2. Dataset design

### 2.1 Source data

Two sources are combined:

| Source | File | Count | Origin |
|---|---|---:|---|
| Generated fault scenarios | `llm/data/scenarios.jsonl` | 800 | Synthetic, from `llm/scripts/generate_scenarios.py` |
| Handwritten seed examples | `llm/data/handwritten_seed.jsonl` | 30 | Manually authored |
| Full instruction dataset | `llm/data/dataset.jsonl` | 830 | Merged output of `llm/scripts/build_dataset.py` |

Most of the dataset is **synthetic**. The 800 scenarios are sampled by `generate_scenarios.py` using a fixed seed (`SEED = 42`) from 15 generator bands across these fault patterns:

- `DEVICE_UNREACHABLE`
- `HIGH_LATENCY`
- `HIGH_PACKET_LOSS`
- `HIGH_CPU_USAGE`
- `HIGH_MEMORY_USAGE`
- `HIGH_LATENCY+HIGH_PACKET_LOSS`
- `HIGH_CPU_USAGE+HIGH_MEMORY_USAGE`
- `HIGH_LATENCY+HIGH_CPU_USAGE`
- `DEVICE_UNREACHABLE+HIGH_PACKET_LOSS`

The generator covers five device types: router, switch, server, access point, and firewall. Metric ranges mirror the real `FaultThresholds` in `backend/network/faults/detection.py`, so a generated `HIGH_LATENCY` medium scenario always has latency in `[200, 500)` ms, a critical CPU scenario always has CPU `>= 90%`, and so on. Generation also enforces realistic relationships such as `consecutive_failures <= 2` for non-unreachable faults and `100%` packet loss for unreachable devices.

The 30 handwritten seeds add coverage and phrasing that the generators do not produce. A further 20-example out-of-distribution set lives in `llm/data/ood_test.jsonl`; it contains device types the generators do not model (PLC, satellite modem, hub, hypervisor, UPS, storage controller, optical amplifier, SDN controller, IoT gateway, virtual router). It is **not** used for training or by the default evaluation script; it is a manual robustness check.

### 2.2 Target generation

`build_dataset.py` converts each scenario into an instruction-tuning example:

- `instruction`: the fixed network-operations instruction.
- `input`: a structured block with device, fault type, severity, metrics, consecutive ICMP failures where relevant, and duration.
- `output`: the target explanation with exactly three labelled sections.

Target text is generated from deterministic template banks, not by a larger teacher model. The builders select:

- explanation templates by fault type, severity band, and duration;
- causes tailored to the device type (router, switch, server, access point, firewall);
- actions by severity and fault pattern;
- per-slot alternative action banks for medium latency and packet-loss cases to reduce verbatim repetition;
- conditional notes for simultaneous metrics (for example CPU pressure alongside memory pressure) and for very short versus sustained faults.

Example input:

```text
Device: core-router-01 (router)
Fault type: HIGH_LATENCY
Severity: high
Latency: 913.42 ms
Packet loss: 1.3%
Fault duration: 26 minutes
```

Example target structure:

```text
Explanation:
Latency has risen to 913.42 ms, well above the high-severity threshold of 500 ms. ...

Likely causes:
1. Severe WAN link congestion or upstream provider issue.
2. ...

Recommended actions:
1. Immediately check interface utilisation -- look for a bandwidth spike or microbursting.
2. ...
```

Because the targets are written by the same project that wrote the rules, the model is learning a **stylised analyst voice over synthetic incidents**, not a corpus of real operator reports. This is the most important dataset limitation and is discussed again in Section 8.

### 2.3 Splits

`build_dataset.py` performs a stratified split by fault type using `SPLIT_SEED = 42` and an 80/10/10 target ratio:

| Split | File | Rows |
|---|---|---:|
| Train | `llm/data/train.jsonl` | 664 |
| Validation | `llm/data/val.jsonl` | 85 |
| Test | `llm/data/test.jsonl` | 81 |
| Total | `llm/data/dataset.jsonl` | 830 |

The split is stratified per fault pattern, and `llm/scripts/validate_dataset.py` checks field presence, section headers, duplicate inputs, cross-split contamination, severity/threshold consistency, pluralisation, and over-used sentences.

## 3. Model choice and why

The base model is **`Qwen/Qwen2.5-1.5B-Instruct`**.

| Consideration | Why this model |
|---|---|
| Size | 1.5B parameters is small enough for a free Colab T4 (16 GB) with a 4-bit base plus LoRA. |
| Instruction tuning | It is already chat/instruction-tuned, so the chat template and assistant role are well defined. |
| Structured output | It reliably follows a three-section output format after short supervised fine-tuning. |
| Local inference | The merged/adapted model can run on the application host without a hosted API, keeping fault data local. |
| Swappability | `BASE_MODEL` is configurable in the training script, and the backend base model is configurable via `LLM_BASE_MODEL`. |

The adapter stores only the LoRA deltas, which keeps the trained artifact small relative to the base model. The backend loads the base weights once and applies the adapter on top.

## 4. LoRA / QLoRA configuration

Training uses QLoRA: the base model is loaded in 4-bit NF4 and the LoRA adapters are trained on top.

| Setting | Value |
|---|---|
| Quantisation | 4-bit NF4 (`load_in_4bit=True`) |
| Double quantisation | Enabled |
| Compute dtype | `bfloat16` |
| LoRA rank `r` | 16 |
| LoRA `alpha` | 32 (`alpha/r = 2`) |
| LoRA dropout | 0.05 |
| Target modules | `all-linear` |
| Bias | `none` |
| Task type | `CAUSAL_LM` |

`target_modules="all-linear"` adapts the attention projections (`q_proj`, `k_proj`, `v_proj`, `o_proj`) and the MLP projections (`gate_proj`, `up_proj`, `down_proj`) rather than attention-only modules. This gives more capacity at the same rank, at the cost of a slightly larger adapter.

The corresponding code is in `llm/train_lora.py` (`make_bnb_config()` and `make_lora_config()`).

## 5. Training setup

| Setting | Value |
|---|---|
| Method | Supervised fine-tuning with TRL `SFTTrainer` |
| Epochs | 3 |
| Learning rate | `2e-4` |
| LR schedule | Cosine with 5% warm-up |
| Per-device batch size | 2 |
| Gradient accumulation | 8 |
| Effective batch size | 16 |
| Max sequence length | 512 tokens |
| Precision | `fp16` |
| Gradient checkpointing | Enabled |
| Evaluation / checkpointing | Once per epoch |
| Best-checkpoint rule | Lowest validation loss |
| Packing | Disabled |
| Logging | Console only (`report_to="none"`) |

Each example is formatted with the tokenizer's own chat template:

```text
user:      {instruction}\n\n{input}
assistant: {output}
```

`SFTTrainer` receives the formatted `text` column. The script's intent is to learn the assistant answer; whether prompt tokens are explicitly masked depends on the TRL version and the `SFTConfig.completion_only_loss` setting. The committed configuration does not enable answer-only masking explicitly, so describe training as full-sequence language modelling unless you add and verify that option. The trained adapter and tokenizer are saved to `llm/outputs/adapter/`, and a loss curve is written to `llm/results/loss_curve.png`.

`QUANTIZE = True` is the default and requires a CUDA GPU plus `bitsandbytes`. For CPU-only experimentation, edit `QUANTIZE = False` in `train_lora.py` and use `BASE_MODEL=Qwen/Qwen2.5-0.5B-Instruct` if memory is tight. Training on CPU is significantly slower.

## 6. Evaluation method and results

### 6.1 Automated metrics

`llm/evaluate.py` compares two systems on `llm/data/test.jsonl`:

1. the base model alone;
2. the base model with the fine-tuned LoRA adapter merged.

Generation is greedy (`do_sample=False`, `max_new_tokens=512`) to minimise run-to-run variation. For each example the script computes:

- **ROUGE-1**, **ROUGE-2**, **ROUGE-L** F-measure against the reference output, using stemming;
- **BLEU** against the reference via `sacrebleu` with exponential smoothing;
- **Structure pass**: whether the generated text contains `Explanation:`, `Likely causes:`, and `Recommended actions:`.

It saves:

| Artifact | Contents |
|---|---|
| `llm/results/generations.jsonl` | Per-example input, reference, base output, fine-tuned output, per-example scores, structure flags |
| `llm/results/metrics.md` | Two-column comparison table |
| `llm/results/metrics.json` | Averaged machine-readable metrics plus structure pass percentages |

### 6.2 Results

> **Placeholders — replace the bracketed values with the numbers produced by `llm/evaluate.py` on the final adapter.**

| Metric | Base model | Fine-tuned model |
|---|---:|---:|
| ROUGE-1 | `<fill in>` | `<fill in>` |
| ROUGE-2 | `<fill in>` | `<fill in>` |
| ROUGE-L | `<fill in>` | `<fill in>` |
| BLEU | `<fill in>` | `<fill in>` |
| Structure pass | `<fill in>` | `<fill in>` |

Qualitative observations to record after inspecting `generations.jsonl`:

- `<fill in: does the fine-tuned model reliably emit all three sections?>`
- `<fill in: are causes device-appropriate, or generic?>`
- `<fill in: does it repeat the threshold rather than interpret it?>`
- `<fill in: any regressions versus the base model?>`

### 6.3 Human evaluation

`llm/scripts/make_human_eval_sheet.py` samples 20 test examples and writes `llm/results/human_eval_sheet.csv`. The two outputs are shuffled and unlabelled as **A** and **B** so the rater does not know which model produced which. The CSV includes empty 1–5 columns for:

- clarity
- correctness
- usefulness

for each of A and B. Keep the A/B mapping out of the rating sheet until scoring is complete. Because the sample is random and unseeded, a second run may select different examples.

### 6.4 Interpreting the metrics

ROUGE and BLEU compare the generated text to the template-produced reference. They reward lexical overlap, not factual correctness or operational usefulness. A model can score well by reproducing template phrasing while giving a weak diagnosis, and a technically correct answer can score poorly if it is phrased differently. The structure metric only checks labels, not whether the content under them is sound. For these reasons the human ratings are the more meaningful signal, and the automated numbers should be reported as style/format fidelity rather than diagnostic accuracy.

## 7. Integration architecture

### 7.1 Request flow

```text
React fault detail modal
  "Explain this fault"
        │
        ▼
POST /api/faults/<id>/explain/          (admin token required)
        │
        ▼
FaultViewSet.explain
        │
        ▼
llm_service.get_fault_explanation(fault)
        │
        ├── cached on FaultEvent.explanation_cache? ──► return cached JSON
        │
        ├── LLM_ENABLED false / deps missing / load failure / timeout
        │        └── deterministic fallback templates
        │
        └── prompt → lazy-loaded base + LoRA adapter → generate
                 → parse sections → cache on fault → return JSON
```

Response:

```json
{
  "explanation": "…",
  "likely_causes": ["…", "…"],
  "recommended_actions": ["…", "…"],
  "source": "llm"
}
```

`source` is `"llm"` when the adapter produced the result and `"fallback"` when the deterministic templates were used.

### 7.2 Backend service

`backend/network/llm_service.py`:

- `build_prompt(fault)` recreates the training-time instruction and structured input from the `FaultEvent` (device name/type, fault type, severity, duration, description).
- `_load_model()` lazily imports `torch`/`transformers`/`peft`, loads `LLM_BASE_MODEL`, applies the adapter from `LLM_ADAPTER_PATH`, and caches the pair process-wide behind a lock. A failed load is cached as an error so later requests fall back quickly.
- `_generate_llm(prompt)` applies the chat template, generates deterministically, parses the three sections, and rejects output missing any section.
- `explain_fault(fault)` runs generation on a single-worker executor with `LLM_TIMEOUT_SECONDS`; a non-blocking generation lock prevents concurrent generations. Any exception or timeout returns the fallback.
- `get_fault_explanation(fault, refresh=False)` returns `FaultEvent.explanation_cache` when present; otherwise it generates and persists the result with a targeted `update()` so normal fault updates are not contended. `?refresh=true` bypasses the cache.
- `_fallback_result(fault)` has deterministic explanations, causes, and actions for every `FaultEvent.FaultType`.

The endpoint is `@action(detail=True, methods=['post'])` on `FaultViewSet`, which already requires an authenticated staff administrator (`IsAdminUser`). It is deliberately *not* called from Celery monitoring tasks or fault detection.

### 7.3 Caching

`FaultEvent.explanation_cache` (`JSONField`, nullable) and migration `backend/network/migrations/0010_faultevent_explanation_cache.py` store the last result. The field is not exposed by `FaultSerializer`, so existing fault API contracts are unchanged. Cache hits avoid reloading or invoking the model.

### 7.4 Configuration

| Variable | Default | Purpose |
|---|---|---|
| `LLM_ENABLED` | `False` | Attempt local generation; `False` forces the fallback path |
| `LLM_BASE_MODEL` | `Qwen/Qwen2.5-1.5B-Instruct` | Hugging Face id or local base-model path |
| `LLM_ADAPTER_PATH` | `<repo>/llm/outputs/adapter` | LoRA adapter directory; relative paths resolve from the repository root |
| `LLM_MAX_NEW_TOKENS` | `512` | Generation budget |
| `LLM_TIMEOUT_SECONDS` | `30` | Deadline before falling back |

These are documented in `backend/.env.example` and parsed in `backend/backend/settings.py`.

### 7.5 Frontend

`frontend/src/pages/FaultsPage.tsx` renders an “Explain this fault” button in the fault detail modal. It calls the existing API client through `frontend/src/faults/service.ts` (`POST /faults/<id>/explain/`) and displays:

- a loading state while the request runs;
- a card with Explanation, Likely causes, and Recommended actions;
- a badge showing “Fine-tuned model” (`source: "llm"`) or “Fallback template” (`source: "fallback"`);
- an inline error message if the request fails.

Types live in `frontend/src/faults/types.ts`. The raw model is never called from the browser.

## 8. Limitations and ethical notes

### 8.1 Data and evaluation

- **The dataset is overwhelmingly synthetic.** Targets are generated from the project's own templates, so the model learns the template authors' assumptions and phrasing, not ground truth from real incidents.
- **References are not independent.** ROUGE/BLEU compare the model to the same synthetic style. High scores mean “sounds like the generator”, not “is correct”.
- **Coverage is narrow.** Training covers five device types and nine fault patterns. The out-of-distribution file shows device classes the model has never seen; accuracy there should not be assumed.
- **Combined faults are limited** to the combinations the generator emits. The backend can also produce HTTP-related fault types that are not in the training data; those rely on the fallback templates.
- **Metrics do not measure diagnosis.** There is no labelled ground truth for “correct root cause”, so correctness is assessed only through the human rating sheet, and even that is a small unseeded sample.

### 8.2 Operational and safety

- The explanation is **advisory**, not an authoritative diagnosis. It can produce plausible but incorrect causes, or recommend commands that do not exist on a particular vendor/platform.
- Do not connect the model to automated remediation. Any suggested action should be reviewed by a qualified network engineer before it is applied.
- The model is **not** a substitute for logs, packet captures, vendor documentation, or change history.
- Latency and packet-loss data reach the prompt only through the fault description, because `FaultEvent` stores a short summary rather than a full metric snapshot. The model therefore has less context than a human investigator.
- Generation can be slow on CPU and may time out; the fallback is intentional, not a failure of the application.
- The deterministic fallback is maintained separately from the model. If fault types or thresholds change, both the templates and the training data need review.

### 8.3 Privacy and ethics

- Generation runs locally when enabled; no hosted LLM API is called. Fault records, device names, and descriptions remain in the application database.
- Cached explanations are stored in `FaultEvent.explanation_cache`, so infrastructure details embedded in the prompt may be persisted in the database. Treat the database with the same care as other monitoring data.
- The synthetic templates encode assumptions about vendor behaviour (for example, BGP table growth on routers or session tables on firewalls). They should not be presented as vendor-specific truths.
- When reporting results, state clearly that the dataset is synthetic and that the evaluation is a format/style comparison plus a small human review. Do not claim production diagnostic accuracy.
- Check the license of the chosen base model and of any redistributed adapter weights before publishing or deploying them.
- Human oversight is required: the feature should inform an administrator, not replace one.

## 9. Reproducing everything

### 9.1 Prerequisites

- Python 3.10+ (the LLM scripts use modern type syntax).
- An NVIDIA GPU with CUDA for QLoRA training (a T4 is sufficient). CPU-only training works with `QUANTIZE = False`.
- Node.js/npm for the frontend.
- Redis and the backend dependencies for the integrated application.

Install the LLM dependencies separately from the backend:

```bash
pip install -r llm/requirements-llm.txt
```

### 9.2 Rebuild the dataset

From the repository root:

```bash
python llm/scripts/generate_scenarios.py
PYTHONHASHSEED=0 python llm/scripts/build_dataset.py
python llm/scripts/validate_dataset.py
```

`generate_scenarios.py` is seeded and reproduces the scenarios. `build_dataset.py` selects among template variants using Python's `hash()`, so set `PYTHONHASHSEED=0` if you need byte-identical regeneration; otherwise the committed `llm/data/*.jsonl` files are the reference artifacts.

### 9.3 Train the adapter

```bash
python llm/train_lora.py
```

or with a different base:

```bash
BASE_MODEL=Qwen/Qwen2.5-1.5B-Instruct python llm/train_lora.py
```

Artifacts:

```text
llm/outputs/adapter/       # LoRA adapter + tokenizer
llm/results/loss_curve.png # training / validation loss per epoch
```

### 9.4 Evaluate

```bash
python llm/evaluate.py
python llm/scripts/make_human_eval_sheet.py
```

Outputs:

```text
llm/results/generations.jsonl
llm/results/metrics.md
llm/results/metrics.json
llm/results/human_eval_sheet.csv
```

Fill the results table in Section 6.2 from `llm/results/metrics.md`, and record human ratings from the CSV.

### 9.5 Run the integrated application

Backend:

```bash
cd backend
cp .env.example .env
# Set DJANGO_SECRET_KEY, and optionally:
#   LLM_ENABLED=True
#   LLM_BASE_MODEL=Qwen/Qwen2.5-1.5B-Instruct
#   LLM_ADAPTER_PATH=llm/outputs/adapter
python manage.py migrate
python manage.py runserver
```

The model loads lazily on the first explain request. Until then, startup is unaffected. If `LLM_ENABLED=False` (the default), every explain request returns the deterministic fallback.

Frontend:

```bash
cd frontend
npm install
npm run dev
```

Open **Faults**, select a fault, and use **Explain this fault** in the detail modal. The badge indicates whether the result came from the adapter or the fallback.

### 9.6 Verify

```bash
cd backend
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py test

cd ../frontend
npm run lint
npm run build
```

The backend test suite includes `network.test_fault_explainer`, which mocks generation so it never loads model weights.

## 10. File map

| Path | Role |
|---|---|
| `llm/scripts/generate_scenarios.py` | Seeded synthetic scenario generator aligned to detection thresholds |
| `llm/scripts/build_dataset.py` | Scenario → instruction/input/output conversion and stratified split |
| `llm/scripts/validate_dataset.py` | Dataset and split integrity checks |
| `llm/train_lora.py` | QLoRA/SFT training |
| `llm/evaluate.py` | Base vs adapter ROUGE/BLEU/structure evaluation |
| `llm/scripts/make_human_eval_sheet.py` | Blinded 20-example human rating CSV |
| `llm/data/` | Scenarios, seeds, splits, and out-of-distribution examples |
| `llm/outputs/adapter/` | Trained LoRA adapter and tokenizer |
| `llm/results/` | Loss curve, generations, metrics, human-eval sheet |
| `backend/network/llm_service.py` | Prompt building, lazy loading, generation, parsing, fallback, caching |
| `backend/network/views.py` | `POST /api/faults/<id>/explain/` action |
| `backend/network/models.py` | `FaultEvent.explanation_cache` |
| `backend/network/migrations/0010_faultevent_explanation_cache.py` | Cache field migration |
| `backend/network/test_fault_explainer.py` | Endpoint, fallback, caching, prompt tests |
| `frontend/src/faults/service.ts` | API client method for the explain endpoint |
| `frontend/src/faults/types.ts` | Explanation request/response types |
| `frontend/src/pages/FaultsPage.tsx` | Explain button, loading state, result card, source badge |
