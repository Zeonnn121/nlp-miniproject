from datetime import timedelta

from django.db import models
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Device
from .serializers import (
    DeviceSerializer,
    MonitoringConfigurationSerializer,
    MonitoringRecordSerializer,
    SNMPMetricSerializer,
)
from .snmp import collect_snmp_metrics, get_supported_metrics


class DeviceMonitoringSnapshotView(APIView):
    permission_classes = [IsAdminUser]

    DEFAULT_HISTORY_LIMIT = 50
    MAX_HISTORY_LIMIT = 500

    def history_limit(self, request):
        """Chart-friendly history depth, capped so the payload stays bounded."""
        value = request.query_params.get('history')
        if value is None:
            return self.DEFAULT_HISTORY_LIMIT
        try:
            requested = int(value)
        except (TypeError, ValueError):
            return self.DEFAULT_HISTORY_LIMIT
        return max(1, min(self.MAX_HISTORY_LIMIT, requested))

    def get(self, request, pk):
        device = get_object_or_404(
            Device.objects.select_related('monitoring_configuration'),
            pk=pk,
        )
        configuration = device.monitoring_configuration
        latest = device.monitoring_records.first()
        history = device.monitoring_records.all()[:self.history_limit(request)]
        snmp_metrics = device.snmp_metrics.order_by('-timestamp')

        latest_by_metric = {}
        for metric in snmp_metrics:
            latest_by_metric.setdefault(metric.metric, metric)

        metric_names = list(dict.fromkeys([
            *(configuration.available_metrics or []),
            *latest_by_metric.keys(),
        ]))
        snapshot_metrics = []
        for metric_name in metric_names:
            metric = latest_by_metric.get(metric_name)
            snapshot_metrics.append({
                'name': metric_name,
                'metricName': metric_name,
                'value': metric.value if metric else None,
                'available': metric is not None,
            })

        return Response({
            'device': DeviceSerializer(device).data,
            'latest': MonitoringRecordSerializer(latest).data if latest else None,
            'history': MonitoringRecordSerializer(history, many=True).data,
            'snmpMetrics': snapshot_metrics,
            'configuration': MonitoringConfigurationSerializer(configuration).data,
        })


class DeviceMonitoringSummaryView(APIView):
    permission_classes = [IsAdminUser]

    def get(self, request, pk):
        device = get_object_or_404(Device, pk=pk)
        hours_value = request.query_params.get('hours')
        try:
            hours = max(1, min(168, int(hours_value))) if hours_value else 24
        except (TypeError, ValueError):
            return Response(
                {'detail': 'hours must be an integer between 1 and 168.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        queryset = device.monitoring_records.filter(
            timestamp__gte=timezone.now() - timedelta(hours=hours)
        )
        total = queryset.count()
        reachable = queryset.filter(reachable=True).count()
        latest = queryset.first()
        average_latency = queryset.exclude(latency_ms__isnull=True).aggregate(
            value=models.Avg('latency_ms')
        )['value']
        average_packet_loss = queryset.exclude(packet_loss_percent__isnull=True).aggregate(
            value=models.Avg('packet_loss_percent')
        )['value']

        return Response({
            'deviceId': str(device.id),
            'hours': hours,
            'totalRecords': total,
            'reachableRecords': reachable,
            'unreachableRecords': total - reachable,
            'availabilityPercent': round(reachable / total * 100, 2) if total else None,
            'averageLatencyMs': round(average_latency, 3) if average_latency is not None else None,
            'averagePacketLossPercent': round(average_packet_loss, 3) if average_packet_loss is not None else None,
            'latest': MonitoringRecordSerializer(latest).data if latest else None,
            'records': total,
            'availability': reachable / total * 100 if total else None,
        })


class DeviceSNMPView(APIView):
    permission_classes = [IsAdminUser]

    def get_device(self, pk):
        return get_object_or_404(
            Device.objects.select_related('monitoring_configuration'),
            pk=pk,
        )

    def get(self, request, pk):
        device = self.get_device(pk)
        configuration = device.monitoring_configuration
        return Response({
            'configuration': MonitoringConfigurationSerializer(configuration).data,
            'supportedMetrics': get_supported_metrics(),
        })

    def patch(self, request, pk):
        device = self.get_device(pk)
        configuration = device.monitoring_configuration
        serializer = MonitoringConfigurationSerializer(
            configuration,
            data=request.data,
            partial=True,
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        configuration.refresh_from_db()
        return Response({
            'configuration': MonitoringConfigurationSerializer(configuration).data,
            'supportedMetrics': get_supported_metrics(),
        })

    def post(self, request, pk):
        device = self.get_device(pk)
        result = collect_snmp_metrics(device)
        metrics = device.snmp_metrics.filter(
            timestamp__gte=timezone.now() - timedelta(seconds=5)
        )
        response_status = status.HTTP_200_OK if result.status in {'success', 'partial'} else status.HTTP_400_BAD_REQUEST
        return Response({
            'status': result.status,
            'metrics': SNMPMetricSerializer(metrics, many=True).data,
            'errors': list(result.errors),
        }, status=response_status)
