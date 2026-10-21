"""Turn scenarios.jsonl + handwritten_seed.jsonl into instruction-tuning examples.

Outputs:
  llm/data/dataset.jsonl        — full merged set
  llm/data/train.jsonl          — 80 % stratified by fault_type
  llm/data/val.jsonl            — 10 %
  llm/data/test.jsonl           — 10 %

Usage:
  python llm/scripts/build_dataset.py
"""

from __future__ import annotations

import json
import random
from collections import defaultdict
from pathlib import Path

# ── paths ─────────────────────────────────────────────────────────────────────
ROOT = Path(__file__).parent.parent
SCENARIOS   = ROOT / "data" / "scenarios.jsonl"
SEED_FILE   = ROOT / "data" / "handwritten_seed.jsonl"
DATASET_OUT = ROOT / "data" / "dataset.jsonl"
TRAIN_OUT   = ROOT / "data" / "train.jsonl"
VAL_OUT     = ROOT / "data" / "val.jsonl"
TEST_OUT    = ROOT / "data" / "test.jsonl"

SPLIT_SEED  = 42
TRAIN_RATIO = 0.80
VAL_RATIO   = 0.10
# test = whatever remains

# ── static instruction ────────────────────────────────────────────────────────
INSTRUCTION = (
    "You are a network operations assistant. "
    "Given a fault event detected on a network device, produce a structured explanation "
    "with three clearly labelled sections: "
    "'Explanation' (what is happening and why it matters, referencing the specific metrics), "
    "'Likely causes' (ranked list of probable root causes for this device type and fault pattern), "
    "and 'Recommended actions' (concrete remediation steps in priority order)."
)

# ── phrasing banks ────────────────────────────────────────────────────────────
# Each bank maps to a list; we pick by hashing the scenario so generation is
# deterministic but varied across different scenarios.

def _pick(bank: list, scenario: dict) -> str:
    """Deterministic pick so re-runs produce identical output."""
    key = json.dumps(scenario, sort_keys=True)
    return bank[hash(key) % len(bank)]

# ── severity adjectives ───────────────────────────────────────────────────────
SEV_ADJ = {
    "medium":   ["elevated", "moderate", "notable", "above-threshold"],
    "high":     ["high", "significant", "concerning", "serious"],
    "critical": ["critical", "severe", "alarming", "dangerously high"],
}

def sev_adj(sev: str, scenario: dict) -> str:
    return _pick(SEV_ADJ.get(sev, SEV_ADJ["high"]), scenario)

# ── device-type context ───────────────────────────────────────────────────────
DEVICE_ROLE = {
    "router":       "a core routing device responsible for inter-network traffic forwarding",
    "switch":       "a Layer 2/3 switching device forwarding traffic between local segments",
    "server":       "a host running application or infrastructure services",
    "access-point": "a wireless access point providing Wi-Fi connectivity to clients",
    "firewall":     "a security gateway inspecting and filtering network traffic",
    "other":        "a network device",
}

def device_role(dtype: str) -> str:
    return DEVICE_ROLE.get(dtype, DEVICE_ROLE["other"])

# ── DEVICE_UNREACHABLE ────────────────────────────────────────────────────────
_UNREACH_EXPLAIN = [
    "The device has stopped responding to all ICMP probes ({failures} consecutive failures over {dur} minutes), indicating it is completely unreachable from the monitoring host.",
    "ICMP monitoring lost contact with the device after {failures} consecutive failed probes spanning {dur} minutes. No echo replies are being received.",
    "All {failures} ping attempts over a {dur}-minute window returned no response. The device appears to be offline or isolated from the monitoring network.",
    "The monitoring system received no ICMP echo reply across {failures} consecutive probes during a {dur}-minute outage window, classifying this as a critical unreachability event.",
]
_UNREACH_CAUSES = {
    "router": [
        "Power failure or hardware fault on the router chassis.",
        "BGP/OSPF route withdrawal making the management address unroutable.",
        "ACL or firewall rule inadvertently blocking ICMP from the monitoring host.",
        "Interface flap or link failure on the uplink port.",
        "CPU overload causing the device to drop control-plane traffic.",
    ],
    "switch": [
        "Power supply failure or PoE overload shutting down the switch.",
        "Spanning-tree loop causing a broadcast storm that overwhelms the control plane.",
        "Management VLAN misconfiguration isolating the monitoring path.",
        "Uplink port failure disconnecting the switch from the aggregation layer.",
        "Firmware crash or watchdog reboot in progress.",
    ],
    "server": [
        "Operating system crash or kernel panic requiring a hard reboot.",
        "Network interface card failure or cable disconnection.",
        "Hypervisor migration or snapshot operation that paused the VM.",
        "Firewall or iptables rule blocking ICMP from the monitoring subnet.",
        "Out-of-band management port is down and the in-band NIC has failed.",
    ],
    "access-point": [
        "PoE budget exceeded, causing the switch port to cut power to the AP.",
        "Controller-managed AP rebooting after a firmware push.",
        "Physical cable disconnection or PoE injector failure.",
        "RF interference causing the AP to reset its radio stack.",
        "Management VLAN trunk misconfiguration blocking reachability.",
    ],
    "firewall": [
        "Failover to secondary unit with a different management IP.",
        "Policy change blocking ICMP from the monitoring segment.",
        "Hardware failure on the active unit triggering an unplanned failover.",
        "High-availability state synchronisation issue causing both units to be unreachable briefly.",
        "Out-of-memory condition crashing the packet-processing engine.",
    ],
    "other": [
        "Power or hardware failure.",
        "Network path change making the device unreachable.",
        "Management interface misconfiguration.",
        "Firmware crash or reboot in progress.",
    ],
}
_UNREACH_ACTIONS = {
    "router": [
        "Verify physical connectivity and power status via out-of-band console or IPMI.",
        "Check upstream logs for interface flap or routing withdrawal events.",
        "Attempt an out-of-band SSH session to confirm whether the device is responsive.",
        "Review recent configuration changes (ACLs, route policies) that could block ICMP.",
        "If unresponsive, dispatch on-site personnel to perform a controlled power cycle.",
    ],
    "switch": [
        "Check PoE power budget and per-port power draw in the management system.",
        "Inspect span-tree topology for root bridge elections or topology change notifications.",
        "Verify management VLAN tagging on all uplink trunk ports.",
        "Review system logs via out-of-band console for crash or reload messages.",
        "Power-cycle via smart PDU if the device does not respond to console.",
    ],
    "server": [
        "Attempt console/iDRAC/iLO access to check for a kernel panic or hardware alarm.",
        "Verify NIC link state and cable integrity at the patch panel.",
        "Check hypervisor events if this is a virtual machine.",
        "Review iptables/nftables rules for ICMP drops from the monitoring host.",
        "Coordinate with on-site staff for a physical inspection if remote access fails.",
    ],
    "access-point": [
        "Check the PoE switch port status and per-port power budget.",
        "Inspect the wireless controller for AP reboot or join failure events.",
        "Verify physical Ethernet cable and PoE injector if used.",
        "Review the controller's firmware update scheduler for a concurrent push.",
        "Re-adopt the AP from the controller if it is powered but not joining.",
    ],
    "firewall": [
        "Check the HA pair status to determine which unit is active.",
        "Access the secondary unit's console and review failover events.",
        "Confirm ICMP passing from the monitoring host through the current active unit's policy.",
        "Review hardware health alarms (memory, CPU, NIC).",
        "Contact the firewall vendor's support line if both units are unreachable.",
    ],
    "other": [
        "Attempt out-of-band console access.",
        "Verify physical power and cable connections.",
        "Check upstream switch port for link state.",
        "Review recent configuration changes.",
        "Dispatch on-site staff for physical inspection.",
    ],
}

def _causes_list(causes: list[str]) -> str:
    return "\n".join(f"{i+1}. {c}" for i, c in enumerate(causes))

def _actions_list(actions: list[str]) -> str:
    return "\n".join(f"{i+1}. {a}" for i, a in enumerate(actions))

def build_unreachable(s: dict) -> dict:
    dtype = s["device_type"]
    dur   = s["duration_minutes"]
    fails = s["consecutive_failures"]
    sev   = s["severity"]

    explain_tmpl = _pick(_UNREACH_EXPLAIN, s)
    explain = explain_tmpl.format(failures=fails, dur=dur)

    causes  = _causes_list(_UNREACH_CAUSES.get(dtype, _UNREACH_CAUSES["other"]))
    actions = _actions_list(_UNREACH_ACTIONS.get(dtype, _UNREACH_ACTIONS["other"]))

    output = (
        f"Explanation:\n{explain}\n\n"
        f"Likely causes:\n{causes}\n\n"
        f"Recommended actions:\n{actions}"
    )
    return output

# ── HIGH_LATENCY ──────────────────────────────────────────────────────────────
_LAT_EXPLAIN_MED = [
    "Round-trip latency to the device is {lat} ms, which exceeds the 200 ms medium threshold. Packet loss is negligible at {loss}%, so the link is stable but slow.",
    "ICMP probes are returning in {lat} ms — above the 200 ms warning level — while packet delivery remains intact ({loss}% loss). The device is reachable but experiencing degraded response times.",
    "Latency has climbed to {lat} ms (threshold: 200 ms). With only {loss}% packet loss the underlying link appears healthy; the delay is likely caused by processing or queuing overhead.",
    "The device is responding to pings in {lat} ms, crossing the medium-severity threshold of 200 ms. Low packet loss ({loss}%) suggests the path is congested rather than failing.",
]
_LAT_EXPLAIN_HIGH = [
    "Latency has risen to {lat} ms, well above the 500 ms high-severity threshold. Even with minimal packet loss ({loss}%), response times at this level indicate serious congestion or processing bottlenecks.",
    "Round-trip time to the device is {lat} ms — {x:.1f}× the 500 ms high threshold. Packet loss is {loss}%, meaning packets are arriving but with severely degraded timing.",
    "ICMP probes are taking {lat} ms to return, triggering a high-severity latency fault. At this level user-facing applications will experience timeouts and retransmissions.",
    "The monitoring system recorded a round-trip latency of {lat} ms against the 500 ms high-severity limit. The {loss}% packet loss figure confirms the path is still functional but heavily congested.",
]
_LAT_CAUSES = {
    "router": {
        "medium": [
            "CPU-based packet forwarding (process switching) instead of CEF/hardware forwarding.",
            "QoS policy mis-classification causing high-priority traffic to queue behind bulk flows.",
            "Routing table churn triggering repeated route lookups.",
            "WAN link approaching bandwidth saturation during peak hours.",
            "SNMP or NetFlow polling consuming management-plane CPU cycles.",
        ],
        "high": [
            "Severe WAN link congestion or upstream provider issue.",
            "ACL or NAT table exhaustion forcing software-path processing.",
            "BGP path instability causing continuous route recalculation.",
            "Hardware queue full, causing packets to be held in software buffers.",
            "Interface error rate rising, triggering retransmissions that compound delay.",
        ],
    },
    "switch": {
        "medium": [
            "Spanning-tree topology change causing transient re-convergence delay.",
            "Broadcast or multicast storm consuming switching capacity.",
            "Port mirror (SPAN) session overloading the CPU for analysis traffic.",
            "MAC table nearing capacity, causing unknown-unicast flooding.",
            "QoS misconfiguration deprioritising management traffic.",
        ],
        "high": [
            "Broadcast storm or Layer 2 loop saturating all ports.",
            "Control-plane policing rate exceeded, dropping ICMP to the CPU.",
            "Uplink trunk failure with failover in progress.",
            "TCAM or MAC table exhaustion causing all traffic to be software-switched.",
            "Power supply issue causing intermittent packet drops and retransmissions.",
        ],
    },
    "server": {
        "medium": [
            "Network stack processing overhead from high connection count.",
            "Interrupt coalescing settings delaying small packet responses.",
            "NIC driver or firmware bug introducing unnecessary latency.",
            "High I/O load causing the kernel to defer network interrupt handling.",
            "Receive buffer saturation on a busy NIC.",
        ],
        "high": [
            "Kernel or NIC driver under extreme I/O contention, deferring ICMP responses.",
            "Swap usage causing paging that starves the network stack of CPU time.",
            "NIC experiencing hardware errors, retransmitting at the physical layer.",
            "Container or VM migration pausing the instance briefly.",
            "Traffic shaping or tc (traffic control) rule throttling outbound ICMP.",
        ],
    },
    "access-point": {
        "medium": [
            "RF interference or co-channel congestion slowing wireless retransmissions.",
            "High client association count saturating the AP's CPU for association management.",
            "Background channel scanning pausing radio service briefly.",
            "Ethernet uplink approaching bandwidth limit from wireless-to-wired aggregation.",
            "PoE power slightly below requirement, causing intermittent performance degradation.",
        ],
        "high": [
            "Severe RF interference causing excessive retransmissions on all SSIDs.",
            "AP CPU overloaded by captive portal, RADIUS, or IDS/IPS processing.",
            "Ethernet uplink saturated, causing backpressure into the wireless queue.",
            "Memory leak in AP firmware causing progressive slow-down.",
            "Radar detection (DFS) causing the AP to vacate the channel and scan.",
        ],
    },
    "firewall": {
        "medium": [
            "Session table approaching capacity, slowing new connection setup.",
            "Deep-packet inspection or IDS module adding processing overhead.",
            "SSL/TLS inspection consuming significant CPU for certificate handling.",
            "Logging pipeline saturated, delaying packet processing in logging-sync mode.",
            "HA state synchronisation adding inter-unit latency to each connection.",
        ],
        "high": [
            "Session table full, causing new flows to be queued or dropped.",
            "Under a volumetric attack that is consuming all inspection capacity.",
            "SSL inspection certificate store bloated, causing lookup delays.",
            "Hardware acceleration module fault, falling back to software inspection.",
            "Management-plane process (GUI, SNMP) consuming CPU intended for data-plane.",
        ],
    },
}

def _lat_causes(dtype: str, sev: str, scenario: dict) -> list[str]:
    dt_map = _LAT_CAUSES.get(dtype, {})
    return dt_map.get(sev, dt_map.get("medium", [
        "Network congestion or queuing delay on the path.",
        "Device CPU overloaded, delaying ICMP processing.",
        "Link saturation nearing capacity.",
        "QoS misconfiguration deprioritising control traffic.",
    ]))

_LAT_ACTIONS_MEDIUM = [
    "Review interface utilisation graphs for the past hour to identify bandwidth saturation.",
    "Check CPU utilisation on the device and identify any runaway processes.",
    "Inspect QoS policies to confirm management and ICMP traffic are correctly prioritised.",
    "Run a traceroute from the monitoring host and compare per-hop latency.",
    "Monitor for the next 15 minutes; escalate if latency continues to rise.",
]
_LAT_ACTIONS_HIGH = [
    "Immediately check interface utilisation — look for a bandwidth spike or microbursting.",
    "Capture a brief packet trace on the uplink to identify the traffic source causing congestion.",
    "Divert or rate-limit bulk flows (backup jobs, software updates) if they are the cause.",
    "Review hardware queue drop counters on the uplink interface.",
    "Escalate to the network team if no clear cause is found within 10 minutes; latency at this level impacts live services.",
    "Consider temporarily increasing QoS priority for critical traffic while the cause is investigated.",
]

def build_high_latency(s: dict) -> str:
    lat  = s["latency_ms"]
    loss = s["packet_loss_pct"]
    sev  = s["severity"]
    dtype = s["device_type"]
    dur  = s["duration_minutes"]

    if sev == "medium":
        tmpl = _pick(_LAT_EXPLAIN_MED, s)
        explain = tmpl.format(lat=lat, loss=loss)
        actions = _LAT_ACTIONS_MEDIUM
    else:
        tmpl = _pick(_LAT_EXPLAIN_HIGH, s)
        explain = tmpl.format(lat=lat, loss=loss, x=lat/500)
        actions = _LAT_ACTIONS_HIGH

    if dur >= 30:
        explain += f" This condition has persisted for {dur} minutes, suggesting a sustained rather than transient problem."
    elif dur <= 3:
        explain += f" The fault has been active for only {dur} minute(s); it may be a transient spike."

    causes  = _causes_list(_lat_causes(dtype, sev, s))
    actions_str = _actions_list(actions)
    return f"Explanation:\n{explain}\n\nLikely causes:\n{causes}\n\nRecommended actions:\n{actions_str}"

# ── HIGH_PACKET_LOSS ──────────────────────────────────────────────────────────
_LOSS_EXPLAIN_MED = [
    "Packet loss is {loss}%, above the 20% medium-severity threshold. Latency of {lat} ms is within normal bounds, suggesting the drop is occurring at a specific queue or interface rather than across the whole path.",
    "{loss}% of ICMP probes are being dropped, triggering a medium-severity alert. The latency of {lat} ms remains normal, which points to selective packet discard rather than general congestion.",
    "The monitoring system is observing {loss}% packet loss against the 20% threshold while round-trip time holds at {lat} ms. This pattern is consistent with a queue tail-drop policy or a flapping interface.",
    "One in approximately {ratio} packets is being dropped ({loss}% loss). Latency ({lat} ms) is normal, implying the link has capacity but some classification or queue mechanism is selectively discarding traffic.",
]
_LOSS_EXPLAIN_HIGH = [
    "{loss}% packet loss is far above the 50% high-severity threshold. At this rate, TCP sessions will stall, UDP streams will degrade severely, and network-dependent services may appear offline.",
    "More than half of all ICMP probes are failing ({loss}% loss). The round-trip time of {lat} ms does not reflect extreme congestion, which suggests a hardware error, port flap, or selective drop policy rather than pure bandwidth exhaustion.",
    "Packet loss has reached {loss}%, crossing the critical 50% high-severity boundary. With {consecutive} consecutive probe failures in this window, the path is effectively unreliable.",
    "A {loss}% packet loss rate means the network path to this device is deeply impaired. Even latency-tolerant protocols like DNS will experience failures at this level of loss.",
]
_LOSS_CAUSES = {
    "router": {
        "medium": [
            "Input queue drops on an interface due to a brief traffic burst.",
            "QoS policy tail-dropping low-priority traffic during peak load.",
            "CEF/FIB polarisation sending too much traffic through a single link in a bundle.",
            "Policer rate set too low on an ingress policy, discarding probe packets.",
            "Partial link failure causing intermittent CRC errors and retransmissions.",
        ],
        "high": [
            "Severe WAN congestion with sustained queue-full drops beyond the RED threshold.",
            "Hardware forwarding ASIC error causing a subset of flows to be dropped.",
            "Interface in half-duplex or duplex mismatch state causing collision-induced drops.",
            "Upstream ISP link experiencing impairment or capacity event.",
            "QoS misclassification assigning ICMP probe traffic to a heavily congested class.",
        ],
    },
    "switch": {
        "medium": [
            "Port microbursting exceeding the egress buffer threshold.",
            "Spanning-tree topology change triggering transient flooding and drops.",
            "VLAN mismatch causing some frames to be discarded at the trunk boundary.",
            "Layer 2 loop causing duplicate frames and MAC table instability.",
            "Egress port queue congestion for traffic destined for a slow uplink.",
        ],
        "high": [
            "Physical layer error on the cable (bent fibre, bad SFP) causing frame loss.",
            "Broadcast storm consuming all switching fabric bandwidth.",
            "TCAM hardware error dropping entire classes of traffic.",
            "PoE instability causing interface to cycle, losing packets during re-initialisation.",
            "Duplex mismatch between the switch port and its peer causing constant collisions.",
        ],
    },
    "server": {
        "medium": [
            "Receive ring buffer overrun when inbound traffic momentarily exceeds NIC processing.",
            "Interrupt throttling (NAPI budget) causing packets to be held and occasionally dropped.",
            "OS-level rate limiting (tc/qdisc) policy dropping excess traffic.",
            "NIC firmware bug causing intermittent descriptor underflow.",
            "CPU saturation preventing the kernel from draining the receive queue in time.",
        ],
        "high": [
            "NIC hardware fault or failing transceiver dropping most frames at the physical layer.",
            "Kernel memory pressure causing socket buffer allocation failures.",
            "Receive buffer exhaustion under a high-volume inbound connection burst.",
            "Network namespace or container veth pair misconfiguration dropping non-local traffic.",
            "MTU mismatch causing IP fragmentation drops at the server NIC.",
        ],
    },
    "access-point": {
        "medium": [
            "RF interference causing wireless retransmission failures that surface as ICMP loss.",
            "Client density too high, causing medium-contention retransmits to fill the retry limit.",
            "Hidden node problem causing collisions on the 2.4 GHz band.",
            "Background radar scan (DFS) briefly pausing the channel.",
            "Ethernet uplink experiencing intermittent link events.",
        ],
        "high": [
            "Near-complete RF failure or interference on all bands.",
            "Physical cable or SFP failure between the AP and switch.",
            "AP CPU overloaded to the point it cannot service the wireless queue.",
            "Association storm from a rogue or misbehaving client flooding the air.",
            "PoE power dropout causing the AP's NIC to reset intermittently.",
        ],
    },
    "firewall": {
        "medium": [
            "Session-rate limit reached, causing new connections (and associated probes) to be dropped.",
            "IDS/IPS signature match treating ICMP probes as a potential scan.",
            "Zone-based policy gap inadvertently dropping ICMP from the monitoring host.",
            "Connection tracker table nearing capacity, failing new state entries.",
            "Rate-limit rule applied to the monitoring source IP.",
        ],
        "high": [
            "Session table full — all new connections, including ICMP, are being rejected.",
            "Firewall under a DDoS or SYN-flood attack consuming all capacity.",
            "Hardware interface error causing physical-layer packet loss.",
            "Policy rule blocking ICMP type 0 (echo-reply) on the outbound interface.",
            "HA failover in progress causing momentary packet loss during state sync.",
        ],
    },
}

def _loss_causes(dtype: str, sev: str) -> list[str]:
    dt_map = _LOSS_CAUSES.get(dtype, {})
    return dt_map.get(sev, dt_map.get("medium", [
        "Physical layer errors on the cable or transceiver.",
        "Queue congestion causing tail-drop at the interface.",
        "Hardware fault in the forwarding engine.",
        "Policy or ACL inadvertently discarding probes.",
    ]))

_LOSS_ACTIONS_MEDIUM = [
    "Check interface input/output error counters for CRC, giants, or runts.",
    "Inspect the interface queue statistics for tail-drop or RED discards.",
    "Review QoS policy to confirm ICMP/monitoring traffic is not being policed.",
    "Run a sustained ping test from multiple hosts to determine if loss is source-specific.",
    "Monitor the interface utilisation trend to check for microburst patterns.",
]
_LOSS_ACTIONS_HIGH = [
    "Immediately review interface error counters — high physical errors indicate a cable or SFP issue.",
    "Replace or reseat the SFP/cable if CRC errors or input errors are climbing.",
    "Check for duplex mismatches with 'show interface' or equivalent.",
    "Capture traffic on the upstream switch port to identify if loss originates there.",
    "Consider failing over to a redundant path if available, while the root cause is identified.",
    "Escalate to the network team; greater than 50% loss is a service-impacting event.",
]

def build_high_packet_loss(s: dict) -> str:
    loss = s["packet_loss_pct"]
    lat  = s["latency_ms"]
    sev  = s["severity"]
    dtype = s["device_type"]
    fails = s["consecutive_failures"]

    if sev == "medium":
        tmpl = _pick(_LOSS_EXPLAIN_MED, s)
        explain = tmpl.format(loss=loss, lat=lat, ratio=round(100/max(loss,1),1))
        actions = _LOSS_ACTIONS_MEDIUM
    else:
        tmpl = _pick(_LOSS_EXPLAIN_HIGH, s)
        explain = tmpl.format(loss=loss, lat=lat, consecutive=fails)
        actions = _LOSS_ACTIONS_HIGH

    # contextual note about latency
    if lat < 50 and sev == "high":
        explain += " The low latency ({lat} ms) for surviving packets suggests the loss is due to selective discard (queue policy, hardware error) rather than path congestion.".format(lat=lat)

    causes      = _causes_list(_loss_causes(dtype, sev))
    actions_str = _actions_list(actions)
    return f"Explanation:\n{explain}\n\nLikely causes:\n{causes}\n\nRecommended actions:\n{actions_str}"

# ── HIGH_CPU_USAGE ────────────────────────────────────────────────────────────
_CPU_EXPLAIN_HIGH = [
    "CPU utilisation has reached {cpu}%, above the 80% high-severity threshold, and has been sustained for {dur} minutes. At this level the device may begin dropping control-plane packets, slow convergence, and fail to service management requests promptly.",
    "The device is reporting {cpu}% CPU usage, crossing the 80% warning mark. Sustained high CPU on {role} can degrade routing protocol timers, slow policy lookups, and cause intermittent management timeouts.",
    "CPU load stands at {cpu}% (threshold: 80%). While the device remains functional, {dur} minutes of sustained load at this level risks destabilising protocol adjacencies and slowing failover detection.",
    "At {cpu}% CPU utilisation above the 80% threshold, the device process scheduler is running near capacity. Interrupt and timer-driven operations — such as routing keepalives — become unreliable.",
]
_CPU_EXPLAIN_CRIT = [
    "CPU utilisation is {cpu}% — above the 90% critical threshold. The device is effectively saturated; control-plane functions are at serious risk of failure, and packet forwarding may be falling back to the software path.",
    "A {cpu}% CPU reading, {x:.0f} points above the critical 90% boundary, indicates that the device cannot service all scheduled tasks. Protocol adjacencies may drop, and management access may be completely unresponsive.",
    "Critical CPU saturation at {cpu}% has persisted for {dur} minutes. At this level the device operating system cannot honour all timer and interrupt requests, risking BGP/OSPF neighbour loss, STP instability, or RADIUS timeout.",
    "The device CPU is pegged at {cpu}%, well into the critical zone above 90%. Any latency in the scheduler at this point can cascade into protocol failures that take minutes to recover after the CPU pressure is relieved.",
]
_CPU_CAUSES = {
    "router": [
        "BGP or OSPF route table recalculation caused by an upstream topology change.",
        "Unoptimised ACL forcing process switching for matched flows instead of hardware forwarding.",
        "High-volume NetFlow, sFlow, or SNMP polling consuming management-plane CPU.",
        "Routing protocol flap triggering SPF calculations in a tight loop.",
        "Crypto engine saturation from IPsec or SSL VPN encryption.",
    ],
    "switch": [
        "Spanning-tree TCN storm triggering mass MAC table flushes.",
        "Broadcast or multicast storm consuming CPU for flooding decisions.",
        "IGMP/MLD snooping table exhaustion causing software-path processing.",
        "SNMP or LLDP polling overhead on a heavily loaded management plane.",
        "Port security violation logging consuming excessive CPU cycles.",
    ],
    "server": [
        "Runaway daemon or user process consuming disproportionate CPU time.",
        "Backup job, antivirus scan, or log rotation running during peak hours.",
        "Memory pressure causing excessive kernel time in the page reclaim path.",
        "DDoS or brute-force attack causing high system-call overhead.",
        "Java or Python garbage collection pause causing CPU spikes.",
    ],
    "access-point": [
        "High client count causing excessive 802.11 management frame processing.",
        "IDS/WIDS signature scanning consuming the AP's limited CPU.",
        "Background channel scan or spectrum analysis running concurrently.",
        "Captive portal or RADIUS accounting process looping on a failed upstream.",
        "Firmware memory leak forcing excessive garbage collection on the embedded OS.",
    ],
    "firewall": [
        "Deep-packet inspection or IDS/IPS engine processing a high-volume flow.",
        "SSL/TLS decryption and re-encryption consuming the crypto co-processor.",
        "Session table at capacity, forcing per-packet state lookups in software.",
        "Under a volumetric attack that is exhausting connection-rate processing.",
        "Log buffering saturated, causing the logging process to consume CPU while flushing.",
    ],
    "other": [
        "Runaway process or misconfigured service consuming excessive CPU.",
        "Heavy management polling (SNMP, NetFlow) overhead.",
        "Cryptographic operations or packet inspection at software path.",
        "Scheduled task (update, scan) running during peak hours.",
    ],
}
_CPU_ACTIONS_HIGH = [
    "Run 'show processes cpu' (or equivalent) to identify the top CPU consumers.",
    "Check for routing protocol flaps — a sudden topology change can trigger sustained SPF/RIB recalculation.",
    "Review SNMP polling intervals; a polling storm can peg management-plane CPU.",
    "Identify any recent configuration change that may have disabled hardware-assisted forwarding.",
    "Monitor every 2 minutes; if CPU stays above 80% for over 15 minutes, escalate.",
]
_CPU_ACTIONS_CRIT = [
    "Immediately identify the top CPU-consuming process using the device's process monitor.",
    "Check routing neighbour tables — if adjacencies are flapping, the SPF storm is the cause.",
    "Reduce SNMP polling frequency or disable non-essential polling until CPU normalises.",
    "If a specific process is the culprit, consider restarting it (with change-control approval).",
    "Prepare to failover to a redundant device if CPU does not drop within 5 minutes.",
    "Engage the network operations team immediately — critical CPU on a {role} risks a service outage.",
]

def build_high_cpu(s: dict) -> str:
    cpu  = s["cpu_pct"]
    mem  = s["memory_pct"]
    sev  = s["severity"]
    dtype = s["device_type"]
    dur  = s["duration_minutes"]
    role = device_role(dtype)

    if sev == "critical":
        tmpl = _pick(_CPU_EXPLAIN_CRIT, s)
        explain = tmpl.format(cpu=cpu, dur=dur, x=cpu-90, role=role)
        actions = [a.format(role=role) for a in _CPU_ACTIONS_CRIT]
    else:
        tmpl = _pick(_CPU_EXPLAIN_HIGH, s)
        explain = tmpl.format(cpu=cpu, dur=dur, role=role)
        actions = _CPU_ACTIONS_HIGH

    if mem is not None and mem >= 80:
        explain += f" Memory usage is also elevated at {mem}%, compounding the risk."
    elif mem is not None and mem >= 60:
        explain += f" Memory is at {mem}% — not yet at threshold, but worth monitoring alongside CPU."

    causes      = _causes_list(_CPU_CAUSES.get(dtype, _CPU_CAUSES["other"]))
    actions_str = _actions_list(actions)
    return f"Explanation:\n{explain}\n\nLikely causes:\n{causes}\n\nRecommended actions:\n{actions_str}"

# ── HIGH_MEMORY_USAGE ─────────────────────────────────────────────────────────
_MEM_EXPLAIN_HIGH = [
    "Memory usage is {mem}%, above the 80% high-severity threshold, after {dur} minutes. As free memory shrinks, the device will increasingly rely on buffer reuse and may begin dropping sessions or routes.",
    "The device is utilising {mem}% of available memory, crossing the 80% warning mark. Reduced free memory limits the operating system's ability to respond to traffic bursts and can cause routing table truncation.",
    "At {mem}% memory utilisation (threshold: 80%), the device has limited headroom before it must begin aggressively reclaiming buffers or dropping cached state.",
    "Memory consumption of {mem}% is above the 80% alert level. For {role}, this may constrain the size of connection-tracking tables, routing caches, or application heaps.",
]
_MEM_EXPLAIN_CRIT = [
    "Memory usage has reached {mem}%, crossing the critical 90% boundary. The device is nearly out of usable memory; any additional allocation may fail, causing processes to crash or the device to reload.",
    "At {mem}% memory utilisation — {x:.0f} points above critical — the device OS is likely swapping or forcibly reclaiming buffers. This produces latency spikes and may corrupt in-flight sessions.",
    "Critical memory pressure ({mem}%) means the device has only {free:.1f}% of RAM free. Routing entries, session state, or application heap allocations are at risk of being evicted or failing outright.",
    "The device is at {mem}% memory utilisation, exceeding the 90% critical threshold. Uncontrolled memory growth at this level typically ends in an OOM-triggered crash or watchdog reboot.",
]
_MEM_CAUSES = {
    "router": [
        "BGP full-table route count growing beyond the original memory allocation.",
        "Memory leak in an IOS/NX-OS process that has accumulated over days of uptime.",
        "MPLS VPN label database expansion consuming prefix memory.",
        "NetFlow cache not being exported and flushed promptly, growing unbounded.",
        "Excessive number of ACL entries compiled into TCAM memory.",
    ],
    "switch": [
        "MAC address table grown to capacity due to many connected endpoints.",
        "ARP/ND cache not being aged out, growing for every unique IP seen.",
        "IGMP snooping state for a large number of multicast groups.",
        "Spanning-tree topology table retaining stale entries after topology changes.",
        "sFlow or ERSPAN buffer consuming switch CPU memory.",
    ],
    "server": [
        "Application memory leak — heap grows over time without being released.",
        "Too many concurrent connections holding socket buffers open.",
        "JVM or Python runtime not aggressively GC-ing, allowing heap to grow.",
        "Tmpfs or page cache consuming memory that is not being reclaimed.",
        "Runaway process forking many child processes each with its own memory map.",
    ],
    "access-point": [
        "Client association table retaining stale entries after clients disconnect.",
        "Firmware memory leak that grows with uptime, cleared only by reboot.",
        "Large number of associated clients each requiring per-client state.",
        "Captive portal session database not being pruned.",
        "WIDS/ROGUE detection table not aging out old observed APs.",
    ],
    "firewall": [
        "Connection tracking table retaining TIME_WAIT states too long.",
        "SSL inspection certificate cache growing without eviction.",
        "IDS/IPS signature database update increasing baseline memory footprint.",
        "Log buffer allocated too large, consuming free memory.",
        "HA state synchronisation holding a full copy of the session table in RAM.",
    ],
    "other": [
        "Application or process memory leak over time.",
        "Large number of concurrent sessions consuming per-session state.",
        "Routing or forwarding table growth exceeding initial memory allocation.",
        "OS page cache growing and not being reclaimed promptly.",
    ],
}
_MEM_ACTIONS_HIGH = [
    "Identify the top memory-consuming processes using 'show memory' or platform equivalents.",
    "Check the device uptime — a long-running device may be accumulating a slow memory leak.",
    "Review routing table size and compare to the device's recommended maximum.",
    "Schedule a maintenance window reboot if memory continues to climb without a clear cause.",
    "Set an alert to escalate automatically if memory crosses 90% before the next check.",
]
_MEM_ACTIONS_CRIT = [
    "Immediately identify the memory allocation per process — look for the largest consumer.",
    "Check if swapping is active; swap usage on a network device often precedes a crash.",
    "Clear any clearable caches (ARP, route cache, log buffers) if the platform supports it.",
    "Begin planning an emergency failover or controlled reload before an uncontrolled crash occurs.",
    "Engage the network operations team — critical memory pressure risks an imminent reload.",
    "After recovery, conduct a post-mortem to identify whether a leak or an oversized table caused the event.",
]

def build_high_memory(s: dict) -> str:
    mem  = s["memory_pct"]
    cpu  = s["cpu_pct"]
    sev  = s["severity"]
    dtype = s["device_type"]
    dur  = s["duration_minutes"]
    role = device_role(dtype)
    free = 100 - mem

    if sev == "critical":
        tmpl = _pick(_MEM_EXPLAIN_CRIT, s)
        explain = tmpl.format(mem=mem, x=mem-90, free=free, dur=dur, role=role)
        actions = _MEM_ACTIONS_CRIT
    else:
        tmpl = _pick(_MEM_EXPLAIN_HIGH, s)
        explain = tmpl.format(mem=mem, dur=dur, role=role)
        actions = _MEM_ACTIONS_HIGH

    if cpu is not None and cpu >= 80:
        explain += f" CPU is also under pressure at {cpu}%, which may indicate memory pressure is causing excessive paging or buffer management overhead."
    elif cpu is not None and cpu >= 60:
        explain += f" CPU is at {cpu}%, which is worth watching—memory pressure can eventually drive CPU up as the OS spends more time in memory management."

    causes      = _causes_list(_MEM_CAUSES.get(dtype, _MEM_CAUSES["other"]))
    actions_str = _actions_list(actions)
    return f"Explanation:\n{explain}\n\nLikely causes:\n{causes}\n\nRecommended actions:\n{actions_str}"

# ── combined fault builders ───────────────────────────────────────────────────
def build_latency_and_loss(s: dict) -> str:
    lat  = s["latency_ms"]
    loss = s["packet_loss_pct"]
    sev  = s["severity"]
    dtype = s["device_type"]
    dur  = s["duration_minutes"]

    if sev == "medium":
        explain = (
            f"Both latency ({lat} ms) and packet loss ({loss}%) are simultaneously elevated "
            f"above their respective medium thresholds (200 ms / 20%). "
            f"The co-occurrence of these two metrics over {dur} minutes indicates path-level "
            f"congestion rather than a single isolated metric anomaly."
        )
    else:
        explain = (
            f"Latency has risen to {lat} ms and packet loss to {loss}% — both well above "
            f"their high-severity thresholds (500 ms / 50%). "
            f"This combined pattern is characteristic of severe link congestion, a hardware fault, "
            f"or a partial path failure. "
            f"At {loss}% loss, TCP sessions will stall and VoIP/video streams will be unusable. "
            f"The elevated latency of surviving packets ({lat} ms) confirms the path is still "
            f"partially functional but deeply impaired."
        )

    causes = _causes_list([
        f"Link congestion: the path to the {dtype} is saturated, causing both queuing delay and tail-drop.",
        "Duplex mismatch or physical layer error causing retransmissions that inflate latency and discard packets.",
        "Faulty cable, SFP, or patch-panel connection intermittently disrupting frames.",
        "An upstream device (router or switch) in the path experiencing its own CPU or queue issue.",
        "Routing instability causing traffic to traverse a longer, lower-bandwidth path.",
    ])
    if sev == "high":
        actions_list = [
            "Run interface error counters on every hop in the path to the device.",
            "Identify if a new bulk flow (backup, video stream) has appeared on the same link.",
            "Check for duplex mismatch symptoms (half-duplex counters, CRC errors, runt frames).",
            "Consider re-routing traffic to a redundant path while investigating.",
            "Escalate immediately — combined high latency and high loss causes service outages.",
        ]
    else:
        actions_list = [
            "Check interface utilisation graphs for the segments between monitor and device.",
            "Review QoS policy to see if probe traffic is in a congested queue.",
            "Run a traceroute and measure per-hop latency to isolate which segment is congested.",
            "Monitor for 10 minutes; both metrics rising together suggests an active congestion condition.",
        ]
    return (
        f"Explanation:\n{explain}\n\n"
        f"Likely causes:\n{causes}\n\n"
        f"Recommended actions:\n{_actions_list(actions_list)}"
    )

def build_cpu_and_memory(s: dict) -> str:
    cpu  = s["cpu_pct"]
    mem  = s["memory_pct"]
    sev  = s["severity"]
    dtype = s["device_type"]
    dur  = s["duration_minutes"]
    role = device_role(dtype)

    if sev == "critical":
        explain = (
            f"Both CPU ({cpu}%) and memory ({mem}%) have simultaneously crossed the critical 90% threshold "
            f"on this {dtype}, which serves as {role}. "
            f"After {dur} minutes at this level, the device's ability to maintain protocol adjacencies, "
            f"process management requests, and forward packets reliably is severely compromised. "
            f"An uncontrolled crash or watchdog reboot is a real risk."
        )
    else:
        explain = (
            f"CPU and memory are both above the 80% high-severity threshold "
            f"(CPU: {cpu}%, memory: {mem}%), persisting for {dur} minutes. "
            f"The combination suggests the system is under sustained workload pressure rather than "
            f"a single runaway process, since memory growth typically follows from high CPU activity "
            f"(process forks, connection-state growth, cache accumulation)."
        )

    causes = _causes_list([
        f"A runaway process on the {dtype} consuming both CPU cycles and heap memory.",
        "A large routing or session table growth that requires both CPU lookups and memory allocation.",
        "A recent software update or feature activation increasing the baseline resource footprint.",
        "An external event (topology change, attack, configuration push) driving simultaneous CPU and memory spikes.",
        "Long uptime with a slow memory leak, now also consuming CPU for garbage collection or swap management.",
    ])
    if sev == "critical":
        actions_list = [
            "Identify top resource consumers immediately via the device's process monitor.",
            "Check if any recently pushed configuration or software version change correlates with the onset.",
            "Begin controlled failover planning if CPU and memory do not start declining in the next 5 minutes.",
            "Attempt to restart the identified runaway process under change control.",
            "Engage vendor support for memory dump analysis if the cause is unclear.",
            "After stabilisation, review the device's resource allocation and upgrade hardware if warranted.",
        ]
    else:
        actions_list = [
            "Identify which process is consuming the most CPU and the most memory.",
            "Review uptime — a device running for many weeks without reboot may be accumulating a slow leak.",
            "Check for a recent spike in connections, routes, or clients that could explain the increase.",
            "Set a 15-minute re-check; if both metrics continue to rise, escalate and begin failover preparation.",
            "Consider scheduling a maintenance window reboot if no specific cause is identified.",
        ]
    return (
        f"Explanation:\n{explain}\n\n"
        f"Likely causes:\n{causes}\n\n"
        f"Recommended actions:\n{_actions_list(actions_list)}"
    )

def build_latency_with_cpu(s: dict) -> str:
    lat  = s["latency_ms"]
    cpu  = s["cpu_pct"]
    sev  = s["severity"]
    dtype = s["device_type"]
    dur  = s["duration_minutes"]
    role = device_role(dtype)

    explain = (
        f"Latency to the device is {lat} ms (threshold: {'500 ms high' if sev == 'high' else '200 ms medium'}) "
        f"while CPU is at {cpu}% (threshold: {'90% critical' if cpu >= 90 else '80% high'}). "
        f"This combination is significant: CPU saturation on {role} often causes latency because "
        f"ICMP echo-reply processing is handled by the control plane, which is the first thing to "
        f"suffer when the CPU is overloaded. The fault has persisted for {dur} minutes."
    )
    causes = _causes_list([
        f"Control-plane CPU saturation causing the {dtype} to delay ICMP echo-reply handling.",
        "A heavy process (route recalculation, config parsing, crypto) monopolising CPU and indirectly inflating latency.",
        "Process switching instead of hardware forwarding, adding per-packet CPU overhead that raises latency.",
        "Management polling (SNMP, syslog flushing) competing with forwarding tasks.",
        "A control-plane attack (e.g. crafted BGP UPDATEs) consuming CPU and degrading response times.",
    ])
    actions_list = [
        "Check the top CPU processes first — resolving the CPU issue should bring latency down.",
        "Verify whether ICMP responses are process-switched or hardware-switched on this platform.",
        "Review routing protocol adjacency logs for flaps that could be driving SPF recalculations.",
        "Reduce management polling to give the control plane more headroom.",
        "If latency persists after CPU normalises, investigate the network path independently.",
    ]
    return (
        f"Explanation:\n{explain}\n\n"
        f"Likely causes:\n{causes}\n\n"
        f"Recommended actions:\n{_actions_list(actions_list)}"
    )

def build_unreachable_with_loss(s: dict) -> str:
    # Reuse the unreachable builder — the "+HIGH_PACKET_LOSS" annotation reflects
    # that the device went unreachable after progressive loss, but the state is
    # now total loss (100%).
    base = build_unreachable(s)
    addendum = (
        " This fault is annotated as a progression through high packet loss to "
        "full unreachability, suggesting a gradual path failure rather than an "
        "instantaneous event (e.g. a flapping interface or degrading cable)."
    )
    # inject addendum after the first paragraph of Explanation
    return base.replace("\n\nLikely causes:", addendum + "\n\nLikely causes:", 1)

# ── dispatch ──────────────────────────────────────────────────────────────────
def build_output(s: dict) -> str:
    ft = s["fault_type"]
    if ft == "DEVICE_UNREACHABLE":
        return build_unreachable(s)
    if ft == "HIGH_LATENCY":
        return build_high_latency(s)
    if ft == "HIGH_PACKET_LOSS":
        return build_high_packet_loss(s)
    if ft == "HIGH_CPU_USAGE":
        return build_high_cpu(s)
    if ft == "HIGH_MEMORY_USAGE":
        return build_high_memory(s)
    if ft == "HIGH_LATENCY+HIGH_PACKET_LOSS":
        return build_latency_and_loss(s)
    if ft == "HIGH_CPU_USAGE+HIGH_MEMORY_USAGE":
        return build_cpu_and_memory(s)
    if ft == "HIGH_LATENCY+HIGH_CPU_USAGE":
        return build_latency_with_cpu(s)
    if ft == "DEVICE_UNREACHABLE+HIGH_PACKET_LOSS":
        return build_unreachable_with_loss(s)
    raise ValueError(f"Unknown fault_type: {ft}")

def scenario_to_input(s: dict) -> str:
    """Render a scenario dict as a structured plain-text block."""
    lines = [
        f"Device: {s['device_name']} ({s['device_type']})",
        f"Fault type: {s['fault_type']}",
        f"Severity: {s['severity']}",
    ]
    if s.get("latency_ms") is not None:
        lines.append(f"Latency: {s['latency_ms']} ms")
    if s.get("packet_loss_pct") is not None:
        lines.append(f"Packet loss: {s['packet_loss_pct']}%")
    if s.get("cpu_pct") is not None:
        lines.append(f"CPU usage: {s['cpu_pct']}%")
    if s.get("memory_pct") is not None:
        lines.append(f"Memory usage: {s['memory_pct']}%")
    if s.get("consecutive_failures"):
        lines.append(f"Consecutive ICMP failures: {s['consecutive_failures']}")
    lines.append(f"Fault duration: {s['duration_minutes']} minutes")
    return "\n".join(lines)

def scenario_to_example(s: dict) -> dict:
    return {
        "instruction": INSTRUCTION,
        "input":       scenario_to_input(s),
        "output":      build_output(s),
    }

# ── stratified split ──────────────────────────────────────────────────────────
def stratified_split(
    examples: list[dict],
    labels: list[str],
    train_ratio: float,
    val_ratio: float,
    seed: int,
) -> tuple[list[dict], list[dict], list[dict]]:
    rng = random.Random(seed)
    by_label: dict[str, list[int]] = defaultdict(list)
    for i, lbl in enumerate(labels):
        by_label[lbl].append(i)

    train_idx, val_idx, test_idx = [], [], []
    for lbl, idxs in by_label.items():
        shuffled = list(idxs)
        rng.shuffle(shuffled)
        n = len(shuffled)
        n_train = max(1, round(n * train_ratio))
        n_val   = max(1, round(n * val_ratio))
        train_idx.extend(shuffled[:n_train])
        val_idx.extend(shuffled[n_train:n_train + n_val])
        test_idx.extend(shuffled[n_train + n_val:])

    return (
        [examples[i] for i in train_idx],
        [examples[i] for i in val_idx],
        [examples[i] for i in test_idx],
    )

# ── main ──────────────────────────────────────────────────────────────────────
def main():
    # 1. Load generated scenarios
    with SCENARIOS.open() as f:
        scenarios = [json.loads(l) for l in f]

    examples = [scenario_to_example(s) for s in scenarios]
    labels   = [s["fault_type"] for s in scenarios]

    # 2. Load handwritten seeds (if present)
    seed_examples: list[dict] = []
    if SEED_FILE.exists():
        with SEED_FILE.open() as f:
            for line in f:
                line = line.strip()
                if line:
                    seed_examples.append(json.loads(line))
        print(f"Loaded {len(seed_examples)} handwritten seed examples.")
    else:
        print("No handwritten seed file found; skipping.")

    # Merge seeds (add before splitting so they land in train)
    # We label seeds with their extracted fault_type or "SEED" fallback
    seed_labels = []
    for e in seed_examples:
        # Try to pull fault type from the input block
        ft = "SEED"
        for line in e.get("input", "").splitlines():
            if line.startswith("Fault type:"):
                ft = line.split(":", 1)[1].strip()
                break
        seed_labels.append(ft)

    all_examples = examples + seed_examples
    all_labels   = labels   + seed_labels

    # 3. Write full dataset
    DATASET_OUT.parent.mkdir(parents=True, exist_ok=True)
    with DATASET_OUT.open("w") as f:
        for ex in all_examples:
            f.write(json.dumps(ex) + "\n")
    print(f"Full dataset: {len(all_examples)} examples -> {DATASET_OUT}")

    # 4. Stratified split
    train, val, test = stratified_split(
        all_examples, all_labels, TRAIN_RATIO, VAL_RATIO, seed=SPLIT_SEED
    )

    for path, split in [(TRAIN_OUT, train), (VAL_OUT, val), (TEST_OUT, test)]:
        with path.open("w") as f:
            for ex in split:
                f.write(json.dumps(ex) + "\n")

    total = len(train) + len(val) + len(test)
    print(f"Split: train={len(train)} ({len(train)/total:.0%})  "
          f"val={len(val)} ({len(val)/total:.0%})  "
          f"test={len(test)} ({len(test)/total:.0%})")
    print(f"  -> {TRAIN_OUT.name}, {VAL_OUT.name}, {TEST_OUT.name}")

if __name__ == "__main__":
    main()
