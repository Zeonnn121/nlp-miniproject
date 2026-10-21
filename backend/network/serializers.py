from django.contrib.auth import authenticate, get_user_model
from rest_framework import serializers

from .httpcheck import InvalidHTTPConfiguration, validate_endpoint_url
from .models import Device, FaultEvent, MonitoringConfiguration, MonitoringRecord, Notification, SNMPMetric


User = get_user_model()


class DeviceSerializer(serializers.ModelSerializer):
    ipAddress = serializers.IPAddressField(source='ip_address', protocol='IPv4')
    type = serializers.ChoiceField(source='device_type', choices=Device.DeviceType.choices)
    monitoring = serializers.BooleanField(source='monitoring_enabled')
    createdAt = serializers.DateTimeField(source='created_at', read_only=True)
    updatedAt = serializers.DateTimeField(source='updated_at', read_only=True)

    class Meta:
        model = Device
        fields = ['id', 'name', 'ipAddress', 'type', 'status', 'monitoring', 'createdAt', 'updatedAt']
        read_only_fields = ['id', 'status', 'createdAt', 'updatedAt']

    def validate_name(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError('Device name is required.')
        return value


class MonitoringConfigurationSerializer(serializers.ModelSerializer):
    enabled = serializers.BooleanField(source='device.monitoring_enabled', read_only=True)
    intervalSeconds = serializers.IntegerField(source='interval_seconds', allow_null=True)
    snmpEnabled = serializers.BooleanField(source='snmp_enabled')
    snmpVersion = serializers.ChoiceField(
        source='snmp_version',
        choices=[('1', 'SNMPv1'), ('2c', 'SNMPv2c')],
        allow_blank=True,
        allow_null=True,
        required=False,
    )
    snmpCommunity = serializers.CharField(source='snmp_community', write_only=True, allow_blank=True, required=False)
    snmpPort = serializers.IntegerField(source='snmp_port', required=False, min_value=1, max_value=65535)
    snmpTimeoutSeconds = serializers.FloatField(
        source='snmp_timeout_seconds', required=False, min_value=0.1, max_value=30
    )
    availableMetrics = serializers.ListField(
        source='available_metrics', child=serializers.CharField(), required=False
    )
    httpMonitoringEnabled = serializers.BooleanField(source='http_monitoring_enabled', required=False)
    httpUrl = serializers.URLField(
        source='http_url', required=False, allow_blank=True, max_length=500
    )
    httpTimeoutSeconds = serializers.FloatField(
        source='http_timeout_seconds', required=False, min_value=0.1, max_value=30
    )
    httpExpectedStatus = serializers.IntegerField(
        source='http_expected_status', required=False, min_value=100, max_value=599,
        allow_null=True,
    )

    class Meta:
        model = MonitoringConfiguration
        fields = [
            'enabled', 'intervalSeconds', 'snmpEnabled', 'snmpVersion', 'snmpCommunity',
            'snmpPort', 'snmpTimeoutSeconds', 'availableMetrics',
            'httpMonitoringEnabled', 'httpUrl', 'httpTimeoutSeconds', 'httpExpectedStatus',
        ]

    def validate_intervalSeconds(self, value):
        if value is not None and value < 5:
            raise serializers.ValidationError('Monitoring interval must be at least 5 seconds.')
        return value

    def validate_httpUrl(self, value):
        if not value:
            return value
        try:
            return validate_endpoint_url(value)
        except InvalidHTTPConfiguration as exc:
            raise serializers.ValidationError(str(exc))

    def validate(self, attrs):
        attrs = super().validate(attrs)
        # Enabling HTTP monitoring without a usable URL would fail every run.
        if 'http_monitoring_enabled' in attrs and attrs['http_monitoring_enabled']:
            url = attrs.get('http_url', self.instance.http_url if self.instance else '')
            if not (url or '').strip():
                raise serializers.ValidationError(
                    {'httpUrl': 'An HTTP endpoint URL is required when HTTP monitoring is enabled.'}
                )
        return attrs


class MonitoringRecordSerializer(serializers.ModelSerializer):
    deviceId = serializers.UUIDField(source='device_id', read_only=True)
    latencyMs = serializers.FloatField(source='latency_ms', allow_null=True)
    packetLossPercent = serializers.FloatField(source='packet_loss_percent', allow_null=True)
    httpOk = serializers.BooleanField(source='http_ok', allow_null=True)
    httpStatusCode = serializers.IntegerField(source='http_status_code', allow_null=True)
    httpResponseTimeMs = serializers.FloatField(source='http_response_time_ms', allow_null=True)
    httpError = serializers.CharField(source='http_error', allow_blank=True)

    class Meta:
        model = MonitoringRecord
        fields = [
            'id', 'deviceId', 'timestamp', 'reachable', 'latencyMs', 'packetLossPercent',
            'httpOk', 'httpStatusCode', 'httpResponseTimeMs', 'httpError',
        ]
        read_only_fields = ['id', 'deviceId']


class HistoricalMonitoringRecordSerializer(MonitoringRecordSerializer):
    deviceName = serializers.CharField(source='device.name', read_only=True)

    class Meta(MonitoringRecordSerializer.Meta):
        fields = MonitoringRecordSerializer.Meta.fields + ['deviceName']


class SNMPMetricSerializer(serializers.ModelSerializer):
    deviceId = serializers.UUIDField(source='device_id', read_only=True)
    metricName = serializers.CharField(source='metric', read_only=True)
    valueType = serializers.CharField(source='value_type', read_only=True)

    class Meta:
        model = SNMPMetric
        fields = ['id', 'deviceId', 'timestamp', 'metricName', 'oid', 'value', 'valueType']
        read_only_fields = fields


class FaultSerializer(serializers.ModelSerializer):
    device = serializers.PrimaryKeyRelatedField(queryset=Device.objects.all(), write_only=True)
    deviceId = serializers.UUIDField(source='device_id', read_only=True)
    deviceName = serializers.CharField(source='device.name', read_only=True)
    faultType = serializers.ChoiceField(source='fault_type', choices=FaultEvent.FaultType.choices)
    detectedAt = serializers.DateTimeField(source='detected_at')
    resolvedAt = serializers.DateTimeField(source='resolved_at', allow_null=True, read_only=True)
    severity = serializers.ChoiceField(choices=FaultEvent.Severity.choices)
    status = serializers.ChoiceField(choices=FaultEvent.Status.choices)

    class Meta:
        model = FaultEvent
        fields = [
            'id', 'device', 'deviceId', 'deviceName', 'faultType', 'severity',
            'detectedAt', 'status', 'description', 'resolvedAt',
        ]
        read_only_fields = ['id', 'deviceId', 'deviceName', 'resolvedAt']


class NotificationSerializer(serializers.ModelSerializer):
    faultId = serializers.UUIDField(source='fault_id', read_only=True)
    deviceId = serializers.UUIDField(source='fault.device_id', read_only=True)
    deviceName = serializers.CharField(source='fault.device.name', read_only=True)
    faultType = serializers.CharField(source='fault.fault_type', read_only=True)
    severity = serializers.CharField(source='fault.severity', read_only=True)
    detectedAt = serializers.DateTimeField(source='fault.detected_at', read_only=True)
    description = serializers.CharField(source='fault.description', read_only=True)
    createdAt = serializers.DateTimeField(source='created_at', read_only=True)

    class Meta:
        model = Notification
        fields = [
            'id', 'faultId', 'deviceId', 'deviceName', 'faultType',
            'severity', 'detectedAt', 'createdAt', 'status', 'description',
        ]
        read_only_fields = [
            'id', 'faultId', 'deviceId', 'deviceName', 'faultType',
            'severity', 'detectedAt', 'createdAt', 'description',
        ]


class LoginSerializer(serializers.Serializer):
    username = serializers.CharField()
    password = serializers.CharField(write_only=True, trim_whitespace=False)

    def validate(self, attrs):
        identifier = attrs['username'].strip()
        username = identifier

        if '@' in identifier:
            user = User.objects.filter(email__iexact=identifier).first()
            if user is None:
                raise serializers.ValidationError('Invalid username or password.')
            username = user.get_username()

        user = authenticate(username=username, password=attrs['password'])
        if user is None or not user.is_active or not user.is_staff:
            raise serializers.ValidationError('Invalid username or password.')

        attrs['user'] = user
        return attrs
