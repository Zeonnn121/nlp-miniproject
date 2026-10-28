interface Concept {
  key: string
  title: string
  badge: string
  definition: string
  example: { input: string; step: string; output: string }
  where: { file: string; purpose: string }[]
}

const snapshot = [
  { label: 'Base model', value: 'Qwen2.5-1.5B-Instruct', detail: '4-bit NF4 with double quantization (bitsandbytes)' },
  { label: 'Adaptation', value: 'QLoRA adapter', detail: 'rank r = 16, alpha = 32, dropout 0.05 over all linear projections' },
  { label: 'Dataset', value: '830 records', detail: '664 train / 85 validation / 81 test, plus 20 out-of-domain stress cases' },
  { label: 'Output contract', value: '3 fixed sections', detail: 'Explanation · Likely causes · Recommended actions' },
]

const pipeline = [
  { step: '1', title: 'Telemetry', detail: 'ICMP latency, SNMP CPU/RAM, and HTTP checks are written as measurement records by the Celery probe workers.' },
  { step: '2', title: 'Deterministic detection', detail: 'Threshold rules promote a metric violation into a FaultEvent with type, severity, and duration. The LLM never decides whether a fault exists.' },
  { step: '3', title: 'Prompt construction', detail: 'build_prompt() renders the fault as a plain-text block: device, fault type, severity, duration, and any operator-facing details.' },
  { step: '4', title: 'Tokenization', detail: "Qwen's chat template wraps the prompt and the Byte-Pair Encoding tokenizer turns it into subword token ids." },
  { step: '5', title: 'Generation & parsing', detail: 'The adapter generates the triage note; regex section parsing splits it into three sections and falls back to a template if the model is unavailable.' },
]

const concepts: Concept[] = [
  {
    key: 'regex',
    title: 'Regular Expressions',
    badge: 'Python re module',
    definition:
      'Patterns that describe the shape of text. They validate input, pull measurements out of unstructured log lines, and reshape generated text into the sections the dashboard can render.',
    example: {
      input: 'Fault duration: 25 minutes. Consecutive ICMP failures: 4',
      step: 're.search(r"Fault duration:\\s*(\\d+)\\s*minute", text)',
      output: '25',
    },
    where: [
      { file: 'llm/scripts/validate_dataset.py', purpose: 're.search reads "Fault duration" and "Consecutive ICMP failures" out of every training record to check that severity claims match the metrics.' },
      { file: 'backend/network/llm_service.py', purpose: '_SECTION_PATTERN and _LIST_ITEM_PATTERN split model output into Explanation / Likely causes / Recommended actions and rebuild numbered lists.' },
      { file: 'llm/evaluate.py', purpose: 're.sub strips <|channel|> control tokens from generated text before structural and BLEU/ROUGE scoring.' },
    ],
  },
  {
    key: 'tokenization',
    title: 'Tokenization',
    badge: 'Sentence tokens + BPE',
    definition:
      'Splitting text into the units a later stage can consume. The project uses rule-based sentence and word tokenization for analysis, and the Qwen tokenizer’s subword Byte-Pair Encoding for the model itself.',
    example: {
      input: 'High CPU utilization detected on edge-router-01.',
      step: 'sentence split → 1 sentence · word tokens → High | CPU | utilization | detected · BPE → subword ids',
      output: 'chat template: <|im_start|>user … <|im_end|> → token ids',
    },
    where: [
      { file: 'llm/scripts/validate_dataset.py', purpose: 're.split(r"(?<=[.!?])\\s+", out) sentence-tokenizes every output so repeated boilerplate sentences can be counted across splits.' },
      { file: 'llm/train_lora.py', purpose: 'AutoTokenizer.apply_chat_template turns each instruction/input/output record into the exact token sequence the model is trained on.' },
      { file: 'backend/network/llm_service.py', purpose: 'The same tokenizer runs at inference: tokenizer(chat_prompt, return_tensors="pt"), with only the newly generated tokens decoded after prompt_length.' },
    ],
  },
  {
    key: 'stemming',
    title: 'Stemming',
    badge: 'Porter Stemmer',
    definition:
      'Heuristic suffix stripping that collapses inflected forms onto one root, so vocabulary counts are not split across tense and plurality. Porter is intentionally crude — the root it returns is not always a dictionary word.',
    example: {
      input: 'saturates, saturated, saturating',
      step: 'PorterStemmer().stem(term)',
      output: 'satur',
    },
    where: [
      { file: 'llm/scripts/validate_dataset.py', purpose: 'stem_tokens() stems every content word in all outputs; collect_root_frequencies() prints the top 15 roots (caus ← cause / caused / causes) so an over-used idea is visible regardless of tense.' },
    ],
  },
  {
    key: 'lemmatization',
    title: 'Lemmatization',
    badge: 'WordNet Lemmatizer',
    definition:
      'Dictionary-driven normalization. Each word is mapped to a real dictionary headword using WordNet — first as a verb, then as a noun — so the result is a valid word rather than a truncated root.',
    example: {
      input: 'drops, dropped, dropping, congested',
      step: 'lemmatize(token, pos=VERB) → lemmatize(…, pos=NOUN)',
      output: 'drop, drop, drop, congest',
    },
    where: [
      { file: 'llm/scripts/validate_dataset.py', purpose: 'lemma_tokens() normalizes every output word; check_cross_split_lemmas() compares lemma signatures of sentences to catch near-duplicates that survive in two splits under different surface wording.' },
    ],
  },
]

function CodeBlock({ children }: { children: string }) {
  return (
    <pre className="mt-3 overflow-x-auto rounded-xl border border-[#1e2a45] p-4 text-xs leading-relaxed text-[#c9d4e8]" style={{ background: '#030407' }}>
      <code>{children}</code>
    </pre>
  )
}

function ConceptCard({ concept }: { concept: Concept }) {
  return <article className="rounded-2xl border border-[#1e2a45] p-5 shadow-sm" style={{ background: '#0a0d16' }}>
    <div className="flex flex-wrap items-center justify-between gap-2">
      <h3 className="text-lg font-semibold text-[#f0f4ff]">{concept.title}</h3>
      <span className="rounded-full border border-[#1e2a45] px-2.5 py-1 text-[11px] font-semibold text-[#8b9dc0]">{concept.badge}</span>
    </div>
    <p className="mt-2 text-sm leading-relaxed text-[#8b9dc0]">{concept.definition}</p>

    <div className="mt-4 rounded-xl border border-[#1e2a45] p-4" style={{ background: '#0f1424' }}>
      <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-[#4a5a80]">Project example</p>
      <p className="mt-2 font-mono text-xs text-[#c9d4e8]">{concept.example.input}</p>
      <p className="mt-2 font-mono text-xs text-[#4a5a80]">{concept.example.step}</p>
      <p className="mt-2 text-sm font-semibold text-[#d4ff24]">→ {concept.example.output}</p>
    </div>

    <div className="mt-4">
      <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-[#4a5a80]">Where it is implemented</p>
      <ul className="mt-2 space-y-3">
        {concept.where.map((entry) => <li key={entry.file}>
          <code className="rounded-md border border-[#1e2a45] px-2 py-1 text-[11px] text-[#d4ff24]" style={{ background: '#030407' }}>{entry.file}</code>
          <p className="mt-1.5 text-sm leading-relaxed text-[#8b9dc0]">{entry.purpose}</p>
        </li>)}
      </ul>
    </div>
  </article>
}

export function LlmPage() {
  return <section className="mx-auto max-w-7xl space-y-6 px-4 py-6 sm:px-6 lg:px-8">
    <div>
      <p className="text-xs font-semibold uppercase tracking-[0.14em] text-[#4a5a80]">Applied NLP</p>
      <h1 className="mt-1 text-2xl font-semibold tracking-tight text-[#f0f4ff]">The triage LLM</h1>
      <p className="mt-2 max-w-3xl text-sm leading-relaxed text-[#8b9dc0]">
        NetWatch pairs a deterministic fault detector with a small, domain-adapted language model. The detector decides <em>that</em> something is wrong; the
        model explains <em>what it means</em> and what to do next. A 1.5B-parameter Qwen model is fine-tuned with QLoRA so it can be served on modest hardware,
        and classical NLP techniques — regex, tokenization, and stemming — do the text handling around it.
      </p>
    </div>

    <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
      {snapshot.map((item) => <div key={item.label} className="rounded-2xl border border-[#1e2a45] p-5 shadow-sm" style={{ background: '#0a0d16' }}>
        <p className="text-xs font-semibold uppercase tracking-wide text-[#4a5a80]">{item.label}</p>
        <p className="mt-2 text-base font-semibold text-[#f0f4ff]">{item.value}</p>
        <p className="mt-1 text-xs leading-relaxed text-[#8b9dc0]">{item.detail}</p>
      </div>)}
    </div>

    <div className="grid gap-4 sm:grid-cols-3">
      <div className="rounded-2xl border border-[#1e2a45] p-5" style={{ background: '#0a0d16' }}><p className="text-xs text-[#4a5a80]">Structural compliance</p><p className="mt-2 text-2xl font-semibold text-[#d4ff24]">100%</p><p className="mt-1 text-xs text-[#8b9dc0]">vs 58% zero-shot baseline</p></div>
      <div className="rounded-2xl border border-[#1e2a45] p-5" style={{ background: '#0a0d16' }}><p className="text-xs text-[#4a5a80]">Training loss</p><p className="mt-2 text-2xl font-semibold text-[#f0f4ff]">1.37 → 0.16</p><p className="mt-1 text-xs text-[#8b9dc0]">3 epochs, validation 0.44 → 0.16</p></div>
      <div className="rounded-2xl border border-[#1e2a45] p-5" style={{ background: '#0a0d16' }}><p className="text-xs text-[#4a5a80]">Text quality</p><p className="mt-2 text-2xl font-semibold text-[#f0f4ff]">3× BLEU / ROUGE-L</p><p className="mt-1 text-xs text-[#8b9dc0]">over the same zero-shot baseline</p></div>
    </div>

    <div className="rounded-2xl border border-[#1e2a45] p-5 shadow-sm" style={{ background: '#0a0d16' }}>
      <h2 className="text-lg font-semibold text-[#f0f4ff]">How a fault becomes an explanation</h2>
      <ol className="mt-4 grid gap-3 lg:grid-cols-5">
        {pipeline.map((item) => <li key={item.step} className="rounded-xl border border-[#1e2a45] p-4" style={{ background: '#0f1424' }}>
          <span className="grid size-7 place-items-center rounded-lg text-xs font-bold text-white" style={{ background: 'linear-gradient(135deg, #1558c9, #0d3fa0)' }}>{item.step}</span>
          <p className="mt-3 text-sm font-semibold text-[#f0f4ff]">{item.title}</p>
          <p className="mt-1 text-xs leading-relaxed text-[#8b9dc0]">{item.detail}</p>
        </li>)}
      </ol>
    </div>

    <div className="grid gap-4 lg:grid-cols-2">
      <div className="rounded-2xl border border-[#1e2a45] p-5" style={{ background: '#0a0d16' }}>
        <h2 className="text-lg font-semibold text-[#f0f4ff]">What the model is given</h2>
        <p className="mt-1 text-sm text-[#8b9dc0]">A held-out validation record, as the prompt block the model sees.</p>
        <CodeBlock>{`Device: fw-perimeter (firewall)
Fault type: HIGH_CPU_USAGE+HIGH_MEMORY_USAGE
Severity: high
Latency: 87.53 ms
Packet loss: 1.96%
CPU usage: 89.75%
Memory usage: 89.07%
Fault duration: 7 minutes`}</CodeBlock>
      </div>
      <div className="rounded-2xl border border-[#1e2a45] p-5" style={{ background: '#0a0d16' }}>
        <h2 className="text-lg font-semibold text-[#f0f4ff]">What the model produces</h2>
        <p className="mt-1 text-sm text-[#8b9dc0]">The same record’s target completion, trimmed.</p>
        <CodeBlock>{`Explanation:
CPU and memory are both above the 80% high-severity threshold
(CPU: 89.75%, memory: 89.07%), persisting for 7 minutes...

Likely causes:
1. A runaway process on the firewall consuming CPU and heap memory.
2. A large routing or session table growth...

Recommended actions:
1. Identify which process is consuming the most CPU and memory.
2. Review uptime -- a device running many weeks may be leaking...`}</CodeBlock>
      </div>
    </div>

    <div>
      <h2 className="text-lg font-semibold text-[#f0f4ff]">NLP concepts used in this project</h2>
      <p className="mt-1 max-w-3xl text-sm text-[#8b9dc0]">Four text-processing techniques carry the pipeline: regex for extraction and parsing, tokenization for both the model and the dataset audits, and stemming plus lemmatization for vocabulary normalization.</p>
    </div>

    <div className="grid gap-4 sm:grid-cols-2">
      {concepts.map((concept) => <ConceptCard key={concept.key} concept={concept} />)}
    </div>

    <div className="rounded-2xl border border-[#1e2a45] p-5 text-sm leading-relaxed text-[#8b9dc0]" style={{ background: '#0a0d16' }}>
      <p className="font-semibold text-[#f0f4ff]">Graceful degradation</p>
      <p className="mt-1">
        Generation is opt-in through <code className="text-[#d4ff24]">LLM_ENABLED</code> with the base model and adapter paths set in the environment. If the model,
        its dependencies, or the adapter cannot be loaded, the fault API still returns a deterministic template explanation instead of failing, so monitoring keeps
        working on deployments without a GPU.
      </p>
    </div>
  </section>
}
