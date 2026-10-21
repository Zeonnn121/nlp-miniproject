"""Turn scenarios.jsonl + handwritten_seed.jsonl into instruction-tuning examples.

Outputs:
  llm/data/dataset.jsonl        -- full merged set
  llm/data/train.jsonl          -- 80 % stratified by fault_type
  llm/data/val.jsonl            -- 10 %
  llm/data/test.jsonl           -- 10 %

Usage:
  python llm/scripts/build_dataset.py
"""

from __future__ import annotations

import json
import random
from collections import defaultdict
from pathlib import Path

# -- paths --------------------------------------------------------------------
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

SUSTAINED_MIN = 20  # minutes; below this we don't call a fault "sustained"

# -- static instruction -------------------------------------------------------
INSTRUCTION = (
    "You are a network operations assistant. "
    "Given a fault event detected on a network device, produce a structured explanation "
    "with three clearly labelled sections: "
    "'Explanation' (what is happening and why it matters, referencing the specific metrics), "
    "'Likely causes' (ranked list of probable root causes for this device type and fault pattern), "
    "and 'Recommended actions' (concrete remediation steps in priority order)."
)

# -- helpers ------------------------------------------------------------------

def _pick(bank: list, scenario: dict) -> str:
    """Deterministic pick so re-runs produce identical output."""
    key = json.dumps(scenario, sort_keys=True)
    return bank[hash(key) % len(bank)]


def _pick_i(bank: list, scenario: dict, i: int) -> str:
    """Per-slot pick: same scenario produces different choices for different slot indices."""
    key = json.dumps(scenario, sort_keys=True) + str(i)
    return bank[hash(key) % len(bank)]


def _mins(dur: float) -> str:
    """'1 minute' vs '5 minutes' -- no more minute(s) hack."""
    n = int(dur)
    return f"{n} minute" if n == 1 else f"{n} minutes"


def _duration_note(dur: float, long_prefix: str = "") -> str:
    """Append a duration qualifier only when it adds information.

    Returns '' for boring mid-range durations so we don't pad every output.
    """
    if dur >= SUSTAINED_MIN:
        prefix = long_prefix or "This condition has persisted"
        return f" {prefix} for {_mins(dur)}, suggesting a sustained rather than transient problem."
    if dur <= 3:
        return f" The fault has been active for only {_mins(dur)}; it may be a transient spike."
    return ""


def _causes_list(causes: list[str]) -> str:
    return "\n".join(f"{i+1}. {c}" for i, c in enumerate(causes))


def _actions_list(actions: list[str]) -> str:
    return "\n".join(f"{i+1}. {a}" for i, a in enumerate(actions))


# -- severity adjectives ------------------------------------------------------
SEV_ADJ = {
    "medium":   ["elevated", "moderate", "notable", "above-threshold", "borderline"],
    "high":     ["high", "significant", "concerning", "serious", "well above normal"],
    "critical": ["critical", "severe", "alarming", "dangerously high", "at a critical level"],
}

def sev_adj(sev: str, scenario: dict) -> str:
    return _pick(SEV_ADJ.get(sev, SEV_ADJ["high"]), scenario)


# -- device-type context ------------------------------------------------------
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


# == DEVICE_UNREACHABLE =======================================================
_UNREACH_EXPLAIN = [
    "The device has stopped responding to all ICMP probes "
    "({failures} consecutive failures over {dur} minutes), indicating it is completely "
    "unreachable from the monitoring host.",

    "ICMP monitoring lost contact with the device after {failures} consecutive failed probes "
    "spanning {dur} minutes. No echo replies are being received.",

    "All {failures} ping attempts over a {dur}-minute window returned no response. "
    "The device appears to be offline or isolated from the monitoring network.",

    "The monitoring system received no ICMP echo reply across {failures} consecutive probes "
    "during a {dur}-minute outage window, classifying this as a critical unreachability event.",

    "After {failures} unanswered ICMP probes over {dur} minutes the device is classified as "
    "unreachable. No partial responses or degraded replies were observed -- the failure is total.",

    "Monitoring has registered {failures} back-to-back probe failures over the past {dur} minutes. "
    "The absence of any ICMP echo reply means the device cannot be confirmed operational "
    "from the network perspective.",
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


def build_unreachable(s: dict) -> str:
    dtype = s["device_type"]
    dur   = s["duration_minutes"]
    fails = s["consecutive_failures"]

    explain_tmpl = _pick(_UNREACH_EXPLAIN, s)
    explain = explain_tmpl.format(failures=fails, dur=int(dur))
    explain += _duration_note(dur, "The outage has continued")

    causes  = _causes_list(_UNREACH_CAUSES.get(dtype, _UNREACH_CAUSES["other"]))
    actions = _actions_list(_UNREACH_ACTIONS.get(dtype, _UNREACH_ACTIONS["other"]))
    return (
        f"Explanation:\n{explain}\n\n"
        f"Likely causes:\n{causes}\n\n"
        f"Recommended actions:\n{actions}"
    )


# == HIGH_LATENCY =============================================================
_LAT_EXPLAIN_MED = [
    "Round-trip latency to the device is {lat} ms, which exceeds the medium-severity "
    "threshold of 200 ms. Packet loss is negligible at {loss}%, so the link is stable "
    "but slow.",

    "ICMP probes are returning in {lat} ms -- above the 200 ms warning level -- while "
    "packet delivery remains intact ({loss}% loss). The device is reachable but "
    "experiencing degraded response times.",

    "Latency has climbed to {lat} ms, crossing the 200 ms medium threshold. "
    "With only {loss}% packet loss the underlying link appears healthy; "
    "the delay is likely caused by processing or queuing overhead.",

    "The device is responding to pings in {lat} ms, crossing the medium-severity "
    "threshold of 200 ms. Low packet loss ({loss}%) suggests the path is congested "
    "rather than failing.",

    "A {lat} ms round-trip time has triggered the medium-severity latency alert "
    "(threshold: 200 ms). The {loss}% packet loss confirms the path remains functional; "
    "this is a performance problem, not a connectivity failure.",

    "Monitoring records {lat} ms average latency against the 200 ms medium-severity limit. "
    "Packet loss stands at {loss}%, well within normal bounds, pointing to queuing or "
    "processing delay as the likely cause rather than link failure.",
]

_LAT_EXPLAIN_HIGH = [
    "Latency has risen to {lat} ms, well above the high-severity threshold of 500 ms. "
    "Even with minimal packet loss ({loss}%), response times at this level indicate "
    "serious congestion or processing bottlenecks.",

    "Round-trip time to the device is {lat} ms -- {x:.1f}x the 500 ms high threshold. "
    "Packet loss is {loss}%, meaning packets are arriving but with severely degraded timing.",

    "ICMP probes are taking {lat} ms to return, triggering a high-severity latency fault "
    "(threshold: 500 ms). At this level user-facing applications will experience timeouts "
    "and retransmissions.",

    "The monitoring system recorded a round-trip latency of {lat} ms against the "
    "500 ms high-severity limit. The {loss}% packet loss figure confirms the path is "
    "still functional but heavily congested.",

    "At {lat} ms the device is {x:.1f}x slower to respond than the 500 ms high-severity "
    "threshold allows. Packet loss of {loss}% is secondary; the latency alone constitutes "
    "a high-severity event with direct user-visible impact.",

    "High-severity latency detected: {lat} ms observed vs 500 ms threshold. "
    "Despite {loss}% packet loss the path is not down -- but at {lat} ms, "
    "interactive sessions and time-sensitive protocols will be severely impaired.",
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

def _lat_causes(dtype: str, sev: str) -> list[str]:
    dt_map = _LAT_CAUSES.get(dtype, {})
    return dt_map.get(sev, dt_map.get("medium", [
        "Network congestion or queuing delay on the path.",
        "Device CPU overloaded, delaying ICMP processing.",
        "Link saturation nearing capacity.",
        "QoS misconfiguration deprioritising control traffic.",
    ]))

# Per-slot banks for latency-medium actions (5 slots, 10+ alternatives each).
# Use _pick_i(bank, s, slot_index) so each slot picks independently.
_LAT_ACTIONS_MED_BANKS = [
    # slot 0: utilisation / data collection
    [
        "Review interface utilisation graphs for the past hour to identify bandwidth saturation.",
        "Pull interface utilisation data for the last 30 minutes and look for a pattern correlating with the latency onset.",
        "Check SNMP counters for input/output rates on uplink interfaces; compare against contracted bandwidth.",
        "Export interface statistics from the monitoring tool and graphing tool for the affected segment.",
        "Gather historical utilisation baselines from the NMS to confirm whether this latency level is new or recurring.",
        "Review MRTG or equivalent graphs for the upstream interface; look for a rate spike at the time of alert onset.",
        "Pull bandwidth utilisation charts from the NMS for the last 2 hours and compare peak values against link capacity.",
        "Run 'show interface counters' on the uplink and note input/output rate against configured bandwidth.",
        "Query the SNMP ifInOctets/ifOutOctets OIDs for the path interfaces to calculate real-time utilisation.",
        "Check cloud or NOC dashboard for the uplink segment to see traffic volume trends.",
    ],
    # slot 1: device CPU / process check
    [
        "Check CPU utilisation on the device and identify any runaway processes.",
        "Inspect the device's process scheduler for any high-CPU process that could be stealing forwarding cycles.",
        "Run 'show processes cpu' or equivalent and note any process above 20% CPU for more than 5 seconds.",
        "Verify that SNMP polling, NetFlow export, or logging processes are not consuming excessive CPU.",
        "Review whether a recent configuration push or software update changed the CPU baseline on this device.",
        "Check for memory pressure on the device -- a low-memory state can cause software-path forwarding, increasing latency.",
        "Inspect the control-plane policing rate; a saturated CoPP queue can delay ICMP responses.",
        "Run a hardware diagnostic if the device supports it to rule out ASIC forwarding-plane issues.",
        "Confirm the device is running CEF or hardware forwarding, not process-switched forwarding.",
        "Check whether a scheduled task (backup, log rotation) coincides with the latency onset time.",
    ],
    # slot 2: QoS / policy check
    [
        "Inspect QoS policies to confirm management and ICMP traffic are correctly prioritised.",
        "Verify the DSCP markings applied to the monitoring host's probes and confirm they reach the correct QoS queue.",
        "Review class-map and policy-map configurations to ensure ICMP is not classified into a congestion-managed queue.",
        "Check if a recent QoS policy change has reclassified traffic in a way that affects probe packets.",
        "Confirm that rate-limiting or policing rules are not inadvertently throttling the monitoring traffic.",
        "Test latency with a probe marked DSCP EF (Expedited Forwarding) to see if the issue is queue-specific.",
        "Review the output queue statistics on the egress interface to identify which queue is tail-dropping.",
        "Confirm that the monitoring host is reachable on all traffic classes, not just the default best-effort queue.",
        "Check whether traffic shaping (not just policing) is in use; shaped traffic can add consistent queuing delay.",
        "Review the device's interface service policy to confirm no rogue policy is applied at the port level.",
    ],
    # slot 3: path / routing investigation
    [
        "Run a traceroute from the monitoring host and compare per-hop latency.",
        "Execute a traceroute to the device right now and compare hop RTTs against the previous baseline.",
        "Perform an MTR (My Traceroute) test to see real-time per-hop loss and latency across the path.",
        "Check the routing table for any route changes in the last hour that might have introduced a longer path.",
        "Run a traceroute from a second monitoring host on a different VLAN to confirm whether the issue is path-wide.",
        "Compare current BGP or OSPF paths against yesterday's baseline to detect any inadvertent route changes.",
        "Use 'ping ip source <interface>' to test latency from different interfaces and isolate which segment is affected.",
        "Run a traceroute with increasing TTLs and note which hop shows the jump in response time.",
        "Check OSPF or EIGRP topology for any recent adjacency changes that might have shifted the traffic path.",
        "Run a simultaneous traceroute and ping to compare probe RTT against hop-by-hop latency.",
    ],
    # slot 4: monitoring / escalation
    [
        "Monitor for the next 15 minutes; escalate if latency continues to rise.",
        "Set a monitoring alert threshold at 350 ms and observe whether the metric trends toward or away from it.",
        "Continue polling at 1-minute intervals for the next 20 minutes and note whether latency is stable, rising, or fluctuating.",
        "Annotate the monitoring timeline with any network events (config changes, link flaps) that coincide with the latency onset.",
        "Open a low-priority incident ticket and flag for review if latency exceeds 350 ms or persists beyond 30 minutes.",
        "Set a paging threshold at 400 ms so the on-call engineer is notified automatically if the situation worsens.",
        "Document the current baseline and check again in 10 minutes; a stable medium-severity latency often self-resolves.",
        "Correlate the latency onset time with any scheduled jobs, batch processes, or software deployments.",
        "Check for user-reported service complaints that coincide with the latency onset; if none, continue to monitor passively.",
        "Review the latency trend graph -- a flat elevated line points to a changed path; a sawtooth pattern points to microbursting.",
    ],
]
_LAT_ACTIONS_HIGH = [
    "Immediately check interface utilisation -- look for a bandwidth spike or microbursting.",
    "Capture a brief packet trace on the uplink to identify the traffic source causing congestion.",
    "Divert or rate-limit bulk flows (backup jobs, software updates) if they are the cause.",
    "Review hardware queue drop counters on the uplink interface.",
    "Escalate to the network team if no clear cause is found within 10 minutes; latency at this level impacts live services.",
    "Consider temporarily increasing QoS priority for critical traffic while the cause is investigated.",
]


def build_high_latency(s: dict) -> str:
    lat   = s["latency_ms"]
    loss  = s["packet_loss_pct"]
    sev   = s["severity"]
    dtype = s["device_type"]
    dur   = s["duration_minutes"]

    if sev == "medium":
        tmpl    = _pick(_LAT_EXPLAIN_MED, s)
        explain = tmpl.format(lat=lat, loss=loss)
        actions_str = _actions_list(
            [_pick_i(bank, s, i) for i, bank in enumerate(_LAT_ACTIONS_MED_BANKS)]
        )
    else:
        tmpl    = _pick(_LAT_EXPLAIN_HIGH, s)
        explain = tmpl.format(lat=lat, loss=loss, x=lat / 500)
        actions_str = _actions_list(_LAT_ACTIONS_HIGH)

    explain += _duration_note(dur)

    causes = _causes_list(_lat_causes(dtype, sev))
    return f"Explanation:\n{explain}\n\nLikely causes:\n{causes}\n\nRecommended actions:\n{actions_str}"


# == HIGH_PACKET_LOSS =========================================================
_LOSS_EXPLAIN_MED = [
    "Packet loss is {loss}%, above the medium-severity threshold of 20%. "
    "Latency of {lat} ms is within normal bounds, suggesting the drop is occurring "
    "at a specific queue or interface rather than across the whole path.",

    "{loss}% of ICMP probes are being dropped, triggering a medium-severity alert "
    "(threshold: 20%). The latency of {lat} ms remains normal, which points to "
    "selective packet discard rather than general congestion.",

    "The monitoring system is observing {loss}% packet loss against the 20% "
    "medium-severity threshold while round-trip time holds at {lat} ms. "
    "This pattern is consistent with a queue tail-drop policy or a flapping interface.",

    "One in approximately {ratio} packets is being dropped ({loss}% loss, threshold: 20%). "
    "Latency ({lat} ms) is normal, implying the link has capacity but some classification "
    "or queue mechanism is selectively discarding traffic.",

    "Packet loss stands at {loss}%, crossing the 20% medium-severity boundary. "
    "With latency only at {lat} ms, the link appears structurally sound; "
    "the loss is likely intermittent rather than the result of sustained congestion.",

    "A {loss}% loss rate against the 20% medium-severity threshold indicates degraded "
    "packet delivery without a complete path failure. The {lat} ms latency for surviving "
    "packets is within normal range, narrowing the cause to a queue or interface issue.",
]

_LOSS_EXPLAIN_HIGH = [
    "{loss}% packet loss is far above the high-severity threshold of 50%. "
    "At this rate, TCP sessions will stall, UDP streams will degrade severely, "
    "and network-dependent services may appear offline.",

    "More than half of all ICMP probes are failing ({loss}% loss, threshold: 50%). "
    "The round-trip time of {lat} ms does not reflect extreme congestion, which suggests "
    "a hardware error, port flap, or selective drop policy rather than pure bandwidth exhaustion.",

    "Packet loss has reached {loss}%, crossing the high-severity boundary of 50%. "
    "With {consecutive} consecutive probe failures in this window, "
    "the path is effectively unreliable.",

    "A {loss}% packet loss rate means the network path to this device is deeply impaired. "
    "Even latency-tolerant protocols like DNS will experience failures at this level of loss.",

    "High-severity packet loss at {loss}% -- {x:.0f} percentage points above the 50% threshold. "
    "Surviving packets arrive in {lat} ms, so the path still has capacity, "
    "but the extreme drop rate renders it unsuitable for any reliable traffic.",

    "At {loss}% loss the link is above the 50% high-severity threshold and functionally "
    "unreliable. TCP connections will time out, streaming media will break, and "
    "any stateful protocol will see session resets within {lat}-ms round-trip windows.",
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
            "Session table full -- all new connections, including ICMP, are being rejected.",
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

# Per-slot banks for packet-loss-medium actions (5 slots, 10+ alternatives each).
_LOSS_ACTIONS_MED_BANKS = [
    # slot 0: error counter inspection
    [
        "Check interface input/output error counters for CRC, giants, or runts.",
        "Pull 'show interface' output and note input errors, CRC, and frame discards over the past 5 minutes.",
        "Check the ingress error rate per port on the upstream switch using SNMP ifInErrors.",
        "Review interface counters for runts and giants; both indicate a physical layer or duplex issue.",
        "Run 'show interface counters errors' on each hop in the path and compare error rates against the baseline.",
        "Check FCS error counters on the interface -- a rising FCS error rate points to a physical connection fault.",
        "Review optical power (dBm) on SFP interfaces to see if received power has dropped below the sensitivity threshold.",
        "Inspect the interface for late collisions, which indicate duplex mismatch even on switches.",
        "Poll SNMP ifInErrors and ifOutDiscards at 30-second intervals for 5 minutes and chart the rate.",
        "Check the output queue discard counters alongside input errors to distinguish between queue policy drops and physical errors.",
    ],
    # slot 1: queue / drop policy
    [
        "Inspect the interface queue statistics for tail-drop or RED discards.",
        "Check the egress queue depth and drop counters on the uplink interface serving this device.",
        "Review WRED or tail-drop discard statistics per queue to identify which traffic class is being dropped.",
        "Check whether a per-user or per-flow policer is applying a hard drop to packets matching the monitoring source.",
        "Inspect 'show policy-map interface' to identify the queue that is accumulating drops.",
        "Review the interface output drop counter; a rising output drop count confirms buffer exhaustion.",
        "Check whether Weighted Fair Queuing or Priority Queuing has a misconfigured bandwidth allocation.",
        "Run 'show queue' on the egress interface and note which queue is contributing most drops.",
        "Check the input queue counters as well as output -- input drops on a saturated uplink cause upstream loss.",
        "Review the hardware queue (tx-ring) depth if the device provides that counter.",
    ],
    # slot 2: QoS / monitoring traffic policy
    [
        "Review QoS policy to confirm ICMP/monitoring traffic is not being policed.",
        "Verify that the monitoring host's source IP is not matched by a drop-action police rule.",
        "Check whether a recent QoS policy change reclassified ICMP probes into a lower-priority class.",
        "Confirm that the DSCP marking on the monitoring probe traffic is preserved across the path.",
        "Test with a probe from a different source IP to rule out a per-source policing rule causing the discards.",
        "Review the access-list or class-map that matches monitoring traffic to confirm it is set to permit, not drop.",
        "Check whether control-plane policing (CoPP) is rate-limiting ICMP to the device CPU.",
        "Confirm that no rate-limit ACL on the monitored device's interface is dropping probe packets.",
        "Inspect whether a traffic-shaping policy is buffering but also dropping monitoring traffic during burst periods.",
        "Check whether a NetFlow or sFlow sampler on the interface is inadvertently dropping sampled packets.",
    ],
    # slot 3: source-specific / multi-point testing
    [
        "Run a sustained ping test from multiple hosts to determine if loss is source-specific.",
        "Launch simultaneous pings from two different monitoring hosts to confirm whether the loss is path-wide or source-specific.",
        "Test packet loss from a host on a different VLAN to rule out a VLAN-specific forwarding issue.",
        "Run a large-packet ping (1400-byte payload) alongside the standard test to rule out MTU-related fragmentation drop.",
        "Perform an iPerf3 UDP test from the monitoring host and compare with the ICMP loss measurement.",
        "Check whether packet loss is symmetric (both directions) or asymmetric (one direction), then trace that specific path.",
        "Run a traceroute with packet loss measurements per hop to pinpoint which network segment is dropping frames.",
        "Test from a host on the monitored device's local segment to confirm whether the loss is internal or external.",
        "Compare packet loss at different packet sizes: MTU-sized packets losing more than small packets indicates a fragmentation or reassembly issue.",
        "Ping the device from both the monitoring VLAN and the management VLAN and compare loss percentages.",
    ],
    # slot 4: trend / escalation
    [
        "Monitor the interface utilisation trend to check for microburst patterns.",
        "Enable microburst detection on the uplink interface if the platform supports sub-second polling.",
        "Poll the interface counters every 30 seconds for the next 10 minutes and look for a periodic spike pattern.",
        "Check whether loss correlates with top-of-hour or scheduled jobs (backup, log collection) that saturate the link briefly.",
        "Continue monitoring and set an escalation rule: if loss exceeds 30% for more than 5 consecutive minutes, page on-call.",
        "Annotate the monitoring timeline with any network events and check if the loss onset correlates with a logged event.",
        "Monitor for 15 minutes and escalate to the high-severity workflow if loss remains above 30%.",
        "Open a low-priority incident ticket and schedule a follow-up review in 30 minutes if loss persists.",
        "Check the monitoring tool's history for this device to see if similar loss episodes occurred at the same time of day.",
        "Set a 5-minute moving average alert on packet loss; a rising trend confirms an active condition rather than a transient blip.",
    ],
]
_LOSS_ACTIONS_HIGH = [
    "Immediately review interface error counters -- high physical errors indicate a cable or SFP issue.",
    "Replace or reseat the SFP/cable if CRC errors or input errors are climbing.",
    "Check for duplex mismatches with 'show interface' or equivalent.",
    "Capture traffic on the upstream switch port to identify if loss originates there.",
    "Consider failing over to a redundant path if available, while the root cause is identified.",
    "Escalate to the network team; greater than 50% loss is a service-impacting event.",
]


def build_high_packet_loss(s: dict) -> str:
    loss  = s["packet_loss_pct"]
    lat   = s["latency_ms"]
    sev   = s["severity"]
    dtype = s["device_type"]
    fails = s["consecutive_failures"]
    dur   = s["duration_minutes"]

    if sev == "medium":
        tmpl    = _pick(_LOSS_EXPLAIN_MED, s)
        explain = tmpl.format(loss=loss, lat=lat, ratio=round(100 / max(loss, 1), 1))
        actions_str = _actions_list(
            [_pick_i(bank, s, i) for i, bank in enumerate(_LOSS_ACTIONS_MED_BANKS)]
        )
    else:
        tmpl    = _pick(_LOSS_EXPLAIN_HIGH, s)
        explain = tmpl.format(
            loss=loss, lat=lat, consecutive=fails, x=loss - 50
        )
        actions_str = _actions_list(_LOSS_ACTIONS_HIGH)

    # low latency on high-loss: note selective discard
    if lat is not None and lat < 50 and sev == "high":
        explain += (
            f" The low latency ({lat} ms) for surviving packets suggests the loss is due to "
            f"selective discard (queue policy, hardware error) rather than path congestion."
        )

    explain += _duration_note(dur)

    causes = _causes_list(_loss_causes(dtype, sev))
    return f"Explanation:\n{explain}\n\nLikely causes:\n{causes}\n\nRecommended actions:\n{actions_str}"


# == HIGH_CPU_USAGE ===========================================================
_CPU_EXPLAIN_HIGH = [
    "CPU utilisation has reached {cpu}%, above the high-severity threshold of 80%, "
    "persisting for {dur}. At this level the device may begin dropping control-plane "
    "packets, slow convergence, and fail to service management requests promptly.",

    "The device is reporting {cpu}% CPU usage, crossing the 80% high-severity mark. "
    "Elevated CPU on {role} can degrade routing protocol timers, slow policy "
    "lookups, and cause intermittent management timeouts.",

    "CPU load stands at {cpu}% (threshold: 80%). While the device remains functional, "
    "{dur} of load at this level risks destabilising protocol adjacencies and slowing "
    "failover detection.",

    "At {cpu}% CPU utilisation above the 80% high-severity threshold, the device process "
    "scheduler is running near capacity. Interrupt and timer-driven operations -- such as "
    "routing keepalives -- become unreliable.",

    "A {cpu}% CPU reading has triggered the high-severity alert (threshold: 80%). "
    "For {dur} the device has been under elevated load that could cause control-plane "
    "events (keepalives, SNMP queries) to be delayed or dropped.",

    "CPU utilisation of {cpu}% exceeds the 80% high-severity threshold and has been "
    "elevated for {dur}. The device remains responsive, but any further increase risks "
    "crossing the 90% critical boundary where protocol adjacencies begin to fail.",
]

_CPU_EXPLAIN_CRIT = [
    "CPU utilisation is {cpu}% -- above the critical threshold of 90%. The device is "
    "effectively saturated; control-plane functions are at serious risk of failure, "
    "and packet forwarding may be falling back to the software path.",

    "A {cpu}% CPU reading, {x:.0f} points above the critical boundary of 90%, indicates "
    "that the device cannot service all scheduled tasks. Protocol adjacencies may drop, "
    "and management access may be completely unresponsive.",

    "Critical CPU saturation at {cpu}% has persisted for {dur}. At this level the device "
    "operating system cannot honour all timer and interrupt requests, risking BGP/OSPF "
    "neighbour loss, STP instability, or RADIUS timeout.",

    "The device CPU is pegged at {cpu}%, well into the critical zone above the 90% "
    "threshold. Any latency in the scheduler at this point can cascade into protocol "
    "failures that take minutes to recover after the CPU pressure is relieved.",

    "Critical CPU alert: {cpu}% observed against the 90% threshold. With {dur} at this "
    "level, the device has likely already dropped some control-plane packet processing "
    "and may show adjacency warnings in its logs.",

    "At {cpu}% the CPU has exceeded the 90% critical threshold for {dur}. The operating "
    "system is unable to guarantee timely service for all scheduled tasks; routing "
    "protocol keepalives and management polling are the first victims.",
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
    "Check for routing protocol flaps -- a sudden topology change can trigger sustained SPF/RIB recalculation.",
    "Review SNMP polling intervals; a polling storm can peg management-plane CPU.",
    "Identify any recent configuration change that may have disabled hardware-assisted forwarding.",
    "Monitor every 2 minutes; if CPU stays above 80% for over 15 minutes, escalate.",
]
_CPU_ACTIONS_CRIT = [
    "Immediately identify the top CPU-consuming process using the device's process monitor.",
    "Check routing neighbour tables -- if adjacencies are flapping, the SPF storm is the cause.",
    "Reduce SNMP polling frequency or disable non-essential polling until CPU normalises.",
    "If a specific process is the culprit, consider restarting it (with change-control approval).",
    "Prepare to failover to a redundant device if CPU does not drop within 5 minutes.",
    "Engage the network operations team immediately -- critical CPU on {role} risks a service outage.",
]


def build_high_cpu(s: dict) -> str:
    cpu   = s["cpu_pct"]
    mem   = s["memory_pct"]
    sev   = s["severity"]
    dtype = s["device_type"]
    dur   = s["duration_minutes"]
    role  = device_role(dtype)
    dur_s = _mins(dur)

    if sev == "critical":
        tmpl    = _pick(_CPU_EXPLAIN_CRIT, s)
        explain = tmpl.format(cpu=cpu, dur=dur_s, x=cpu - 90, role=role)
        actions = [a.format(role=role) for a in _CPU_ACTIONS_CRIT]
    else:
        tmpl    = _pick(_CPU_EXPLAIN_HIGH, s)
        explain = tmpl.format(cpu=cpu, dur=dur_s, role=role)
        actions = list(_CPU_ACTIONS_HIGH)

    if mem is not None and mem >= 90:
        explain += f" Memory usage is also at a critical level ({mem}%, threshold: 90%), compounding the risk of an imminent crash."
    elif mem is not None and mem >= 80:
        explain += f" Memory usage is also elevated at {mem}% (threshold: 80%), compounding the risk."
    elif mem is not None and mem >= 60:
        explain += f" Memory is at {mem}% -- not yet at the 80% threshold, but worth monitoring alongside CPU."

    explain += _duration_note(dur)

    causes      = _causes_list(_CPU_CAUSES.get(dtype, _CPU_CAUSES["other"]))
    actions_str = _actions_list(actions)
    return f"Explanation:\n{explain}\n\nLikely causes:\n{causes}\n\nRecommended actions:\n{actions_str}"


# == HIGH_MEMORY_USAGE ========================================================
_MEM_EXPLAIN_HIGH = [
    "Memory usage is {mem}%, above the high-severity threshold of 80%, after {dur}. "
    "As free memory shrinks, the device will increasingly rely on buffer reuse and may "
    "begin dropping sessions or routes.",

    "The device is utilising {mem}% of available memory, crossing the 80% high-severity "
    "mark. Reduced free memory limits the operating system's ability to respond to "
    "traffic bursts and can cause routing table truncation.",

    "At {mem}% memory utilisation (threshold: 80%), the device has limited headroom "
    "before it must begin aggressively reclaiming buffers or dropping cached state.",

    "Memory consumption of {mem}% is above the 80% high-severity alert level. "
    "For {role}, this may constrain the size of connection-tracking tables, "
    "routing caches, or application heaps.",

    "A {mem}% memory reading has crossed the 80% high-severity threshold. "
    "With {free:.1f}% free RAM remaining, any allocation burst -- a routing update, "
    "a connection spike -- could push the device into the critical zone.",

    "High-severity memory alert: {mem}% used against the 80% threshold. "
    "The device still has {free:.1f}% free, but that margin is narrow enough that "
    "a moderate increase in workload could trigger an OOM condition.",
]

_MEM_EXPLAIN_CRIT = [
    "Memory usage has reached {mem}%, crossing the critical threshold of 90%. "
    "The device is nearly out of usable memory; any additional allocation may fail, "
    "causing processes to crash or the device to reload.",

    "At {mem}% memory utilisation -- {x:.0f} points above the 90% critical level -- "
    "the device OS is likely swapping or forcibly reclaiming buffers. "
    "This produces latency spikes and may corrupt in-flight sessions.",

    "Critical memory pressure ({mem}%, threshold: 90%) means the device has only "
    "{free:.1f}% of RAM free. Routing entries, session state, or application heap "
    "allocations are at risk of being evicted or failing outright.",

    "The device is at {mem}% memory utilisation, exceeding the 90% critical threshold. "
    "Uncontrolled memory growth at this level typically ends in an OOM-triggered crash "
    "or watchdog reboot.",

    "Memory utilisation of {mem}% is {x:.0f} points above the 90% critical boundary. "
    "With only {free:.1f}% RAM free the device has no buffer for any further allocation; "
    "the next significant memory request may trigger a crash.",

    "Critical memory alert: {mem}% used vs the 90% critical threshold. "
    "The device has been near or above this level for {dur}. "
    "Imminent OOM-triggered reloads are a realistic risk if the condition is not addressed.",
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
        "Application memory leak -- heap grows over time without being released.",
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
    "Check the device uptime -- a long-running device may be accumulating a slow memory leak.",
    "Review routing table size and compare to the device's recommended maximum.",
    "Schedule a maintenance window reboot if memory continues to climb without a clear cause.",
    "Set an alert to escalate automatically if memory crosses 90% before the next check.",
]
_MEM_ACTIONS_CRIT = [
    "Immediately identify the memory allocation per process -- look for the largest consumer.",
    "Check if swapping is active; swap usage on a network device often precedes a crash.",
    "Clear any clearable caches (ARP, route cache, log buffers) if the platform supports it.",
    "Begin planning an emergency failover or controlled reload before an uncontrolled crash occurs.",
    "Engage the network operations team -- critical memory pressure risks an imminent reload.",
    "After recovery, conduct a post-mortem to identify whether a leak or an oversized table caused the event.",
]


def build_high_memory(s: dict) -> str:
    mem   = s["memory_pct"]
    cpu   = s["cpu_pct"]
    sev   = s["severity"]
    dtype = s["device_type"]
    dur   = s["duration_minutes"]
    role  = device_role(dtype)
    free  = 100 - mem
    dur_s = _mins(dur)

    if sev == "critical":
        tmpl    = _pick(_MEM_EXPLAIN_CRIT, s)
        explain = tmpl.format(mem=mem, x=mem - 90, free=free, dur=dur_s, role=role)
        actions = _MEM_ACTIONS_CRIT
    else:
        tmpl    = _pick(_MEM_EXPLAIN_HIGH, s)
        explain = tmpl.format(mem=mem, dur=dur_s, role=role, free=free)
        actions = _MEM_ACTIONS_HIGH

    if cpu is not None and cpu >= 90:
        explain += f" CPU is also at a critical level ({cpu}%, threshold: 90%), which may indicate memory pressure is causing excessive paging or buffer management overhead."
    elif cpu is not None and cpu >= 80:
        explain += f" CPU is also under pressure at {cpu}% (threshold: 80%), which may indicate memory pressure is causing excessive paging or buffer management overhead."
    elif cpu is not None and cpu >= 60:
        explain += f" CPU is at {cpu}% -- worth watching, as memory pressure can eventually drive CPU up as the OS spends more time in memory management."

    explain += _duration_note(dur)

    causes      = _causes_list(_MEM_CAUSES.get(dtype, _MEM_CAUSES["other"]))
    actions_str = _actions_list(actions)
    return f"Explanation:\n{explain}\n\nLikely causes:\n{causes}\n\nRecommended actions:\n{actions_str}"


# == combined fault builders ==================================================

def build_latency_and_loss(s: dict) -> str:
    lat   = s["latency_ms"]
    loss  = s["packet_loss_pct"]
    sev   = s["severity"]
    dtype = s["device_type"]
    dur   = s["duration_minutes"]

    if sev == "medium":
        explain = (
            f"Both latency ({lat} ms) and packet loss ({loss}%) are simultaneously elevated "
            f"above their respective medium-severity thresholds (200 ms / 20%). "
            f"The co-occurrence of these two metrics points to path-level congestion "
            f"rather than a single isolated metric anomaly."
        )
    else:
        explain = (
            f"Latency has risen to {lat} ms and packet loss to {loss}% -- both well above "
            f"their high-severity thresholds (500 ms / 50%). "
            f"This combined pattern is characteristic of severe link congestion, a hardware fault, "
            f"or a partial path failure. "
            f"At {loss}% loss, TCP sessions will stall and VoIP/video streams will be unusable. "
            f"The elevated latency of surviving packets ({lat} ms) confirms the path is still "
            f"partially functional but deeply impaired."
        )

    explain += _duration_note(dur)

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
            "Escalate immediately -- combined high latency and high loss causes service outages.",
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
    cpu   = s["cpu_pct"]
    mem   = s["memory_pct"]
    sev   = s["severity"]
    dtype = s["device_type"]
    dur   = s["duration_minutes"]
    role  = device_role(dtype)
    dur_s = _mins(dur)

    if sev == "critical":
        # Determine which metric(s) crossed critical
        cpu_crit = cpu >= 90
        mem_crit = mem >= 90
        if cpu_crit and mem_crit:
            crit_note = (
                f"Both CPU ({cpu}%, threshold: 90%) and memory ({mem}%, threshold: 90%) "
                f"have simultaneously crossed the critical boundary"
            )
        elif cpu_crit:
            crit_note = (
                f"CPU has reached a critical {cpu}% (threshold: 90%), while memory is "
                f"also elevated at {mem}% (threshold: 80%)"
            )
        else:
            crit_note = (
                f"Memory has reached a critical {mem}% (threshold: 90%), while CPU is "
                f"also elevated at {cpu}% (threshold: 80%)"
            )
        explain = (
            f"{crit_note} on this {dtype}, which serves as {role}. "
            f"After {dur_s} at this level, the device's ability to maintain protocol adjacencies, "
            f"process management requests, and forward packets reliably is severely compromised. "
            f"An uncontrolled crash or watchdog reboot is a real risk."
        )
    else:
        explain = (
            f"CPU and memory are both above the 80% high-severity threshold "
            f"(CPU: {cpu}%, memory: {mem}%, threshold for both: 80%), persisting for {dur_s}. "
            f"The combination suggests the system is under consistent workload pressure rather than "
            f"a single runaway process, since memory growth typically follows from high CPU activity "
            f"(process forks, connection-state growth, cache accumulation)."
        )

    explain += _duration_note(dur)

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
            "Review uptime -- a device running for many weeks without reboot may be accumulating a slow leak.",
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
    lat   = s["latency_ms"]
    cpu   = s["cpu_pct"]
    sev   = s["severity"]
    dtype = s["device_type"]
    dur   = s["duration_minutes"]
    role  = device_role(dtype)

    lat_thr = "500 ms (high-severity)" if lat >= 500 else "200 ms (medium-severity)"
    cpu_thr = "90% (critical)" if cpu >= 90 else "80% (high-severity)"

    explain = (
        f"Latency to the device is {lat} ms, exceeding the {lat_thr} threshold, "
        f"while CPU is at {cpu}%, above the {cpu_thr} threshold. "
        f"This combination is significant: CPU saturation on {role} often causes latency because "
        f"ICMP echo-reply processing is handled by the control plane, which is the first thing to "
        f"suffer when the CPU is overloaded. The fault has persisted for {_mins(dur)}."
    )

    explain += _duration_note(dur)

    causes = _causes_list([
        f"Control-plane CPU saturation causing the {dtype} to delay ICMP echo-reply handling.",
        "A heavy process (route recalculation, config parsing, crypto) monopolising CPU and indirectly inflating latency.",
        "Process switching instead of hardware forwarding, adding per-packet CPU overhead that raises latency.",
        "Management polling (SNMP, syslog flushing) competing with forwarding tasks.",
        "A control-plane attack (e.g. crafted BGP UPDATEs) consuming CPU and degrading response times.",
    ])
    actions_list = [
        "Check the top CPU processes first -- resolving the CPU issue should bring latency down.",
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
    # Reuse the unreachable builder -- the "+HIGH_PACKET_LOSS" annotation reflects
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


# -- dispatch -----------------------------------------------------------------
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
    # Only show ICMP failures for faults where it's meaningful (UNREACHABLE types)
    cf = s.get("consecutive_failures", 0) or 0
    if cf > 0 and "UNREACHABLE" in s.get("fault_type", ""):
        lines.append(f"Consecutive ICMP failures: {cf}")
    lines.append(f"Fault duration: {_mins(s['duration_minutes'])}")
    return "\n".join(lines)


def scenario_to_example(s: dict) -> dict:
    return {
        "instruction": INSTRUCTION,
        "input":       scenario_to_input(s),
        "output":      build_output(s),
    }


# -- stratified split ---------------------------------------------------------
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


# -- main ---------------------------------------------------------------------
def main():
    # 1. Load generated scenarios
    with SCENARIOS.open(encoding="utf-8") as f:
        scenarios = [json.loads(l) for l in f]

    examples = [scenario_to_example(s) for s in scenarios]
    labels   = [s["fault_type"] for s in scenarios]

    # 2. Load handwritten seeds (if present)
    seed_examples: list[dict] = []
    if SEED_FILE.exists():
        with SEED_FILE.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    seed_examples.append(json.loads(line))
        print(f"Loaded {len(seed_examples)} handwritten seed examples.")
    else:
        print("No handwritten seed file found; skipping.")

    # Label seeds by fault_type extracted from their input block
    seed_labels = []
    for e in seed_examples:
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
    with DATASET_OUT.open("w", encoding="utf-8") as f:
        for ex in all_examples:
            f.write(json.dumps(ex) + "\n")
    print(f"Full dataset: {len(all_examples)} examples -> {DATASET_OUT}")

    # 4. Stratified split
    train, val, test = stratified_split(
        all_examples, all_labels, TRAIN_RATIO, VAL_RATIO, seed=SPLIT_SEED
    )

    for path, split in [(TRAIN_OUT, train), (VAL_OUT, val), (TEST_OUT, test)]:
        with path.open("w", encoding="utf-8") as f:
            for ex in split:
                f.write(json.dumps(ex) + "\n")

    total = len(train) + len(val) + len(test)
    print(
        f"Split: train={len(train)} ({len(train)/total:.0%})  "
        f"val={len(val)} ({len(val)/total:.0%})  "
        f"test={len(test)} ({len(test)/total:.0%})"
    )
    print(f"  -> {TRAIN_OUT.name}, {VAL_OUT.name}, {TEST_OUT.name}")


if __name__ == "__main__":
    main()
