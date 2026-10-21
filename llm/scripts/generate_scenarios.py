"""Generate synthetic fault scenarios matching the real thresholds from
backend/network/faults/detection.py (FaultThresholds defaults).

Severity rules (mirrors Django detection code exactly):
  DEVICE_UNREACHABLE          -> always critical
  HIGH_LATENCY medium         -> latency_ms in [200, 500)
  HIGH_LATENCY high           -> latency_ms >= 500
  HIGH_PACKET_LOSS medium     -> packet_loss_pct in [20, 50)
  HIGH_PACKET_LOSS high       -> packet_loss_pct >= 50
  HIGH_CPU_USAGE high         -> cpu_pct in [80, 90)
  HIGH_CPU_USAGE critical     -> cpu_pct >= 90
  HIGH_MEMORY_USAGE high      -> memory_pct in [80, 90)
  HIGH_MEMORY_USAGE critical  -> memory_pct >= 90
  Combined faults             -> worst (highest) severity across components

Consecutive ICMP failures:
  DEVICE_UNREACHABLE faults       -> randint(3, 15)  (must exceed threshold)
  Network-path faults (lat/loss)  -> randint(0, 2)   (detected before unreachability)
  SNMP resource faults (cpu/mem)  -> 0               (not ICMP-derived)

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
# "other" removed: no device-type-specific causes can be written for it.
# Every name maps to a concrete type so outputs are always meaningful.
DEVICE_TYPES = ["router", "switch", "server", "access-point", "firewall"]

DEVICE_NAMES = [
    # routers
    "core-router-01", "core-router-02", "edge-router-01", "edge-router-02",
    "edge-router-03", "isp-border-01", "isp-border-02", "vpn-concentrator-01",
    # switches
    "dist-switch-A", "dist-switch-B", "dist-switch-C",
    "access-sw-floor1", "access-sw-floor2", "access-sw-floor3",
    "access-sw-lab", "access-sw-datacenter", "core-sw-01",
    # servers
    "web-server-01", "web-server-02", "db-server-01", "db-server-02",
    "app-server-01", "app-server-02", "backup-server", "mgmt-server",
    "ntp-server", "radius-server", "proxy-server", "log-server-01",
    # access-points
    "ap-lobby", "ap-conf-room", "ap-warehouse", "ap-floor1",
    "ap-floor2", "ap-rooftop", "ap-parking",
    # firewalls
    "fw-perimeter", "fw-internal", "fw-dmz", "vpn-gw-01", "vpn-gw-02",
]

# Name -> device type mapping (deterministic, no random fallback)
_NAME_TO_TYPE: dict[str, str] = {}
for _n in DEVICE_NAMES:
    if any(k in _n for k in ("router", "border", "concentrator")):
        _NAME_TO_TYPE[_n] = "router"
    elif any(k in _n for k in ("switch", "sw", "core-sw")):
        _NAME_TO_TYPE[_n] = "switch"
    elif any(k in _n for k in ("server", "mgmt", "ntp", "radius", "proxy", "log-")):
        _NAME_TO_TYPE[_n] = "server"
    elif "ap" in _n:
        _NAME_TO_TYPE[_n] = "access-point"
    elif any(k in _n for k in ("fw", "vpn-gw")):
        _NAME_TO_TYPE[_n] = "firewall"
    else:
        _NAME_TO_TYPE[_n] = "server"  # safe fallback

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
    # Consecutive-failure threshold before DEVICE_UNREACHABLE fires.
    # The Django detector fires on reachable=False (one probe), but the
    # scenario represents a sustained event that has already been detected,
    # so we use a minimum of 3 to indicate the event is confirmed.
    "unreachable_min_failures": 3,
}

rng = random.Random(SEED)


def uni(lo: float, hi: float, digits: int = 2) -> float:
    return round(rng.uniform(lo, hi), digits)


def rand_duration() -> float:
    """Continuous duration in minutes with realistic distribution.

    Weighted toward short events (most faults are transient) but with a
    long tail out to 3 hours.
    """
    # 60% short (1-30 min), 30% medium (30-90 min), 10% long (90-180 min)
    bucket = rng.random()
    if bucket < 0.60:
        return round(rng.uniform(1, 30), 0)
    elif bucket < 0.90:
        return round(rng.uniform(30, 90), 0)
    else:
        return round(rng.uniform(90, 180), 0)


def rand_unreachable_failures() -> int:
    """Failures for DEVICE_UNREACHABLE: always above detection threshold."""
    return rng.randint(T["unreachable_min_failures"], 15)


def rand_network_failures() -> int:
    """Failures for latency/loss faults: 0-2 (detected before unreachable)."""
    return rng.randint(0, 2)


def pick_device() -> tuple[str, str]:
    name = rng.choice(DEVICE_NAMES)
    return name, _NAME_TO_TYPE[name]


def _combined_severity(severities: list[str]) -> str:
    """Worst severity across all components."""
    order = {"medium": 0, "high": 1, "critical": 2}
    return max(severities, key=lambda s: order.get(s, 0))


# ── per-fault generators ──────────────────────────────────────────────────────

def gen_unreachable():
    name, dtype = pick_device()
    return {
        "device_name": name, "device_type": dtype,
        "fault_type": "DEVICE_UNREACHABLE", "severity": "critical",
        "latency_ms": None, "packet_loss_pct": 100.0,
        "cpu_pct": None, "memory_pct": None,
        "consecutive_failures": rand_unreachable_failures(),
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
        "consecutive_failures": rand_network_failures(),
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
        "consecutive_failures": rand_network_failures(),
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
        "consecutive_failures": rand_network_failures(),
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
        "consecutive_failures": rand_network_failures(),
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
    """HIGH_LATENCY medium + HIGH_PACKET_LOSS medium."""
    name, dtype = pick_device()
    return {
        "device_name": name, "device_type": dtype,
        "fault_type": "HIGH_LATENCY+HIGH_PACKET_LOSS", "severity": "medium",
        "latency_ms": uni(T["latency_medium"], T["latency_high"] - 1),
        "packet_loss_pct": uni(T["loss_medium"], T["loss_high"] - 1),
        "cpu_pct": None, "memory_pct": None,
        "consecutive_failures": rand_network_failures(),
        "duration_minutes": rand_duration(),
    }


def gen_latency_and_loss_high():
    """HIGH_LATENCY high + HIGH_PACKET_LOSS high -> severity high."""
    name, dtype = pick_device()
    return {
        "device_name": name, "device_type": dtype,
        "fault_type": "HIGH_LATENCY+HIGH_PACKET_LOSS", "severity": "high",
        "latency_ms": uni(T["latency_high"], 3000.0),
        "packet_loss_pct": uni(T["loss_high"], 95.0),
        "cpu_pct": None, "memory_pct": None,
        "consecutive_failures": rand_network_failures(),
        "duration_minutes": rand_duration(),
    }


def gen_cpu_and_memory_high():
    """CPU and memory both in [80, 90) -> severity high."""
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
    """At least one of CPU/memory >= 90 -> severity critical."""
    name, dtype = pick_device()
    # Randomly generate which crossed critical, or both
    which = rng.choice(["cpu", "mem", "both"])
    if which == "cpu":
        cpu = uni(T["cpu_critical"], 100.0)
        mem = uni(T["mem_high"], T["mem_critical"] - 0.1)
    elif which == "mem":
        cpu = uni(T["cpu_high"], T["cpu_critical"] - 0.1)
        mem = uni(T["mem_critical"], 100.0)
    else:
        cpu = uni(T["cpu_critical"], 100.0)
        mem = uni(T["mem_critical"], 100.0)
    return {
        "device_name": name, "device_type": dtype,
        "fault_type": "HIGH_CPU_USAGE+HIGH_MEMORY_USAGE", "severity": "critical",
        "latency_ms": uni(5, 200),
        "packet_loss_pct": uni(0, 8),
        "cpu_pct": cpu,
        "memory_pct": mem,
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
        "consecutive_failures": rand_unreachable_failures(),
        "duration_minutes": rand_duration(),
    }


def gen_latency_with_cpu():
    """High CPU causing elevated latency.

    Severity derived from component severities:
      CPU >= 90  -> critical (regardless of latency band)
      latency >= 500 OR CPU >= 80 -> high
      else -> medium
    """
    name, dtype = pick_device()
    # pick latency band first, then CPU band, then derive severity
    lat_band = rng.choice(["medium", "high"])
    cpu_band  = rng.choice(["high", "critical"])

    lat = (uni(T["latency_medium"], T["latency_high"] - 1)
           if lat_band == "medium"
           else uni(T["latency_high"], 2000.0))
    cpu = (uni(T["cpu_high"], T["cpu_critical"] - 0.1)
           if cpu_band == "high"
           else uni(T["cpu_critical"], 100.0))

    # Severity: worst component
    lat_sev = "medium" if lat < T["latency_high"] else "high"
    cpu_sev = "high" if cpu < T["cpu_critical"] else "critical"
    severity = _combined_severity([lat_sev, cpu_sev])

    return {
        "device_name": name, "device_type": dtype,
        "fault_type": "HIGH_LATENCY+HIGH_CPU_USAGE", "severity": severity,
        "latency_ms": lat,
        "packet_loss_pct": uni(0, 5),
        "cpu_pct": cpu,
        "memory_pct": uni(30, 79),
        "consecutive_failures": rand_network_failures(),
        "duration_minutes": rand_duration(),
    }


# ── proportions (sum = TARGET ~800) ──────────────────────────────────────────
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
# total = 855; trimmed to TARGET below


def main():
    out_path = Path(__file__).parent.parent / "data" / "scenarios.jsonl"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    scenarios = []
    for gen_fn, count in GENERATORS:
        for _ in range(count):
            scenarios.append(gen_fn())

    rng.shuffle(scenarios)
    scenarios = scenarios[:TARGET]

    with out_path.open("w", encoding="utf-8") as f:
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

    # ── sanity assertions ────────────────────────────────────────────────────
    for s in scenarios:
        ft  = s["fault_type"]
        sev = s["severity"]
        cf  = s.get("consecutive_failures", 0) or 0

        # 1. Consecutive failures: only UNREACHABLE may have >= threshold
        if "UNREACHABLE" in ft:
            assert cf >= T["unreachable_min_failures"], \
                f"UNREACHABLE fault must have >= {T['unreachable_min_failures']} failures: {s}"
            assert s["packet_loss_pct"] == 100.0, f"unreachable must have 100% loss: {s}"
        else:
            assert cf <= 2, \
                f"non-UNREACHABLE fault must have consecutive_failures <= 2: {s}"

        # 2. Severity follows the real rules
        if ft == "DEVICE_UNREACHABLE":
            assert sev == "critical", s
        if ft == "HIGH_LATENCY":
            if sev == "medium":
                assert T["latency_medium"] <= s["latency_ms"] < T["latency_high"], s
            elif sev == "high":
                assert s["latency_ms"] >= T["latency_high"], s
        if ft == "HIGH_PACKET_LOSS":
            if sev == "medium":
                assert T["loss_medium"] <= s["packet_loss_pct"] < T["loss_high"], s
            elif sev == "high":
                assert s["packet_loss_pct"] >= T["loss_high"], s
        if ft == "HIGH_CPU_USAGE":
            if sev == "high":
                assert T["cpu_high"] <= s["cpu_pct"] < T["cpu_critical"], s
            elif sev == "critical":
                assert s["cpu_pct"] >= T["cpu_critical"], s
        if ft == "HIGH_MEMORY_USAGE":
            if sev == "high":
                assert T["mem_high"] <= s["memory_pct"] < T["mem_critical"], s
            elif sev == "critical":
                assert s["memory_pct"] >= T["mem_critical"], s
        if ft == "HIGH_CPU_USAGE+HIGH_MEMORY_USAGE":
            if sev == "critical":
                assert (s["cpu_pct"] >= T["cpu_critical"] or
                        s["memory_pct"] >= T["mem_critical"]), \
                    f"combined critical must have at least one metric >= critical threshold: {s}"
            elif sev == "high":
                assert (T["cpu_high"] <= s["cpu_pct"] < T["cpu_critical"] and
                        T["mem_high"] <= s["memory_pct"] < T["mem_critical"]), s
        if ft == "HIGH_LATENCY+HIGH_CPU_USAGE":
            # severity must equal worst component
            lat_sev = "medium" if s["latency_ms"] < T["latency_high"] else "high"
            cpu_sev = "high"   if s["cpu_pct"]   < T["cpu_critical"]  else "critical"
            expected = _combined_severity([lat_sev, cpu_sev])
            assert sev == expected, \
                f"HIGH_LATENCY+HIGH_CPU_USAGE severity mismatch: got {sev}, expected {expected}: {s}"

    print("\nAll threshold assertions passed.")


if __name__ == "__main__":
    main()
