import uuid

from django.db import models
from django.db.models import Q


class Device(models.Model):
    class DeviceType(models.TextChoices):
        ROUTER = 'router', 'Router'
        SWITCH = 'switch', 'Switch'
        SERVER = 'server', 'Server'
        ACCESS_POINT = 'access-point', 'Access Point'
        FIREWALL = 'firewall', 'Firewall'
        OTHER = 'other', 'Other'

    class Status(models.TextChoices):
        ONLINE = 'online', 'Online'
        OFFLINE = 'offline', 'Offline'
        UNKNOWN = 'unknown', 'Unknown'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=120)
    ip_address = models.GenericIPAddressField(protocol='IPv4')
    device_type = models.CharField(max_length=20, choices=DeviceType.choices)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.UNKNOWN)
    monitoring_enabled = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name', 'created_at']

    def save(self, *args, **kwargs):
        is_new = self._state.adding
        super().save(*args, **kwargs)
        if is_new:
            MonitoringConfiguration.objects.get_or_create(device=self)

    def __str__(self):
        return f'{self.name} ({self.ip_address})'


class MonitoringConfiguration(models.Model):
    device = models.OneToOneField(Device, on_delete=models.CASCADE, related_name='monitoring_configuration')
    interval_seconds = models.PositiveIntegerField(default=60)
    snmp_enabled = models.BooleanField(default=False)
    snmp_version = models.CharField(max_length=10, blank=True, null=True)
    snmp_community = models.CharField(max_length=255, blank=True, null=True)
    snmp_port = models.PositiveIntegerField(default=161)
    snmp_timeout_seconds = models.FloatField(default=2.0)
    available_metrics = models.JSONField(default=list, blank=True)
    http_monitoring_enabled = models.BooleanField(default=False)
    http_url = models.URLField(max_length=500, blank=True, default='')
    http_timeout_seconds = models.FloatField(default=5.0)
    # Blank means "accept any 2xx/3xx response"; a value demands an exact match.
    http_expected_status = models.PositiveIntegerField(blank=True, null=True)

    def __str__(self):
        return f'Monitoring configuration for {self.device.name}'


class MonitoringRecord(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    device = models.ForeignKey(Device, on_delete=models.CASCADE, related_name='monitoring_records')
    timestamp = models.DateTimeField()
    reachable = models.BooleanField(null=True)
    latency_ms = models.FloatField(null=True, blank=True)
    packet_loss_percent = models.FloatField(null=True, blank=True)
    # HTTP probe fields stay null when the device has no endpoint configured.
    http_ok = models.BooleanField(null=True, blank=True)
    http_status_code = models.PositiveIntegerField(null=True, blank=True)
    http_response_time_ms = models.FloatField(null=True, blank=True)
    http_error = models.CharField(max_length=255, blank=True, default='')

    class Meta:
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['device', '-timestamp'], name='monitoring_device_time_idx'),
            models.Index(fields=['timestamp'], name='monitoring_timestamp_idx'),
            models.Index(fields=['device', 'reachable', '-timestamp'], name='monitoring_device_status_idx'),
        ]


class SNMPMetric(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    device = models.ForeignKey(Device, on_delete=models.CASCADE, related_name='snmp_metrics')
    timestamp = models.DateTimeField()
    metric = models.CharField(max_length=80)
    oid = models.CharField(max_length=128)
    value = models.TextField()
    value_type = models.CharField(max_length=40, blank=True)

    class Meta:
        ordering = ['-timestamp', 'metric']
        indexes = [
            models.Index(fields=['device', '-timestamp']),
            models.Index(fields=['device', 'metric', '-timestamp']),
        ]


class FaultEvent(models.Model):
    class FaultType(models.TextChoices):
        DEVICE_UNREACHABLE = 'DEVICE_UNREACHABLE', 'Device unreachable'
        HIGH_LATENCY = 'HIGH_LATENCY', 'High latency'
        HIGH_PACKET_LOSS = 'HIGH_PACKET_LOSS', 'High packet loss'
        HIGH_CPU_USAGE = 'HIGH_CPU_USAGE', 'High CPU usage'
        HIGH_MEMORY_USAGE = 'HIGH_MEMORY_USAGE', 'High memory usage'
        INTERFACE_FAILURE = 'INTERFACE_FAILURE', 'Interface failure'
        CONNECTIVITY_FAILURE = 'CONNECTIVITY_FAILURE', 'Connectivity failure'
        HTTP_ENDPOINT_FAILURE = 'HTTP_ENDPOINT_FAILURE', 'HTTP endpoint failure'
        HTTP_SLOW_RESPONSE = 'HTTP_SLOW_RESPONSE', 'HTTP slow response'

    class Severity(models.TextChoices):
        CRITICAL = 'critical', 'Critical'
        HIGH = 'high', 'High'
        MEDIUM = 'medium', 'Medium'
        LOW = 'low', 'Low'

    class Status(models.TextChoices):
        ACTIVE = 'active', 'Active'
        ACKNOWLEDGED = 'acknowledged', 'Acknowledged'
        RESOLVED = 'resolved', 'Resolved'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    device = models.ForeignKey(Device, on_delete=models.CASCADE, related_name='faults')
    fault_type = models.CharField(max_length=40, choices=FaultType.choices)
    severity = models.CharField(max_length=10, choices=Severity.choices)
    detected_at = models.DateTimeField()
    status = models.CharField(max_length=15, choices=Status.choices, default=Status.ACTIVE)
    description = models.TextField(blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-detected_at']
        indexes = [
            models.Index(fields=['device', '-detected_at']),
            models.Index(fields=['status', '-detected_at']),
            models.Index(fields=['device', 'status', '-detected_at'], name='fault_device_status_time_idx'),
            models.Index(fields=['device', 'fault_type', '-detected_at'], name='fault_device_type_time_idx'),
            models.Index(fields=['severity', '-detected_at'], name='fault_severity_time_idx'),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['device', 'fault_type'],
                condition=Q(status__in=['active', 'acknowledged']),
                name='uniq_active_fault_type',
            ),
        ]


class Notification(models.Model):
    class Status(models.TextChoices):
        UNREAD = 'unread', 'Unread'
        READ = 'read', 'Read'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    fault = models.OneToOneField(FaultEvent, on_delete=models.CASCADE, related_name='notification')
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.UNREAD)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
