"""Optional local LLM explanations for detected faults.

The service is intentionally best-effort: when the model, its optional
dependencies, or the LoRA adapter are unavailable, callers receive a
deterministic template explanation instead. This keeps the fault API working
on deployments that do not ship a GPU or the LLM stack.

Model configuration is read from Django settings, which in turn reads these
environment variables:

    LLM_ENABLED          -- "true" to attempt local generation (default false)
    LLM_BASE_MODEL       -- Hugging Face model id or local base-model path
    LLM_ADAPTER_PATH     -- LoRA adapter directory
    LLM_MAX_NEW_TOKENS   -- generation budget (default 512)
    LLM_TIMEOUT_SECONDS  -- deadline for one generation before falling back
"""

from __future__ import annotations

import logging
import os
import re
import threading
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from pathlib import Path
from typing import Any

from django.conf import settings
from django.utils import timezone

from .models import FaultEvent

logger = logging.getLogger(__name__)

DEFAULT_BASE_MODEL = 'Qwen/Qwen2.5-1.5B-Instruct'
DEFAULT_MAX_NEW_TOKENS = 512
DEFAULT_TIMEOUT_SECONDS = 30.0

INSTRUCTION = (
    "You are a network operations assistant. Given a fault event detected on a "
    "network device, produce a structured explanation with three clearly labelled "
    "sections: 'Explanation' (what is happening and why it matters, referencing the "
    "specific metrics), 'Likely causes' (ranked list of probable root causes for this "
    "device type and fault pattern), and 'Recommended actions' (concrete remediation "
    "steps in priority order)."
)

_SECTION_PATTERN = re.compile(
    r'(?i)(?:^|\n)\s*(?:#+\s*)?(?:\*\*)?'
    r'(explanation|likely causes|recommended actions)'
    r'(?:\*\*)?\s*:\s*'
)
_LIST_ITEM_PATTERN = re.compile(r'^\s*(?:\d+[.)]|[-*\u2022])\s+')

_model_lock = threading.Lock()
_generation_lock = threading.Lock()
_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='fault-explainer')
_model: Any = None
_tokenizer: Any = None
_load_error: str | None = None


class LLMUnavailable(RuntimeError):
    """Raised when local generation cannot be used."""


def _config(name: str, default: Any) -> Any:
    value = getattr(settings, name, None)
    if value is None:
        return os.getenv(name, default)
    return value


def _llm_enabled() -> bool:
    value = _config('LLM_ENABLED', False)
    if isinstance(value, bool):
        return value
    return str(value).lower() in {'1', 'true', 'yes', 'on'}


def _adapter_path() -> str:
    default = str(Path(settings.BASE_DIR).parent / 'llm' / 'outputs' / 'adapter')
    raw = str(_config('LLM_ADAPTER_PATH', default) or default).strip()
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = Path(settings.BASE_DIR).parent / path
    return str(path)


def _max_new_tokens() -> int:
    try:
        return max(1, int(_config('LLM_MAX_NEW_TOKENS', DEFAULT_MAX_NEW_TOKENS)))
    except (TypeError, ValueError):
        return DEFAULT_MAX_NEW_TOKENS


def _timeout_seconds() -> float:
    try:
        return max(1.0, float(_config('LLM_TIMEOUT_SECONDS', DEFAULT_TIMEOUT_SECONDS)))
    except (TypeError, ValueError):
        return DEFAULT_TIMEOUT_SECONDS


def _fault_duration_minutes(fault: FaultEvent) -> int:
    end = fault.resolved_at or timezone.now()
    try:
        delta = end - fault.detected_at
    except TypeError:
        return 0
    return max(0, int(delta.total_seconds() // 60))


def build_prompt(fault: FaultEvent) -> str:
    """Build the instruction-style prompt used during fine-tuning."""
    device = fault.device
    lines = [
        f'Device: {device.name} ({device.device_type})',
        f'Fault type: {fault.fault_type}',
        f'Severity: {fault.severity}',
        f'Fault duration: {_fault_duration_minutes(fault)} minutes',
    ]
    description = (fault.description or '').strip()
    if description:
        lines.append(f'Details: {description}')
    return f'{INSTRUCTION}\n\n' + '\n'.join(lines)


def _split_items(text: str) -> list[str]:
    """Turn a numbered or bulleted block into a list of individual items."""
    items: list[str] = []
    current: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            if current:
                items.append(' '.join(current))
                current = []
            continue
        if _LIST_ITEM_PATTERN.match(line):
            if current:
                items.append(' '.join(current))
            current = [_LIST_ITEM_PATTERN.sub('', line).strip()]
        elif current:
            current.append(line)
        else:
            current = [line]
    if current:
        items.append(' '.join(current))
    return [item for item in items if item]


def _parse_sections(text: str) -> dict[str, Any]:
    """Split generated text into the three labelled sections."""
    matches = list(_SECTION_PATTERN.finditer(text))
    if not matches:
        return {
            'explanation': text.strip(),
            'likely_causes': [],
            'recommended_actions': [],
        }

    sections: dict[str, str] = {}
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        sections[match.group(1).lower()] = text[start:end].strip()

    return {
        'explanation': sections.get('explanation', '').strip() or text.strip(),
        'likely_causes': _split_items(sections.get('likely causes', '')),
        'recommended_actions': _split_items(sections.get('recommended actions', '')),
    }


_FALLBACK_TEMPLATES: dict[str, dict[str, Any]] = {
    FaultEvent.FaultType.DEVICE_UNREACHABLE: {
        'explanation': (
            'The device is not responding to ICMP monitoring, so it is currently '
            'unreachable from the network. Connectivity to any service hosted on the '
            'device cannot be confirmed until it responds again.'
        ),
        'likely_causes': [
            'Power or hardware failure on the device.',
            'Uplink or interface failure isolating the device from the monitoring path.',
            'Management address or routing change making the device unreachable.',
            'Firewall or ACL change blocking ICMP from the monitoring host.',
            'Device reboot, crash, or firmware upgrade in progress.',
        ],
        'recommended_actions': [
            'Verify power, link state, and console or out-of-band access.',
            'Check upstream switch and router logs for interface flaps.',
            'Confirm the management path and route to the device.',
            'Review recent ACL or firewall changes affecting ICMP.',
            'Dispatch on-site support if the device remains unreachable.',
        ],
    },
    FaultEvent.FaultType.HIGH_LATENCY: {
        'explanation': (
            'Round-trip latency to the device exceeds the configured threshold. '
            'Sustained latency at this level degrades interactive sessions and slows '
            'time-sensitive protocols.'
        ),
        'likely_causes': [
            'WAN or uplink congestion during peak traffic.',
            'Device CPU or control-plane overload delaying packet processing.',
            'QoS misconfiguration deprioritising management traffic.',
            'Routing change moving traffic onto a longer path.',
            'Physical layer errors causing retransmissions.',
        ],
        'recommended_actions': [
            'Check uplink utilisation and queue drops along the path.',
            'Inspect device CPU and process load.',
            'Review QoS policy for management and ICMP traffic.',
            'Run a traceroute to isolate the slow hop.',
            'Monitor for 15 minutes and escalate if latency keeps rising.',
        ],
    },
    FaultEvent.FaultType.HIGH_PACKET_LOSS: {
        'explanation': (
            'Packet loss to the device exceeds the configured threshold. At this '
            'loss rate TCP sessions stall and real-time traffic becomes unreliable.'
        ),
        'likely_causes': [
            'Congestion causing queue tail-drop on the path.',
            'Physical layer errors such as a faulty cable, SFP, or duplex mismatch.',
            'Interface or hardware fault on the device.',
            'QoS or ACL policy discarding probe traffic.',
            'Upstream provider or path impairment.',
        ],
        'recommended_actions': [
            'Check interface error and discard counters on each hop.',
            'Inspect queue drops and QoS policy on the uplink.',
            'Test loss from a second monitoring host to isolate the path.',
            'Reseat or replace cables and SFPs if CRC errors are present.',
            'Escalate if loss remains above threshold after these checks.',
        ],
    },
    FaultEvent.FaultType.HIGH_CPU_USAGE: {
        'explanation': (
            'CPU utilisation on the device exceeds the configured threshold. '
            'Sustained high CPU can delay routing protocol keepalives and management '
            'access.'
        ),
        'likely_causes': [
            'Runaway process or traffic pattern consuming CPU.',
            'Routing protocol recalculation after a topology change.',
            'Excessive SNMP, NetFlow, or logging activity.',
            'Software or configuration change increasing baseline load.',
            'Hardware or thermal issue throttling the CPU.',
        ],
        'recommended_actions': [
            'Identify the top CPU-consuming processes.',
            'Check for routing adjacency flaps or recent topology changes.',
            'Reduce non-essential polling and logging.',
            'Review recent configuration or software changes.',
            'Plan failover or a maintenance window if CPU stays elevated.',
        ],
    },
    FaultEvent.FaultType.HIGH_MEMORY_USAGE: {
        'explanation': (
            'Memory utilisation on the device exceeds the configured threshold. Low '
            'free memory risks process crashes, session loss, and an unplanned reload.'
        ),
        'likely_causes': [
            'Memory leak in a long-running process.',
            'Growing routing, session, or connection-tracking tables.',
            'Caches or buffers not being reclaimed.',
            'Recent software update increasing the baseline footprint.',
            'High connection or client count.',
        ],
        'recommended_actions': [
            'Identify the largest memory consumers.',
            'Check uptime and trend for a slow leak.',
            'Clear reclaimable caches if the platform supports it.',
            'Review table sizes against platform limits.',
            'Plan a controlled reload or failover before memory is exhausted.',
        ],
    },
    FaultEvent.FaultType.INTERFACE_FAILURE: {
        'explanation': (
            'An interface on the device has failed or is down. Traffic using that '
            'interface is disrupted until it recovers or fails over.'
        ),
        'likely_causes': [
            'Cable, SFP, or physical port failure.',
            'Configuration error bringing the interface down.',
            'Upstream device or peer port failure.',
            'Hardware fault on the line card.',
            'Power or environmental issue affecting the port.',
        ],
        'recommended_actions': [
            'Check interface status and error counters.',
            'Verify cabling and transceiver seating.',
            'Review recent interface configuration changes.',
            'Test with a spare port or cable if available.',
            'Escalate to hardware support if the port remains down.',
        ],
    },
    FaultEvent.FaultType.CONNECTIVITY_FAILURE: {
        'explanation': (
            'Connectivity to the device or its network path has failed. The device '
            'may still be powered but unreachable through normal routing.'
        ),
        'likely_causes': [
            'Routing or switching loop or black hole.',
            'Upstream link or provider outage.',
            'VLAN or interface misconfiguration.',
            'Firewall or ACL change blocking traffic.',
            'Device or peer reboot in progress.',
        ],
        'recommended_actions': [
            'Trace the path to the device and check each hop.',
            'Verify routing and VLAN configuration.',
            'Check upstream link and provider status.',
            'Review recent firewall or ACL changes.',
            'Fail over to a redundant path if available.',
        ],
    },
    FaultEvent.FaultType.HTTP_ENDPOINT_FAILURE: {
        'explanation': (
            'The monitored HTTP endpoint did not return an acceptable response. The '
            'service may be down or returning errors.'
        ),
        'likely_causes': [
            'Application or web server not running.',
            'Upstream dependency failure causing error responses.',
            'TLS certificate or DNS problem.',
            'Load balancer or proxy misconfiguration.',
            'Firewall or ACL blocking the probe.',
        ],
        'recommended_actions': [
            'Check the application and web server status.',
            'Review recent deployments or configuration changes.',
            'Verify DNS, TLS certificate, and proxy settings.',
            'Test the endpoint from the monitoring host.',
            'Escalate to the application owner if errors persist.',
        ],
    },
    FaultEvent.FaultType.HTTP_SLOW_RESPONSE: {
        'explanation': (
            'The monitored HTTP endpoint is responding more slowly than the '
            'configured threshold. Slow responses degrade user experience and can '
            'precede timeouts.'
        ),
        'likely_causes': [
            'Application or database contention.',
            'Insufficient server CPU or memory.',
            'Network latency between the probe and the endpoint.',
            'Large response payload or inefficient query.',
            'Proxy or load balancer queueing.',
        ],
        'recommended_actions': [
            'Check server CPU, memory, and database health.',
            'Review application logs for slow queries.',
            'Measure latency from another host to isolate the network.',
            'Inspect proxy and load balancer metrics.',
            'Escalate if response time keeps increasing.',
        ],
    },
}

_DEFAULT_FALLBACK = {
    'explanation': (
        'A fault has been detected on the device. The condition is reported by '
        'deterministic monitoring and should be reviewed by an administrator.'
    ),
    'likely_causes': [
        'Underlying network or device condition matching the reported fault type.',
        'Recent configuration or topology change.',
        'Hardware or software fault on the device.',
        'Traffic or resource level outside the expected baseline.',
    ],
    'recommended_actions': [
        'Review the fault details and recent monitoring records.',
        'Check device health and interface counters.',
        'Review recent configuration changes.',
        'Escalate if the condition persists or worsens.',
    ],
}


def _fallback_result(fault: FaultEvent) -> dict[str, Any]:
    template = _FALLBACK_TEMPLATES.get(fault.fault_type, _DEFAULT_FALLBACK)
    explanation = (
        f"{template['explanation']} This is a {fault.severity}-severity fault on "
        f'{fault.device.name} ({fault.device.device_type}).'
    )
    description = (fault.description or '').strip()
    if description:
        explanation = f'{explanation} {description}'
    return {
        'explanation': explanation,
        'likely_causes': list(template['likely_causes']),
        'recommended_actions': list(template['recommended_actions']),
        'source': 'fallback',
    }


def _load_model() -> tuple[Any, Any]:
    """Load the base model and LoRA adapter once and cache the result."""
    global _model, _tokenizer, _load_error

    if _model is not None:
        return _model, _tokenizer

    with _model_lock:
        if _model is not None:
            return _model, _tokenizer
        if _load_error is not None:
            raise LLMUnavailable(_load_error)

        try:
            import peft  # noqa: F401
            import torch  # noqa: F401
            from peft import PeftModel
            from transformers import AutoModelForCausalLM, AutoTokenizer
        except ImportError as exc:
            _load_error = 'LLM dependencies are not installed.'
            logger.warning(
                '%s Install llm/requirements-llm.txt before enabling LLM_ENABLED.', _load_error
            )
            raise LLMUnavailable(_load_error) from exc

        base_model = str(_config('LLM_BASE_MODEL', DEFAULT_BASE_MODEL) or DEFAULT_BASE_MODEL)
        adapter_path = _adapter_path()
        try:
            tokenizer = AutoTokenizer.from_pretrained(base_model, trust_remote_code=True)
            if tokenizer.pad_token is None:
                tokenizer.pad_token = tokenizer.eos_token

            dtype = torch.bfloat16 if torch.cuda.is_available() else torch.float32
            model = AutoModelForCausalLM.from_pretrained(
                base_model,
                trust_remote_code=True,
                torch_dtype=dtype,
                device_map='auto',
            )
            model = PeftModel.from_pretrained(model, adapter_path)
            model.eval()
            if hasattr(model, 'config'):
                model.config.use_cache = True
        except Exception as exc:
            _load_error = 'LLM model could not be loaded.'
            logger.exception(
                'Failed to load the fault-explainer model %s with adapter %s',
                base_model,
                adapter_path,
            )
            raise LLMUnavailable(_load_error) from exc

        _model, _tokenizer = model, tokenizer
        logger.info('Loaded fault-explainer model %s with adapter %s', base_model, adapter_path)
        return _model, _tokenizer


def _generate_llm(prompt: str) -> dict[str, Any]:
    """Run one generation and return the parsed structured result."""
    if not _generation_lock.acquire(blocking=False):
        raise LLMUnavailable('Another explanation is already being generated.')

    try:
        import torch

        model, tokenizer = _load_model()
        messages = [{'role': 'user', 'content': prompt}]
        chat_prompt = tokenizer.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True
        )
        inputs = tokenizer(chat_prompt, return_tensors='pt')

        device = getattr(model, 'device', None)
        if device is None:
            device = next(model.parameters()).device
        inputs = inputs.to(device)

        with torch.no_grad():
            outputs = model.generate(
                **inputs,
                max_new_tokens=_max_new_tokens(),
                do_sample=False,
                pad_token_id=tokenizer.eos_token_id,
            )

        prompt_length = inputs['input_ids'].shape[1]
        text = tokenizer.decode(outputs[0][prompt_length:], skip_special_tokens=True).strip()
        if not text:
            raise LLMUnavailable('The model returned an empty explanation.')

        parsed = _parse_sections(text)
        if not all(
            (
                parsed['explanation'],
                parsed['likely_causes'],
                parsed['recommended_actions'],
            )
        ):
            raise LLMUnavailable('The model output did not contain all required sections.')
        return {**parsed, 'source': 'llm'}
    finally:
        _generation_lock.release()


def explain_fault(fault: FaultEvent) -> dict[str, Any]:
    """Explain one fault, falling back to a deterministic template on any failure."""
    if not _llm_enabled():
        return _fallback_result(fault)

    if _generation_lock.locked():
        logger.info('Fault explainer is busy; using fallback for fault %s.', fault.id)
        return _fallback_result(fault)

    prompt = build_prompt(fault)
    future = _executor.submit(_generate_llm, prompt)
    try:
        return future.result(timeout=_timeout_seconds())
    except FutureTimeoutError:
        future.cancel()
        logger.warning('Fault explainer timed out for fault %s; using fallback.', fault.id)
        return _fallback_result(fault)
    except Exception:
        logger.exception('Fault explainer failed for fault %s; using fallback.', fault.id)
        return _fallback_result(fault)


def get_fault_explanation(fault: FaultEvent, *, refresh: bool = False) -> dict[str, Any]:
    """Return a cached explanation or generate and cache a new one."""
    cached = fault.explanation_cache
    if not refresh and isinstance(cached, dict) and cached:
        return cached

    result = explain_fault(fault)
    FaultEvent.objects.filter(pk=fault.pk).update(explanation_cache=result)
    fault.explanation_cache = result
    return result
