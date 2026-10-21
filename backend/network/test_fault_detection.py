from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from .faults.detection import FaultThresholds, evaluate_monitoring_record, evaluate_snmp_metric
from .models import Device, FaultEvent, MonitoringRecord, Notification, SNMPMetric
from .monitoring import PingResult, monitor_device


class FaultDetectionTests(TestCase):
    def setUp(self):
        self.device = Device.objects.create(
            name='Core Router',
            ip_address='10.0.0.1',
            device_type=Device.DeviceType.ROUTER,
        )

    def record(self, *, reachable=True, latency=20.0, packet_loss=0.0):
        return MonitoringRecord.objects.create(
            device=self.device,
            timestamp=timezone.now(),
            reachable=reachable,
            latency_ms=latency,
            packet_loss_percent=packet_loss,
        )

    def test_unreachable_device_creates_critical_fault_and_notification(self):
        record = self.record(reachable=False, latency=None, packet_loss=100.0)

        faults = evaluate_monitoring_record(record)

        self.assertEqual(len(faults), 1)
        self.assertEqual(faults[0].fault_type, FaultEvent.FaultType.DEVICE_UNREACHABLE)
        self.assertEqual(faults[0].severity, FaultEvent.Severity.CRITICAL)
        self.assertEqual(faults[0].status, FaultEvent.Status.ACTIVE)
        notification = Notification.objects.get(fault=faults[0])
        self.assertEqual(notification.status, Notification.Status.UNREAD)
        self.assertEqual(notification.fault.device_id, self.device.id)
        self.assertEqual(notification.created_at, notification.fault.notification.created_at)

    def test_high_latency_creates_fault_with_severity_and_notification(self):
        record = self.record(latency=600.0)

        faults = evaluate_monitoring_record(record)

        self.assertEqual(len(faults), 1)
        self.assertEqual(faults[0].fault_type, FaultEvent.FaultType.HIGH_LATENCY)
        self.assertEqual(faults[0].severity, FaultEvent.Severity.HIGH)
        self.assertTrue(Notification.objects.filter(fault=faults[0]).exists())

    def test_medium_packet_loss_does_not_create_notification(self):
        record = self.record(packet_loss=25.0)

        faults = evaluate_monitoring_record(record)

        self.assertEqual(len(faults), 1)
        self.assertEqual(faults[0].fault_type, FaultEvent.FaultType.HIGH_PACKET_LOSS)
        self.assertEqual(faults[0].severity, FaultEvent.Severity.MEDIUM)
        self.assertFalse(Notification.objects.filter(fault=faults[0]).exists())

    def test_custom_thresholds_are_supported(self):
        record = self.record(latency=150.0)
        thresholds = FaultThresholds(latency_medium_ms=100.0, latency_high_ms=300.0)

        faults = evaluate_monitoring_record(record, thresholds)

        self.assertEqual(faults[0].fault_type, FaultEvent.FaultType.HIGH_LATENCY)
        self.assertEqual(faults[0].severity, FaultEvent.Severity.MEDIUM)

    def test_active_fault_is_not_duplicated(self):
        first = self.record(latency=600.0)
        second = self.record(latency=700.0, packet_loss=0.0)

        first_fault = evaluate_monitoring_record(first)[0]
        second_fault = evaluate_monitoring_record(second)[0]

        self.assertEqual(first_fault.id, second_fault.id)
        self.assertEqual(
            FaultEvent.objects.filter(
                device=self.device,
                fault_type=FaultEvent.FaultType.HIGH_LATENCY,
                status=FaultEvent.Status.ACTIVE,
            ).count(),
            1,
        )
        self.assertEqual(Notification.objects.filter(fault=first_fault).count(), 1)

    def test_recovered_condition_resolves_active_fault(self):
        bad = self.record(latency=600.0)
        evaluate_monitoring_record(bad)
        good = self.record(latency=20.0, packet_loss=0.0)

        evaluate_monitoring_record(good)

        fault = FaultEvent.objects.get(
            device=self.device,
            fault_type=FaultEvent.FaultType.HIGH_LATENCY,
        )
        self.assertEqual(fault.status, FaultEvent.Status.RESOLVED)
        self.assertIsNotNone(fault.resolved_at)

    @patch('network.monitoring.services.ping_ipv4')
    def test_monitoring_run_triggers_fault_detection(self, ping):
        ping.return_value = PingResult(False, None, 100.0, 'unreachable')

        monitor_device(self.device)

        self.assertTrue(FaultEvent.objects.filter(
            device=self.device,
            fault_type=FaultEvent.FaultType.DEVICE_UNREACHABLE,
            status=FaultEvent.Status.ACTIVE,
        ).exists())
        self.assertTrue(Notification.objects.filter(
            fault__device=self.device,
            fault__fault_type=FaultEvent.FaultType.DEVICE_UNREACHABLE,
        ).exists())

    def test_cpu_and_memory_resource_faults_are_supported(self):
        now = timezone.now()
        cpu = SNMPMetric.objects.create(
            device=self.device,
            timestamp=now,
            metric='cpuUsage',
            oid='1.3.6.1.4.1.example.cpu',
            value='95',
            value_type='Integer',
        )
        memory = SNMPMetric.objects.create(
            device=self.device,
            timestamp=now + timedelta(seconds=1),
            metric='memory_usage',
            oid='1.3.6.1.4.1.example.memory',
            value='85',
            value_type='Integer',
        )

        cpu_fault = evaluate_snmp_metric(cpu)
        memory_fault = evaluate_snmp_metric(memory)

        self.assertEqual(cpu_fault.fault_type, FaultEvent.FaultType.HIGH_CPU_USAGE)
        self.assertEqual(cpu_fault.severity, FaultEvent.Severity.CRITICAL)
        self.assertEqual(memory_fault.fault_type, FaultEvent.FaultType.HIGH_MEMORY_USAGE)
        self.assertEqual(memory_fault.severity, FaultEvent.Severity.HIGH)
        self.assertTrue(Notification.objects.filter(fault=cpu_fault).exists())
        self.assertTrue(Notification.objects.filter(fault=memory_fault).exists())

    def test_normal_resource_metric_resolves_existing_fault(self):
        high = SNMPMetric.objects.create(
            device=self.device,
            timestamp=timezone.now(),
            metric='cpu',
            oid='1.3.6.1.4.1.example.cpu',
            value='95',
            value_type='Integer',
        )
        evaluate_snmp_metric(high)

        normal = SNMPMetric.objects.create(
            device=self.device,
            timestamp=timezone.now(),
            metric='cpu',
            oid='1.3.6.1.4.1.example.cpu',
            value='40',
            value_type='Integer',
        )
        evaluate_snmp_metric(normal)

        fault = FaultEvent.objects.get(
            device=self.device,
            fault_type=FaultEvent.FaultType.HIGH_CPU_USAGE,
        )
        self.assertEqual(fault.status, FaultEvent.Status.RESOLVED)
