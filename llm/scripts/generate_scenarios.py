#!/usr/bin/env python3
"""Generate synthetic network fault scenarios matching project thresholds."""

import json
import random
from pathlib import Path

DEVICE_TYPES = ['router', 'switch', 'server', 'access-point', 'firewall', 'other']

FAULT_TYPES = [
    'DEVICE_UNREACHABLE',
    'HIGH_LATENCY',
    'HIGH_PACKET_LOSS',
    'HIGH_CPU_USAGE',
    'HIGH_MEMORY_USAGE',
    'HTTP_ENDPOINT_FAILURE',
    'HTTP_SLOW_RESPONSE',
]

SEVERITIES = ['low', 'medium', 'high', 'critical']

DEVICE_NAMES = [
    'core-router-01', 'edge-router-02', 'dc-switch-01', 'access-switch-04',
    'app-server-01', 'db-server-02', 'auth-server-03', 'wifi-ap-hq-01',
    'perimeter-firewall', 'internal-firewall', 'proxy-server-01', 'dns-server-01'
]

def generate_scenario(seed_id: int) -> dict:
    random.seed(seed_id)
    device_name = random.choice(DEVICE_NAMES) + f'-{seed_id % 100:02d}'
    device_type = random.choice(DEVICE_TYPES)

    # Determine primary fault type
    fault_type = random.choice(FAULT_TYPES)

    # Determine severity based on fault type rules
    if fault_type == 'DEVICE_UNREACHABLE':
        severity = random.choice(['high', 'critical'])
    elif fault_type in {'HIGH_CPU_USAGE', 'HIGH_MEMORY_USAGE'}:
        severity = random.choice(['high', 'critical'])
    elif fault_type in {'HIGH_LATENCY', 'HIGH_PACKET_LOSS', 'HTTP_SLOW_RESPONSE'}:
        severity = random.choice(['medium', 'high'])
    elif fault_type == 'HTTP_ENDPOINT_FAILURE':
        severity = random.choice(['high', 'critical'])
    else:
        severity = random.choice(SEVERITIES)

    # Base metrics
    reachable = True
    latency_ms = round(random.uniform(5.0, 80.0), 2)
    packet_loss_pct = round(random.uniform(0.0, 2.0), 2)
    cpu_pct = round(random.uniform(15.0, 65.0), 2)
    memory_pct = round(random.uniform(30.0, 70.0), 2)
    http_ok = True
    http_response_time_ms = round(random.uniform(50.0, 400.0), 2)

    consecutive_failures = random.randint(1, 15)
    duration_minutes = random.randint(5, 240)

    # Apply thresholds and values according to fault type and severity
    if fault_type == 'DEVICE_UNREACHABLE':
        reachable = False
        latency_ms = None
        packet_loss_pct = 100.0
        http_ok = False
    elif fault_type == 'HIGH_LATENCY':
        if severity == 'medium':
            latency_ms = round(random.uniform(200.0, 499.9), 2)
        else:
            latency_ms = round(random.uniform(500.0, 1500.0), 2)
    elif fault_type == 'HIGH_PACKET_LOSS':
        if severity == 'medium':
            packet_loss_pct = round(random.uniform(20.0, 49.9), 2)
        else:
            packet_loss_pct = round(random.uniform(50.0, 100.0), 2)
    elif fault_type == 'HIGH_CPU_USAGE':
        if severity == 'high':
            cpu_pct = round(random.uniform(80.0, 89.9), 2)
        else:
            cpu_pct = round(random.uniform(90.0, 100.0), 2)
    elif fault_type == 'HIGH_MEMORY_USAGE':
        if severity == 'high':
            memory_pct = round(random.uniform(80.0, 89.9), 2)
        else:
            memory_pct = round(random.uniform(90.0, 100.0), 2)
    elif fault_type == 'HTTP_ENDPOINT_FAILURE':
        http_ok = False
        http_response_time_ms = None
    elif fault_type == 'HTTP_SLOW_RESPONSE':
        if severity == 'medium':
            http_response_time_ms = round(random.uniform(1000.0, 2999.9), 2)
        else:
            http_response_time_ms = round(random.uniform(3000.0, 8000.0), 2)

    # Combined faults (approx 20% chance to add secondary fault metric)
    secondary_fault = None
    if random.random() < 0.2 and fault_type not in {'DEVICE_UNREACHABLE', 'HTTP_ENDPOINT_FAILURE'}:
        if fault_type == 'HIGH_LATENCY':
            packet_loss_pct = round(random.uniform(25.0, 60.0), 2)
            secondary_fault = 'HIGH_PACKET_LOSS'
        elif fault_type == 'HIGH_CPU_USAGE':
            memory_pct = round(random.uniform(85.0, 95.0), 2)
            secondary_fault = 'HIGH_MEMORY_USAGE'

    # Plain-English explanation & recommendations generation
    explanation, causes, steps = build_explanation(fault_type, severity, device_type, device_name, latency_ms, packet_loss_pct, cpu_pct, memory_pct)

    scenario = {
        'scenario_id': f'scn-{seed_id:04d}',
        'device_name': device_name,
        'device_type': device_type,
        'fault_type': fault_type,
        'severity': severity,
        'metrics': {
            'reachable': reachable,
            'latency_ms': latency_ms,
            'packet_loss_pct': packet_loss_pct,
            'cpu_pct': cpu_pct,
            'memory_pct': memory_pct,
            'http_ok': http_ok,
            'http_response_time_ms': http_response_time_ms,
            'consecutive_failures': consecutive_failures,
            'duration_minutes': duration_minutes,
        },
        'secondary_fault': secondary_fault,
        'explanation': explanation,
        'likely_causes': causes,
        'recommended_steps': steps,
    }
    return scenario

def build_explanation(fault_type, severity, device_type, device_name, latency, loss, cpu, mem):
    if fault_type == 'DEVICE_UNREACHABLE':
        return (
            f"Device {device_name} ({device_type}) is completely unreachable via ICMP pings, "
            f"indicating a severe network disconnection or device power failure."
        ), [
            "Device power supply failure or accidental unplugging.",
            "Upstream switch or router interface down.",
            "Physical cable disconnection or optical transceiver fault.",
            "Firewall rule blocking ICMP traffic."
        ], [
            "Check physical power and link LEDs on the device.",
            "Verify status of the upstream switch port and VLAN configuration.",
            "Perform out-of-band management console check if available."
        ]
    elif fault_type == 'HIGH_LATENCY':
        return (
            f"{device_type.capitalize()} {device_name} is experiencing {severity} latency "
            f"at {latency}ms, exceeding normal operational thresholds."
        ), [
            "Network interface buffer congestion or queue drops.",
            "High bandwidth utilization saturating the link.",
            "Routing loops or suboptimal path selection."
        ], [
            "Inspect interface utilization and error counters on connected switches.",
            "Check for background traffic spikes or large data transfers.",
            "Trace packet path to identify routing bottlenecks."
        ]
    elif fault_type == 'HIGH_PACKET_LOSS':
        return (
            f"{device_type.capitalize()} {device_name} exhibits {severity} packet loss "
            f"at {loss}%, causing degraded communication quality."
        ), [
            "Faulty physical cabling or damaged SFP optics.",
            "Duplex mismatch on network interfaces.",
            "Interface hardware errors or buffer overruns."
        ], [
            "Check interface error logs for CRC errors, runts, and giants.",
            "Replace patch cables and test optical signal levels.",
            "Verify duplex and speed settings on both ends of the link."
        ]
    elif fault_type == 'HIGH_CPU_USAGE':
        return (
            f"{device_type.capitalize()} {device_name} has {severity} CPU utilization "
            f"at {cpu}%, risking management unresponsiveness."
        ), [
            "Runaway process or daemon consuming excessive CPU cycles.",
            "Control plane traffic spike or denial of service attempt.",
            "Firmware bug or memory leak causing high CPU."
        ], [
            "Access device CLI to inspect top CPU-consuming processes.",
            "Review system logs and SNMP metrics for traffic anomalies.",
            "Plan a maintenance window for firmware upgrade or reboot if necessary."
        ]
    elif fault_type == 'HIGH_MEMORY_USAGE':
        return (
            f"{device_type.capitalize()} {device_name} is operating at {severity} memory usage "
            f"({mem}%), approaching capacity exhaustion."
        ), [
            "Memory leak in routing daemon or system application.",
            "Excessive log buffering or state table exhaustion.",
            "Insufficient RAM for current operational workload."
        ], [
            "Check active process memory allocation via device CLI.",
            "Clear unused caches or restart affected non-critical services.",
            "Evaluate hardware memory upgrade if consistently undersized."
        ]
    elif fault_type == 'HTTP_ENDPOINT_FAILURE':
        return (
            f"The monitored HTTP endpoint on {device_name} ({device_type}) failed health checks, "
            f"returning non-2xx status or timing out."
        ), [
            "Web service / application crashed or unresponsive.",
            "Reverse proxy or web server misconfiguration.",
            "SSL/TLS certificate expiration or handshake failure."
        ], [
            "Check web server service status and error logs.",
            "Verify HTTP/HTTPS service accessibility locally on the server.",
            "Validate SSL certificate validity and endpoint URL configuration."
        ]
    else: # HTTP_SLOW_RESPONSE
        return (
            f"HTTP endpoint response time on {device_name} is slow ({severity}), impacting user experience."
        ), [
            "Database query bottleneck or slow backend dependency.",
            "High server load or CPU exhaustion.",
            "Network latency between proxy and application server."
        ], [
            "Inspect application performance monitoring (APM) traces.",
            "Check server resource utilization and database query logs.",
            "Review web server connection pool and timeout settings."
        ]

def main():
    root = Path(__file__).resolve().parent.parent
    data_dir = root / 'data'
    data_dir.mkdir(parents=True, exist_ok=True)
    output_file = data_dir / 'scenarios.jsonl'

    total_scenarios = 800
    print(f"Generating {total_scenarios} synthetic fault scenarios...")

    distribution = {}
    with open(output_file, 'w', encoding='utf-8') as f:
        for i in range(1, total_scenarios + 1):
            scenario = generate_scenario(i)
            f.write(json.dumps(scenario) + '\n')

            key = (scenario['fault_type'], scenario['severity'])
            distribution[key] = distribution.get(key, 0) + 1

    print(f"Successfully generated {total_scenarios} scenarios at {output_file}")
    print("\n--- Distribution Summary ---")
    for (ft, sev), count in sorted(distribution.items()):
        print(f"  {ft} [{sev}]: {count}")

    # Self-check / assertion test
    assert output_file.exists(), "Scenarios file was not created"
    with open(output_file, 'r', encoding='utf-8') as f:
        lines = f.readlines()
        assert len(lines) == total_scenarios, f"Expected {total_scenarios} lines, got {len(lines)}"
    print("\nSelf-check passed: Scenarios generated and verified.")

if __name__ == '__main__':
    main()
