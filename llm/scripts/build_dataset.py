#!/usr/bin/env python3
"""Build instruction-tuning dataset from scenarios and handwritten seed examples with 80/10/10 stratified split."""

import json
import random
from collections import defaultdict
from pathlib import Path

INSTRUCTION = "Analyze the network fault and provide an expert diagnosis, probable root causes, and remediation steps."

EXPLANATION_TEMPLATES = {
    'DEVICE_UNREACHABLE': [
        "Device {name} ({dtype}) has been completely unreachable via ICMP pings for {duration} minutes ({failures} consecutive failures). This indicates a critical loss of connectivity or power.",
        "Network monitoring confirms {name} ({dtype}) is offline with 100% packet loss over {duration} minutes across {failures} probe intervals. Total path severance detected.",
        "Critical reachability failure on {dtype} {name}: zero ICMP response observed for {duration} minutes. Device appears disconnected or powered down."
    ],
    'HIGH_LATENCY': [
        "Network device {name} ({dtype}) is experiencing {severity} latency of {latency}ms (exceeding threshold), sustained over {duration} minutes with {failures} consecutive failure flags.",
        "Latency on {dtype} {name} has degraded to {latency}ms ({severity} severity level), impacting response times and traffic flow over a {duration}-minute window.",
        "High latency alert for {name} ({dtype}): round-trip time measured at {latency}ms, reflecting severe queuing or transmission delay."
    ],
    'HIGH_PACKET_LOSS': [
        "Device {name} ({dtype}) is suffering from {severity} packet loss at {loss}%, accompanied by {latency}ms latency over {duration} minutes across {failures} check intervals.",
        "High packet loss rate of {loss}% detected on {dtype} {name} ({severity} severity), indicating physical layer degradation or interface errors over {duration} minutes.",
        "Packet loss on {name} ({dtype}) reached {loss}% with {latency}ms latency, causing significant data transmission unreliability for {duration} minutes."
    ],
    'HIGH_CPU_USAGE': [
        "CPU utilization on {dtype} {name} has reached {severity} levels at {cpu}% over {duration} minutes ({failures} check intervals), risking control plane unresponsiveness.",
        "Critical processing load on {name} ({dtype}): CPU usage sustained at {cpu}% ({severity}) for {duration} minutes, threatening routing protocol and management stability.",
        "High CPU consumption ({severity}) on {dtype} {name} at {cpu}% over {duration} minutes, indicating heavy process execution or control plane traffic pressure."
    ],
    'HIGH_MEMORY_USAGE': [
        "Memory utilization on {dtype} {name} is at {severity} levels ({mem}%) over a {duration}-minute window across {failures} checks, approaching capacity limits.",
        "High memory pressure detected on {name} ({dtype}) with utilization at {mem}% ({severity}) sustained for {duration} minutes.",
        "Device {name} ({dtype}) memory usage has reached {mem}% ({severity}), risking out-of-memory errors and daemon termination over {duration} minutes."
    ],
    'HTTP_ENDPOINT_FAILURE': [
        "The monitored HTTP endpoint on {dtype} {name} failed health checks (HTTP OK: False, status: {status}) over {duration} minutes across {failures} checks.",
        "HTTP endpoint failure on {name} ({dtype}): service returned non-2xx status or timed out after {duration} minutes of monitoring.",
        "Critical HTTP service degradation on {dtype} {name}: endpoint unresponsive or throwing errors over {duration} minutes."
    ],
    'HTTP_SLOW_RESPONSE': [
        "HTTP response time on {dtype} {name} is slow at {http_time}ms ({severity}) over {duration} minutes, maintaining HTTP OK status.",
        "Elevated HTTP response latency of {http_time}ms detected on {name} ({dtype}) ({severity} severity) over {duration} minutes.",
        "Web service on {dtype} {name} responded in {http_time}ms, exceeding performance thresholds for {duration} minutes."
    ]
}

KNOWN_FAULT_TYPES = list(EXPLANATION_TEMPLATES.keys())

def infer_fault_type(text: str) -> str:
    for ft in KNOWN_FAULT_TYPES:
        if ft in text:
            return ft
    return 'HIGH_LATENCY'

def process_item(item: dict) -> dict:
    # If already instruction/input/output format (like handwritten seed)
    if 'instruction' in item and 'input' in item and 'output' in item:
        ft = infer_fault_type(item['input'])
        return {
            "instruction": item["instruction"],
            "input": item["input"],
            "output": item["output"],
            "fault_type": ft
        }

    # Otherwise synthetic scenario format
    ft = item.get('fault_type', 'HIGH_LATENCY')
    sev = item.get('severity', 'medium')
    name = item.get('device_name', 'device-01')
    dtype = item.get('device_type', 'router')
    metrics = item.get('metrics', {})

    latency = metrics.get('latency_ms', 0.0) or 0.0
    loss = metrics.get('packet_loss_pct', 0.0) or 0.0
    cpu = metrics.get('cpu_pct', 0.0) or 0.0
    mem = metrics.get('memory_pct', 0.0) or 0.0
    http_time = metrics.get('http_response_time_ms', 0.0) or 0.0
    status = metrics.get('http_status_code', 'None')
    duration = metrics.get('duration_minutes', 15)
    failures = metrics.get('consecutive_failures', 3)

    if 'explanation' in item and 'likely_causes' in item and 'recommended_steps' in item:
        explanation = item['explanation']
        causes = item['likely_causes']
        steps = item['recommended_steps']
    else:
        templates = EXPLANATION_TEMPLATES.get(ft, EXPLANATION_TEMPLATES['HIGH_LATENCY'])
        template = random.choice(templates)
        explanation = template.format(
            name=name, dtype=dtype, severity=sev, latency=latency, loss=loss,
            cpu=cpu, mem=mem, http_time=http_time, status=status, duration=duration, failures=failures
        )
        causes = [
            f"Hardware or resource bottleneck specific to {dtype} architecture.",
            f"Sustained load or physical layer degradation affecting {name}.",
            "Upstream network configuration or daemon state inconsistency."
        ]
        steps = [
            f"Inspect system diagnostic logs and resource counters on {name}.",
            "Verify physical connectivity, cabling, and upstream interface status.",
            "Apply corrective configuration or schedule maintenance reboot if required."
        ]

    causes_text = "\n".join([f"{idx+1}. {cause}" for idx, cause in enumerate(causes[:3])])
    steps_text = "\n".join([f"{idx+1}. {step}" for idx, step in enumerate(steps[:3])])

    input_text = (
        f"Device: {name} ({dtype.title()})\n"
        f"Fault Type: {ft}\n"
        f"Severity: {sev}\n"
        f"Metrics: Reachable={metrics.get('reachable')}, Latency={metrics.get('latency_ms')}ms, "
        f"Packet Loss={metrics.get('packet_loss_pct')}%, CPU={metrics.get('cpu_pct')}%, "
        f"Memory={metrics.get('memory_pct')}%, HTTP OK={metrics.get('http_ok')}, "
        f"HTTP Status={metrics.get('http_status_code')}, Response Time={metrics.get('http_response_time_ms')}ms, "
        f"Consecutive Failures={failures}, Duration={duration}m"
    )

    output_text = (
        f"Explanation: {explanation}\n"
        f"Likely causes:\n{causes_text}\n"
        f"Recommended actions:\n{steps_text}"
    )

    return {
        "instruction": INSTRUCTION,
        "input": input_text,
        "output": output_text,
        "fault_type": ft
    }

def main():
    root = Path(__file__).resolve().parent.parent
    data_dir = root / 'data'
    data_dir.mkdir(parents=True, exist_ok=True)

    scenarios_path = data_dir / 'scenarios.jsonl'
    seed_path = data_dir / 'handwritten_seed.jsonl'

    all_raw = []
    if scenarios_path.exists():
        with open(scenarios_path, 'r', encoding='utf-8') as f:
            for line in f:
                if line.strip():
                    all_raw.append(json.loads(line.strip()))

    if seed_path.exists():
        with open(seed_path, 'r', encoding='utf-8') as f:
            for line in f:
                if line.strip():
                    all_raw.append(json.loads(line.strip()))

    print(f"Loaded {len(all_raw)} total raw items (synthetic + handwritten seed).")

    formatted = [process_item(item) for item in all_raw]

    # Stratified split by fault_type (80% train, 10% val, 10% test)
    random.seed(42)
    by_type = defaultdict(list)
    for item in formatted:
        by_type[item['fault_type']].append(item)

    train_set, val_set, test_set = [], [], []

    for ft, items in by_type.items():
        random.shuffle(items)
        n = len(items)
        n_train = int(n * 0.8)
        n_val = int(n * 0.1)

        train_set.extend(items[:n_train])
        val_set.extend(items[n_train:n_train+n_val])
        test_set.extend(items[n_train+n_val:])

    random.shuffle(train_set)
    random.shuffle(val_set)
    random.shuffle(test_set)

    def save_split(path, dataset):
        with open(path, 'w', encoding='utf-8') as f:
            for item in dataset:
                clean_item = {
                    "instruction": item["instruction"],
                    "input": item["input"],
                    "output": item["output"]
                }
                f.write(json.dumps(clean_item) + '\n')

    save_split(data_dir / 'train.jsonl', train_set)
    save_split(data_dir / 'val.jsonl', val_set)
    save_split(data_dir / 'test.jsonl', test_set)

    print(f"\nDataset built successfully:")
    print(f"  Train: {len(train_set)} examples -> {data_dir / 'train.jsonl'}")
    print(f"  Val:   {len(val_set)} examples -> {data_dir / 'val.jsonl'}")
    print(f"  Test:  {len(test_set)} examples -> {data_dir / 'test.jsonl'}")

if __name__ == '__main__':
    main()
