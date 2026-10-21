from rest_framework import mixins, status, viewsets
from rest_framework.authtoken.models import Token
from rest_framework.decorators import action
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response
from rest_framework.views import APIView

from .alerts.services import create_fault_notification, mark_notification_read
from .faults.services import acknowledge_fault, resolve_fault
from .llm_service import get_fault_explanation
from .models import Device, FaultEvent, MonitoringRecord, Notification
from .monitoring import InvalidMonitoringConfiguration, monitor_device
from .serializers import (
    DeviceSerializer,
    FaultSerializer,
    LoginSerializer,
    MonitoringConfigurationSerializer,
    MonitoringRecordSerializer,
    NotificationSerializer,
)
from .tasks import monitor_device_task


class LoginView(APIView):
    permission_classes = []
    throttle_scope = 'login'

    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.validated_data['user']

        # Rotate the token on every successful login so a previous token cannot
        # remain valid after a new authenticated session is established.
        Token.objects.filter(user=user).delete()
        token = Token.objects.create(user=user)
        return Response({
            'token': token.key,
            'user': {
                'id': user.id,
                'username': user.get_username(),
                'email': user.email,
                'firstName': user.first_name,
                'lastName': user.last_name,
                'isStaff': user.is_staff,
            },
        })


class LogoutView(APIView):
    def post(self, request):
        if request.auth is not None:
            request.auth.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class MeView(APIView):
    def get(self, request):
        user = request.user
        return Response({
            'id': user.id,
            'username': user.get_username(),
            'email': user.email,
            'firstName': user.first_name,
            'lastName': user.last_name,
            'isStaff': user.is_staff,
        })


class DeviceViewSet(viewsets.ModelViewSet):
    queryset = Device.objects.select_related('monitoring_configuration').all()
    serializer_class = DeviceSerializer
    permission_classes = [IsAdminUser]

    def get_queryset(self):
        queryset = super().get_queryset()
        status_value = self.request.query_params.get('status')
        device_type = self.request.query_params.get('type')
        monitoring = self.request.query_params.get('monitoring')
        search = self.request.query_params.get('search')
        if status_value:
            queryset = queryset.filter(status=status_value)
        if device_type:
            queryset = queryset.filter(device_type=device_type)
        if monitoring is not None:
            queryset = queryset.filter(monitoring_enabled=monitoring.lower() in {'true', '1', 'yes'})
        if search:
            queryset = queryset.filter(name__icontains=search)
        return queryset

    @action(detail=True, methods=['get', 'patch'], url_path='monitoring')
    def monitoring(self, request, pk=None):
        """Read or update only the device monitoring enabled state."""
        device = self.get_object()

        if request.method == 'PATCH':
            serializer = DeviceSerializer(
                device,
                data={'monitoring': request.data.get('monitoring')},
                partial=True,
            )
            serializer.is_valid(raise_exception=True)
            serializer.save()
            device.refresh_from_db()

            if device.monitoring_enabled:
                monitor_device_task.delay(str(device.id))

        return Response(DeviceSerializer(device).data)

    @action(detail=True, methods=['get', 'patch'], url_path='monitoring-config')
    def monitoring_config(self, request, pk=None):
        device = self.get_object()
        config = device.monitoring_configuration
        if request.method == 'PATCH':
            serializer = MonitoringConfigurationSerializer(config, data=request.data, partial=True)
            serializer.is_valid(raise_exception=True)
            serializer.save()
        return Response(MonitoringConfigurationSerializer(config).data)

    @action(detail=True, methods=['post'], url_path='monitor')
    def monitor(self, request, pk=None):
        """Run one immediate ICMP monitoring check and persist the result."""
        device = self.get_object()
        try:
            record = monitor_device(device)
        except InvalidMonitoringConfiguration as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(MonitoringRecordSerializer(record).data, status=status.HTTP_200_OK)


class MonitoringRecordViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = MonitoringRecord.objects.select_related('device').all()
    serializer_class = MonitoringRecordSerializer
    permission_classes = [IsAdminUser]

    def get_queryset(self):
        queryset = super().get_queryset()
        device_id = self.request.query_params.get('deviceId')
        if device_id:
            queryset = queryset.filter(device_id=device_id)
        return queryset


class FaultViewSet(viewsets.ReadOnlyModelViewSet):
    """Faults are generated by monitoring; clients may only inspect or act on them."""
    queryset = FaultEvent.objects.select_related('device').all()
    serializer_class = FaultSerializer
    permission_classes = [IsAdminUser]

    def get_queryset(self):
        queryset = super().get_queryset()
        filters = {
            'deviceId': 'device_id',
            'severity': 'severity',
            'type': 'fault_type',
            'faultType': 'fault_type',
            'status': 'status',
        }
        for key, field in filters.items():
            value = self.request.query_params.get(key)
            if value:
                queryset = queryset.filter(**{field: value})
        start = self.request.query_params.get('from')
        end = self.request.query_params.get('to')
        if start:
            queryset = queryset.filter(detected_at__gte=start)
        if end:
            queryset = queryset.filter(detected_at__lte=end)
        return queryset

    @action(detail=False, methods=['get'])
    def active(self, request):
        queryset = self.get_queryset().filter(status__in=[FaultEvent.Status.ACTIVE, FaultEvent.Status.ACKNOWLEDGED])
        return Response(self.get_serializer(queryset, many=True).data)

    @action(detail=True, methods=['post'])
    def acknowledge(self, request, pk=None):
        fault = acknowledge_fault(self.get_object())
        return Response(self.get_serializer(fault).data)

    @action(detail=True, methods=['post'])
    def resolve(self, request, pk=None):
        fault = resolve_fault(self.get_object())
        return Response(self.get_serializer(fault).data)

    @action(detail=True, methods=['post'])
    def explain(self, request, pk=None):
        """Return a structured fault explanation, cached on the fault."""
        fault = self.get_object()
        refresh = str(request.query_params.get('refresh', '')).lower() in {'1', 'true', 'yes'}
        return Response(get_fault_explanation(fault, refresh=refresh))

    @action(detail=True, methods=['patch'], url_path='status')
    def update_status(self, request, pk=None):
        fault = self.get_object()
        new_status = request.data.get('status')
        if new_status not in FaultEvent.Status.values:
            return Response({'detail': 'Invalid fault status.'}, status=status.HTTP_400_BAD_REQUEST)
        if new_status == FaultEvent.Status.ACKNOWLEDGED:
            try:
                fault = acknowledge_fault(fault)
            except ValueError as exc:
                return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        elif new_status == FaultEvent.Status.RESOLVED:
            fault = resolve_fault(fault)
        else:
            if fault.status == FaultEvent.Status.RESOLVED:
                return Response({'detail': 'Resolved faults cannot be reactivated through the API.'}, status=status.HTTP_400_BAD_REQUEST)
            fault.status = FaultEvent.Status.ACTIVE
            fault.save(update_fields=['status'])
        return Response(self.get_serializer(fault).data)


class NotificationViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Notification.objects.select_related('fault__device').all()
    serializer_class = NotificationSerializer
    permission_classes = [IsAdminUser]

    def get_queryset(self):
        queryset = super().get_queryset()
        status_value = self.request.query_params.get('status')
        if status_value:
            queryset = queryset.filter(status=status_value)
        device_id = self.request.query_params.get('deviceId')
        if device_id:
            queryset = queryset.filter(fault__device_id=device_id)
        severity = self.request.query_params.get('severity')
        if severity:
            queryset = queryset.filter(fault__severity=severity)
        return queryset

    @action(detail=True, methods=['post'], url_path='read')
    def mark_read(self, request, pk=None):
        notification = mark_notification_read(self.get_object())
        return Response(self.get_serializer(notification).data)


class DashboardView(APIView):
    def get(self, request):
        devices = Device.objects.all()
        active_faults = FaultEvent.objects.filter(
            status__in=[FaultEvent.Status.ACTIVE, FaultEvent.Status.ACKNOWLEDGED]
        )
        device_health = []
        for device in devices:
            latest = device.monitoring_records.first()
            availability = None if latest is None else (100 if latest.reachable else 0)
            device_health.append({
                'id': str(device.id),
                'name': device.name,
                'address': device.ip_address,
                'type': device.device_type,
                'status': device.status,
                'availability': availability,
                'latencyMs': latest.latency_ms if latest else None,
                'packetLossPercent': latest.packet_loss_percent if latest else None,
            })
        faults = active_faults[:10]
        return Response({
            'summary': {
                'totalDevices': devices.count(),
                'onlineDevices': devices.filter(status=Device.Status.ONLINE).count(),
                'offlineDevices': devices.filter(status=Device.Status.OFFLINE).count(),
                'activeFaults': active_faults.count(),
            },
            'deviceHealth': device_health,
            'activeFaults': [
                {
                    'id': str(fault.id),
                    'deviceName': fault.device.name,
                    'title': fault.get_fault_type_display(),
                    'severity': fault.severity,
                    'detectedAt': fault.detected_at,
                    'description': fault.description or None,
                }
                for fault in faults
            ],
        })
