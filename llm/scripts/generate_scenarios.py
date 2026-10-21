"""Generate synthetic fault scenarios matching the real thresholds from
backend/network/faults/detection.py (FaultThresholds defaults).

Thresholds (from source):
  latency:      medium >= 200 ms,   high >= 500 ms
  packet_loss:  medium >= 20 %,     high >= 50 %
  cpu:          high   >= 80 %,     critical >= 90 %
  memory:       high   >= 80 %,     critical >= 90 %
  unreachable:  always critical

Output: llm/data/scenarios.jsonl  (~800 rows)
Usage:  python llm/scripts/generate_scenarios.py
"""

import json
import random
from collections import Counter
from pathlib import Path

SEED = 42
TARGET = 800

# ── domain constants ──────────────────────────────────────────────────────────
DEVICE_TYPES = ["router", "switch", "server", "access-point", "firewall", "other"]

DEVICE_NAMES = [
    "core-router-01", "edge-router-02", "dist-switch-A", "dist-switch-B",
    "access-sw-floor1", "access-sw-floor2", "web-server-01", "db-server-01",
    "app-server-02", "backup-server", "ap-lobby", "ap-conf-room",
    "ap-warehouse", "fw-perimeter", "fw-internal", "mgmt-server",
    "ntp-server", "radius-server", "proxy-server", "vpn-gw-01",
]

# ── thresholds (mirrors FaultThresholds defaults) ─────────────────────────────
T = {
    "latency_medium": 200.0,
    "latency_high":   500.0,
    "loss_medium":     20.0,
    "loss_high":       50.0,
    "cpu_high":        80.0,
    "cpu_critical":    90.0,
    "mem_high":        80.0,
    "mem_critical":    90.0,
}

rng = random.Random(SEED)

def uni(lo, hi, digits=2):
    return round(rng.uniform(lo, hi), digits)

def rand_duration():
    """Duration in minutes — short bursts to multi-hour events."""
    return rng.choice([1, 2, 3, 5, 8, 10, 15, 20, 30, 45, 60, 90, 120, 180])

def rand_failures():
    """Consecutive ICMP failures before detection."""
    return rng.randint(1, 15)

def pick_device():
    name = rng.choice(DEVICE_NAMES)
    # derive a plausible type from the name heuristic, else random
    for keyword, dtype in [("router", "router"), ("switch", "switch"), ("sw", "switch"),
                            ("server", "server"), ("ap", "access-point"), ("fw", "firewall")]:
        if keyword in name:
            return name, dtype
    return name, rng.choice(DEVICE_TYPES)

# ── per-fault generators ──────────────────────────────────────────────────────

def gen_unreachable():
    name, dtype = pick_device()
    return {
        "device_name": name, "device_type": dtype,
        "fault_type": "DEVICE_UNREACHABLE", "severity": "critical",
        "latency_ms": None, "packet_loss_pct": 100.0,
        "cpu_pct": None, "memory_pct": None,
        "consecutive_failures": rand_failures(),
        "duration_minutes": rand_duration(),
    }

def gen_high_latency_medium():
    name, dtype = pick_device()
    return {
        "device_name": name, "device_type": dtype,
        "fault_type": "HIGH_LATENCY", "severity": "medium",
        "latency_ms": uni(T["latency_medium"], T["latency_high"] - 0.1),
        "packet_loss_pct": uni(0, 5),
        "cpu_pct": None, "memory_pct": None,
        "consecutive_failures": rng.randint(1, 5),
        "duration_minutes": rand_duration(),
    }

def gen_high_latency_high():
    name, dtype = pick_device()
    return {
        "device_name": name, "device_type": dtype,
        "fault_type": "HIGH_LATENCY", "severity": "high",
        "latency_ms": uni(T["latency_high"], 2500.0),
        "packet_loss_pct": uni(0, 10),
        "cpu_pct": None, "memory_pct": None,
        "consecutive_failures": rng.randint(2, 10),
        "duration_minutes": rand_duration(),
    }

def gen_packet_loss_medium():
    name, dtype = pick_device()
    return {
        "device_name": name, "device_type": dtype,
        "fault_type": "HIGH_PACKET_LOSS", "severity": "medium",
        "latency_ms": uni(10, T["latency_medium"] - 1),
        "packet_loss_pct": uni(T["loss_medium"], T["loss_high"] - 0.1),
        "cpu_pct": None, "memory_pct": None,
        "consecutive_failures": rng.randint(1, 6),
        "duration_minutes": rand_duration(),
    }

def gen_packet_loss_high():
    name, dtype = pick_device()
    return {
        "device_name": name, "device_type": dtype,
        "fault_type": "HIGH_PACKET_LOSS", "severity": "high",
        "latency_ms": uni(10, T["latency_medium"] - 1),
        "packet_loss_pct": uni(T["loss_high"], 99.0),
        "cpu_pct": None, "memory_pct": None,
        "consecutive_failures": rng.randint(3, 12),
        "duration_minutes": rand_duration(),
    }

def gen_cpu_high():
    name, dtype = pick_device()
    return {
        "device_name": name, "device_type": dtype,
        "fault_type": "HIGH_CPU_USAGE", "severity": "high",
        "latency_ms": uni(5, 80),
        "packet_loss_pct": uni(0, 3),
        "cpu_pct": uni(T["cpu_high"], T["cpu_critical"] - 0.1),
        "memory_pct": uni(40, 79),
        "consecutive_failures": 0,
        "duration_minutes": rand_duration(),
    }

def gen_cpu_critical():
    name, dtype = pick_device()
    return {
        "device_name": name, "device_type": dtype,
        "fault_type": "HIGH_CPU_USAGE", "severity": "critical",
        "latency_ms": uni(5, 120),
        "packet_loss_pct": uni(0, 5),
        "cpu_pct": uni(T["cpu_critical"], 100.0),
        "memory_pct": uni(50, 95),
        "consecutive_failures": 0,
        "duration_minutes": rand_duration(),
    }

def gen_memory_high():
    name, dtype = pick_device()
    return {
        "device_name": name, "device_type": dtype,
        "fault_type": "HIGH_MEMORY_USAGE", "severity": "high",
        "latency_ms": uni(5, 80),
        "packet_loss_pct": uni(0, 3),
        "cpu_pct": uni(30, 79),
        "memory_pct": uni(T["mem_high"], T["mem_critical"] - 0.1),
        "consecutive_failures": 0,
        "duration_minutes": rand_duration(),
    }

def gen_memory_critical():
    name, dtype = pick_device()
    return {
        "device_name": name, "device_type": dtype,
        "fault_type": "HIGH_MEMORY_USAGE", "severity": "critical",
        "latency_ms": uni(5, 150),
        "packet_loss_pct": uni(0, 5),
        "cpu_pct": uni(40, 99),
        "memory_pct": uni(T["mem_critical"], 100.0),
        "consecutive_failures": 0,
        "duration_minutes": rand_duration(),
    }

# ── combined-fault generators (represent co-occurring conditions) ─────────────

def gen_latency_and_loss_medium():
    """HIGH_LATENCY medium + HIGH_PACKET_LOSS medium in one record."""
    name, dtype = pick_device()
    return {
        "device_name": name, "device_type": dtype,
        "fault_type": "HIGH_LATENCY+HIGH_PACKET_LOSS", "severity": "medium",
        "latency_ms": uni(T["latency_medium"], T["latency_high"] - 1),
        "packet_loss_pct": uni(T["loss_medium"], T["loss_high"] - 1),
        "cpu_pct": None, "memory_pct": None,
        "consecutive_failures": rng.randint(1, 6),
        "duration_minutes": rand_duration(),
    }

def gen_latency_and_loss_high():
    name, dtype = pick_device()
    return {
        "device_name": name, "device_type": dtype,
        "fault_type": "HIGH_LATENCY+HIGH_PACKET_LOSS", "severity": "high",
        "latency_ms": uni(T["latency_high"], 3000.0),
        "packet_loss_pct": uni(T["loss_high"], 95.0),
        "cpu_pct": None, "memory_pct": None,
        "consecutive_failures": rng.randint(3, 12),
        "duration_minutes": rand_duration(),
    }

def gen_cpu_and_memory_high():
    name, dtype = pick_device()
    return {
        "device_name": name, "device_type": dtype,
        "fault_type": "HIGH_CPU_USAGE+HIGH_MEMORY_USAGE", "severity": "high",
        "latency_ms": uni(5, 100),
        "packet_loss_pct": uni(0, 4),
        "cpu_pct": uni(T["cpu_high"], T["cpu_critical"] - 0.1),
        "memory_pct": uni(T["mem_high"], T["mem_critical"] - 0.1),
        "consecutive_failures": 0,
        "duration_minutes": rand_duration(),
    }

def gen_cpu_and_memory_critical():
    name, dtype = pick_device()
    return {
        "device_name": name, "device_type": dtype,
        "fault_type": "HIGH_CPU_USAGE+HIGH_MEMORY_USAGE", "severity": "critical",
        "latency_ms": uni(5, 200),
        "packet_loss_pct": uni(0, 8),
        "cpu_pct": uni(T["cpu_critical"], 100.0),
        "memory_pct": uni(T["mem_critical"], 100.0),
        "consecutive_failures": 0,
        "duration_minutes": rand_duration(),
    }

def gen_unreachable_with_loss():
    """Device went unreachable after progressive packet loss."""
    name, dtype = pick_device()
    return {
        "device_name": name, "device_type": dtype,
        "fault_type": "DEVICE_UNREACHABLE+HIGH_PACKET_LOSS", "severity": "critical",
        "latency_ms": None,
        "packet_loss_pct": 100.0,
        "cpu_pct": None, "memory_pct": None,
        "consecutive_failures": rand_failures(),
        "duration_minutes": rand_duration(),
    }

def gen_latency_with_cpu():
    """High CPU causing elevated latency."""
    name, dtype = pick_device()
    severity = rng.choice(["medium", "high"])
    lat_lo = T["latency_medium"] if severity == "medium" else T["latency_high"]
    lat_hi = T["latency_high"] - 1 if severity == "medium" else 2000.0
    cpu_lo = T["cpu_high"] if severity == "medium" else T["cpu_critical"]
    return {
        "device_name": name, "device_type": dtype,
        "fault_type": "HIGH_LATENCY+HIGH_CPU_USAGE", "severity": severity,
        "latency_ms": uni(lat_lo, lat_hi),
        "packet_loss_pct": uni(0, 5),
        "cpu_pct": uni(cpu_lo, 100.0),
        "memory_pct": uni(30, 79),
        "consecutive_failures": rng.randint(0, 4),
        "duration_minutes": rand_duration(),
    }

# ── proportions (sum = TARGET ~800) ──────────────────────────────────────────
# Approx realistic distribution: connectivity issues most common,
# resource exhaustion less frequent, combinations rarer.
GENERATORS = [
    (gen_unreachable,             90),
    (gen_high_latency_medium,     85),
    (gen_high_latency_high,       70),
    (gen_packet_loss_medium,      75),
    (gen_packet_loss_high,        60),
    (gen_cpu_high,                65),
    (gen_cpu_critical,            45),
    (gen_memory_high,             65),
    (gen_memory_critical,         45),
    (gen_latency_and_loss_medium, 55),
    (gen_latency_and_loss_high,   45),
    (gen_cpu_and_memory_high,     40),
    (gen_cpu_and_memory_critical, 30),
    (gen_unreachable_with_loss,   35),
    (gen_latency_with_cpu,        50),
]
# total = 855; close enough, trimmed to TARGET below

def main():
    out_path = Path(__file__).parent.parent / "data" / "scenarios.jsonl"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    scenarios = []
    for gen_fn, count in GENERATORS:
        for _ in range(count):
            scenarios.append(gen_fn())

    rng.shuffle(scenarios)
    scenarios = scenarios[:TARGET]

    with out_path.open("w") as f:
        for scenario in scenarios:
            f.write(json.dumps(scenario) + "\n")

    # ── summary ───────────────────────────────────────────────────────────────
    by_type = Counter(s["fault_type"] for s in scenarios)
    by_sev  = Counter(s["severity"]   for s in scenarios)

    print(f"Written {len(scenarios)} scenarios -> {out_path}\n")
    print("-- By fault type ------------------------------------------")
    for ft, n in sorted(by_type.items()):
        bar = "#" * (n // 5)
        print(f"  {ft:<40} {n:>4}  {bar}")
    print("\n-- By severity --------------------------------------------")
    for sev in ["critical", "high", "medium", "low"]:
        n = by_sev.get(sev, 0)
        bar = "#" * (n // 5)
        print(f"  {sev:<12} {n:>4}  {bar}")

    # sanity checks
    for s in scenarios:
        ft = s["fault_type"]
        sev = s["severity"]
        if "UNREACHABLE" in ft:
            assert s["packet_loss_pct"] == 100.0, f"unreachable must have 100% loss: {s}"
        if ft == "HIGH_LATENCY" and sev == "medium":
            assert s["latency_ms"] >= T["latency_medium"], s
            assert s["latency_ms"] <  T["latency_high"],   s
        if ft == "HIGH_LATENCY" and sev == "high":
            assert s["latency_ms"] >= T["latency_high"], s
        if ft == "HIGH_PACKET_LOSS" and sev == "medium":
            assert s["packet_loss_pct"] >= T["loss_medium"], s
            assert s["packet_loss_pct"] <  T["loss_high"],   s
        if ft == "HIGH_PACKET_LOSS" and sev == "high":
            assert s["packet_loss_pct"] >= T["loss_high"], s
        if ft == "HIGH_CPU_USAGE" and sev == "high":
            assert s["cpu_pct"] >= T["cpu_high"], s
        if ft == "HIGH_CPU_USAGE" and sev == "critical":
            assert s["cpu_pct"] >= T["cpu_critical"], s
        if ft == "HIGH_MEMORY_USAGE" and sev == "high":
            assert s["memory_pct"] >= T["mem_high"], s
        if ft == "HIGH_MEMORY_USAGE" and sev == "critical":
            assert s["memory_pct"] >= T["mem_critical"], s
    print("\nAll threshold assertions passed.")

if __name__ == "__main__":
    main()
