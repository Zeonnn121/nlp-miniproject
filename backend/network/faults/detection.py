"""Deterministic threshold-based fault detection."""

from __future__ import annotations

from dataclasses import dataclass

from django.db import IntegrityError, transaction
from django.utils import timezone

from ..alerts.services import create_fault_notification
from ..models import Device, FaultEvent, MonitoringRecord, SNMPMetric


@dataclass(frozen=True)
class FaultThresholds:
    """Operational thresholds; callers can provide a different policy."""

    latency_medium_ms: float = 200.0
    latency_high_ms: float = 500.0
    packet_loss_medium_percent: float = 20.0
    packet_loss_high_percent: float = 50.0
    cpu_high_percent: float = 80.0
    cpu_critical_percent: float = 90.0
    memory_high_percent: float = 80.0
    memory_critical_percent: float = 90.0
    http_response_medium_ms: float = 1000.0
    http_response_high_ms: float = 3000.0


DEFAULT_THRESHOLDS = FaultThresholds()
ACTIVE_STATUSES = (FaultEvent.Status.ACTIVE, FaultEvent.Status.ACKNOWLEDGED)


@dataclass(frozen=True)
class FaultEvaluation:
    fault_type: str
    severity: str
    description: str


def _active_fault(device: Device, fault_type: str) -> FaultEvent | None:
    return FaultEvent.objects.filter(
        device=device,
        fault_type=fault_type,
        status__in=ACTIVE_STATUSES,
    ).first()


def _create_or_update_fault(device: Device, evaluation: FaultEvaluation, detected_at) -> FaultEvent:
    existing = _active_fault(device, evaluation.fault_type)
    if existing:
        updates = []
        if existing.severity != evaluation.severity:
            existing.severity = evaluation.severity
            updates.append('severity')
        if existing.description != evaluation.description:
            existing.description = evaluation.description
            updates.append('description')
        if updates:
            existing.save(update_fields=updates)
        fault = existing
    else:
        try:
            with transaction.atomic():
                fault = FaultEvent.objects.create(
                    device=device,
                    fault_type=evaluation.fault_type,
                    severity=evaluation.severity,
                    detected_at=detected_at,
                    status=FaultEvent.Status.ACTIVE,
                    description=evaluation.description,
                )
        except IntegrityError:
            fault = _active_fault(device, evaluation.fault_type)
            if fault is None:
                raise

    create_fault_notification(fault)
    return fault


def _resolve_fault(device: Device, fault_type: str) -> int:
    return FaultEvent.objects.filter(
        device=device,
        fault_type=fault_type,
        status__in=ACTIVE_STATUSES,
    ).update(
        status=FaultEvent.Status.RESOLVED,
        resolved_at=timezone.now(),
    )


def _http_evaluations(record: MonitoringRecord, thresholds: FaultThresholds) -> list[FaultEvaluation]:
    """Evaluate the HTTP probe independently of the ICMP result.

    ``http_ok is None`` means no endpoint was configured for this record, so
    there is nothing to judge and nothing to resolve.
    """
    if record.http_ok is None:
        return []

    if not record.http_ok:
        # No status code means the request never completed.
        severity = (
            FaultEvent.Severity.CRITICAL
            if record.http_status_code is None
            else FaultEvent.Severity.HIGH
        )
        return [FaultEvaluation(
            FaultEvent.FaultType.HTTP_ENDPOINT_FAILURE,
            severity,
            record.http_error or 'HTTP endpoint did not return an acceptable response.',
        )]

    response_time = record.http_response_time_ms
    if response_time is None:
        return []

    if response_time >= thresholds.http_response_high_ms:
        return [FaultEvaluation(
            FaultEvent.FaultType.HTTP_SLOW_RESPONSE,
            FaultEvent.Severity.HIGH,
            f'HTTP response time is {response_time:.3f} ms, above {thresholds.http_response_high_ms:.3f} ms.',
        )]
    if response_time >= thresholds.http_response_medium_ms:
        return [FaultEvaluation(
            FaultEvent.FaultType.HTTP_SLOW_RESPONSE,
            FaultEvent.Severity.MEDIUM,
            f'HTTP response time is {response_time:.3f} ms, above {thresholds.http_response_medium_ms:.3f} ms.',
        )]
    return []


def _record_evaluations(record: MonitoringRecord, thresholds: FaultThresholds) -> list[FaultEvaluation]:
    evaluations: list[FaultEvaluation] = _http_evaluations(record, thresholds)

    if record.reachable is False:
        evaluations.append(FaultEvaluation(
            FaultEvent.FaultType.DEVICE_UNREACHABLE,
            FaultEvent.Severity.CRITICAL,
            'Device is unreachable by ICMP monitoring.',
        ))
        return evaluations

    if record.latency_ms is not None:
        if record.latency_ms >= thresholds.latency_high_ms:
            evaluations.append(FaultEvaluation(
                FaultEvent.FaultType.HIGH_LATENCY,
                FaultEvent.Severity.HIGH,
                f'Latency is {record.latency_ms:.3f} ms, above {thresholds.latency_high_ms:.3f} ms.',
            ))
        elif record.latency_ms >= thresholds.latency_medium_ms:
            evaluations.append(FaultEvaluation(
                FaultEvent.FaultType.HIGH_LATENCY,
                FaultEvent.Severity.MEDIUM,
                f'Latency is {record.latency_ms:.3f} ms, above {thresholds.latency_medium_ms:.3f} ms.',
            ))

    if record.packet_loss_percent is not None:
        if record.packet_loss_percent >= thresholds.packet_loss_high_percent:
            evaluations.append(FaultEvaluation(
                FaultEvent.FaultType.HIGH_PACKET_LOSS,
                FaultEvent.Severity.HIGH,
                f'Packet loss is {record.packet_loss_percent:.3f}%, above {thresholds.packet_loss_high_percent:.3f}%.',
            ))
        elif record.packet_loss_percent >= thresholds.packet_loss_medium_percent:
            evaluations.append(FaultEvaluation(
                FaultEvent.FaultType.HIGH_PACKET_LOSS,
                FaultEvent.Severity.MEDIUM,
                f'Packet loss is {record.packet_loss_percent:.3f}%, above {thresholds.packet_loss_medium_percent:.3f}%.',
            ))

    return evaluations


def evaluate_monitoring_record(
    record: MonitoringRecord,
    thresholds: FaultThresholds = DEFAULT_THRESHOLDS,
) -> list[FaultEvent]:
    """Create threshold faults for a record and resolve recovered conditions."""
    evaluations = _record_evaluations(record, thresholds)
    detected_types = {evaluation.fault_type for evaluation in evaluations}

    for fault_type in (
        FaultEvent.FaultType.DEVICE_UNREACHABLE,
        FaultEvent.FaultType.HIGH_LATENCY,
        FaultEvent.FaultType.HIGH_PACKET_LOSS,
        FaultEvent.FaultType.HTTP_ENDPOINT_FAILURE,
        FaultEvent.FaultType.HTTP_SLOW_RESPONSE,
    ):
        if fault_type not in detected_types:
            _resolve_fault(record.device, fault_type)

    return [
        _create_or_update_fault(record.device, evaluation, record.timestamp)
        for evaluation in evaluations
    ]


def _metric_number(metric: SNMPMetric) -> float | None:
    try:
        return float(metric.value)
    except (TypeError, ValueError):
        return None


def evaluate_snmp_metric(
    metric: SNMPMetric,
    thresholds: FaultThresholds = DEFAULT_THRESHOLDS,
) -> FaultEvent | None:
    """Evaluate supported CPU/memory SNMP metrics when they are stored."""
    value = _metric_number(metric)
    if value is None:
        return None

    name = metric.metric.lower().replace('-', '_').replace(' ', '_')
    if name in {'cpu', 'cpu_usage', 'cpu_utilization', 'cpuusage'}:
        fault_type = FaultEvent.FaultType.HIGH_CPU_USAGE
        high = thresholds.cpu_high_percent
        critical = thresholds.cpu_critical_percent
    elif name in {'memory', 'memory_usage', 'memory_utilization', 'memoryusage'}:
        fault_type = FaultEvent.FaultType.HIGH_MEMORY_USAGE
        high = thresholds.memory_high_percent
        critical = thresholds.memory_critical_percent
    else:
        return None

    if value < high:
        _resolve_fault(metric.device, fault_type)
        return None

    severity = FaultEvent.Severity.CRITICAL if value >= critical else FaultEvent.Severity.HIGH
    return _create_or_update_fault(
        metric.device,
        FaultEvaluation(
            fault_type,
            severity,
            f'{metric.metric} is {value:.3f}%, above {high:.3f}%.',
        ),
        metric.timestamp,
    )
