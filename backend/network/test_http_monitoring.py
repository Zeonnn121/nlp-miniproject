"""Tests for HTTP endpoint monitoring: the probe, its fault rules, and its API."""

from datetime import timedelta
from unittest.mock import MagicMock, patch
import urllib.error

from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.authtoken.models import Token
from rest_framework.test import APITestCase

from .faults.detection import evaluate_monitoring_record
from .httpcheck import InvalidHTTPConfiguration, check_http_endpoint, validate_endpoint_url
from .models import Device, FaultEvent, MonitoringConfiguration, MonitoringRecord, Notification
from .monitoring import InvalidMonitoringConfiguration, PingResult, monitor_device

User = get_user_model()


def _response(status_code):
    """Build a context-manager stand-in for an opened urllib response."""
    response = MagicMock()
    response.getcode.return_value = status_code
    response.read.return_value = b'ok'
    response.__enter__.return_value = response
    return response


class HTTPProbeTests(APITestCase):
    def test_url_validation_rejects_non_http_schemes(self):
        for url in ('ftp://example.com/a', 'file:///etc/passwd', 'example.com'):
            with self.subTest(url=url):
                with self.assertRaises(InvalidHTTPConfiguration):
                    validate_endpoint_url(url)

    def test_url_validation_rejects_embedded_credentials(self):
        with self.assertRaises(InvalidHTTPConfiguration):
            validate_endpoint_url('https://user:pass@example.com/health')

    def test_url_validation_requires_a_host(self):
        with self.assertRaises(InvalidHTTPConfiguration):
            validate_endpoint_url('http://')

    @patch('network.httpcheck.services.urllib.request.urlopen')
    def test_successful_probe_reports_status_and_latency(self, urlopen):
        urlopen.return_value = _response(200)

        result = check_http_endpoint('https://example.com/health', timeout_seconds=2)

        self.assertTrue(result.ok)
        self.assertEqual(result.status_code, 200)
        self.assertIsNotNone(result.response_time_ms)
        self.assertIsNone(result.error)

    @patch('network.httpcheck.services.urllib.request.urlopen')
    def test_redirect_status_is_accepted_by_default(self, urlopen):
        urlopen.return_value = _response(301)

        result = check_http_endpoint('http://example.com/')

        self.assertTrue(result.ok)
        self.assertEqual(result.status_code, 301)

    @patch('network.httpcheck.services.urllib.request.urlopen')
    def test_unexpected_status_is_reported_as_failure(self, urlopen):
        urlopen.return_value = _response(503)

        result = check_http_endpoint('http://example.com/')

        self.assertFalse(result.ok)
        self.assertEqual(result.status_code, 503)
        self.assertIn('503', result.error)

    @patch('network.httpcheck.services.urllib.request.urlopen')
    def test_expected_status_can_be_pinned_exactly(self, urlopen):
        urlopen.return_value = _response(404)

        result = check_http_endpoint('http://example.com/gone', expected_status=404)

        self.assertTrue(result.ok)
        self.assertEqual(result.status_code, 404)

    @patch('network.httpcheck.services.urllib.request.urlopen')
    def test_connection_failure_is_recorded_without_status(self, urlopen):
        urlopen.side_effect = urllib.error.URLError('connection refused')

        result = check_http_endpoint('http://example.com/')

        self.assertFalse(result.ok)
        self.assertIsNone(result.status_code)
        self.assertIn('connection refused', result.error)

    @patch('network.httpcheck.services.urllib.request.urlopen')
    def test_server_error_status_is_captured_with_latency(self, urlopen):
        urlopen.side_effect = urllib.error.HTTPError(
            'http://example.com/', 401, 'Unauthorized', {}, None
        )

        result = check_http_endpoint('http://example.com/')

        self.assertFalse(result.ok)
        self.assertEqual(result.status_code, 401)

    def test_non_positive_timeout_is_rejected(self):
        with self.assertRaises(InvalidHTTPConfiguration):
            check_http_endpoint('http://example.com/', timeout_seconds=0)


class HTTPMonitoringRecordTests(APITestCase):
    def setUp(self):
        self.device = Device.objects.create(
            name='Web Server',
            ip_address='192.168.1.50',
            device_type=Device.DeviceType.SERVER,
        )
        self.configuration = self.device.monitoring_configuration
        self.configuration.http_monitoring_enabled = True
        self.configuration.http_url = 'https://example.com/health'
        self.configuration.http_timeout_seconds = 2.0
        self.configuration.save(
            update_fields=['http_monitoring_enabled', 'http_url', 'http_timeout_seconds']
        )

    @patch('network.monitoring.services.ping_ipv4')
    @patch('network.httpcheck.services.urllib.request.urlopen')
    def test_probe_results_are_stored_on_the_record(self, urlopen, ping):
        urlopen.return_value = _response(200)
        ping.return_value = PingResult(True, 12.5, 0.0)

        record = monitor_device(self.device)

        self.assertTrue(record.http_ok)
        self.assertEqual(record.http_status_code, 200)
        self.assertIsNotNone(record.http_response_time_ms)
        self.assertEqual(record.http_error, '')

    @patch('network.monitoring.services.ping_ipv4')
    @patch('network.httpcheck.services.urllib.request.urlopen')
    def test_failed_endpoint_is_stored_even_when_icmp_succeeds(self, urlopen, ping):
        urlopen.return_value = _response(500)
        ping.return_value = PingResult(True, 12.5, 0.0)

        record = monitor_device(self.device)

        self.assertFalse(record.http_ok)
        self.assertEqual(record.http_status_code, 500)
        self.assertIn('500', record.http_error)
        self.assertEqual(record.device.status, Device.Status.ONLINE)

    @patch('network.monitoring.services.ping_ipv4')
    def test_http_fields_stay_null_when_endpoint_is_disabled(self, ping):
        self.configuration.http_monitoring_enabled = False
        self.configuration.save(update_fields=['http_monitoring_enabled'])
        ping.return_value = PingResult(True, 12.5, 0.0)

        record = monitor_device(self.device)

        self.assertIsNone(record.http_ok)
        self.assertIsNone(record.http_status_code)
        self.assertIsNone(record.http_response_time_ms)
        self.assertEqual(record.http_error, '')

    @patch('network.monitoring.services.ping_ipv4')
    def test_enabled_endpoint_without_url_is_a_configuration_error(self, ping):
        self.configuration.http_url = ''
        self.configuration.save(update_fields=['http_url'])
        ping.return_value = PingResult(True, 12.5, 0.0)

        with self.assertRaises(InvalidMonitoringConfiguration):
            monitor_device(self.device)
        self.assertEqual(MonitoringRecord.objects.count(), 0)


class HTTPFaultDetectionTests(APITestCase):
    def setUp(self):
        self.device = Device.objects.create(
            name='Portal',
            ip_address='192.168.1.60',
            device_type=Device.DeviceType.SERVER,
        )

    def record(self, *, timestamp=None, **values):
        defaults = {'reachable': True, 'latency_ms': 20.0, 'packet_loss_percent': 0.0}
        defaults.update(values)
        return MonitoringRecord.objects.create(
            device=self.device,
            timestamp=timestamp or timezone.now(),
            **defaults,
        )

    def active_faults(self):
        return FaultEvent.objects.filter(
            device=self.device,
            status__in=[FaultEvent.Status.ACTIVE, FaultEvent.Status.ACKNOWLEDGED],
        )

    def test_connection_failure_creates_critical_fault(self):
        record = self.record(http_ok=False, http_status_code=None, http_error='HTTP request timed out.')

        evaluate_monitoring_record(record)

        fault = self.active_faults().get(fault_type=FaultEvent.FaultType.HTTP_ENDPOINT_FAILURE)
        self.assertEqual(fault.severity, FaultEvent.Severity.CRITICAL)
        self.assertTrue(Notification.objects.filter(fault=fault).exists())

    def test_unexpected_status_creates_high_severity_fault(self):
        record = self.record(
            http_ok=False, http_status_code=503, http_error='Endpoint returned HTTP 503.'
        )

        evaluate_monitoring_record(record)

        fault = self.active_faults().get(fault_type=FaultEvent.FaultType.HTTP_ENDPOINT_FAILURE)
        self.assertEqual(fault.severity, FaultEvent.Severity.HIGH)
        self.assertIn('503', fault.description)

    def test_slow_response_severity_follows_thresholds(self):
        evaluate_monitoring_record(
            self.record(http_ok=True, http_status_code=200, http_response_time_ms=4200.0)
        )
        fault = self.active_faults().get(fault_type=FaultEvent.FaultType.HTTP_SLOW_RESPONSE)
        self.assertEqual(fault.severity, FaultEvent.Severity.HIGH)

        evaluate_monitoring_record(
            self.record(http_ok=True, http_status_code=200, http_response_time_ms=1500.0)
        )
        fault.refresh_from_db()
        self.assertEqual(fault.severity, FaultEvent.Severity.MEDIUM)

    def test_recovered_endpoint_resolves_active_fault(self):
        evaluate_monitoring_record(
            self.record(http_ok=False, http_status_code=500, http_error='Endpoint returned HTTP 500.')
        )
        self.assertTrue(self.active_faults().exists())

        evaluate_monitoring_record(
            self.record(http_ok=True, http_status_code=200, http_response_time_ms=45.0)
        )

        self.assertFalse(self.active_faults().exists())
        resolved = FaultEvent.objects.get(
            device=self.device,
            fault_type=FaultEvent.FaultType.HTTP_ENDPOINT_FAILURE,
        )
        self.assertEqual(resolved.status, FaultEvent.Status.RESOLVED)
        self.assertIsNotNone(resolved.resolved_at)

    def test_healthy_fast_endpoint_creates_no_fault(self):
        evaluate_monitoring_record(
            self.record(http_ok=True, http_status_code=200, http_response_time_ms=80.0)
        )

        self.assertFalse(FaultEvent.objects.filter(device=self.device).exists())

    def test_records_without_http_data_never_raise_http_faults(self):
        evaluate_monitoring_record(self.record())

        self.assertFalse(FaultEvent.objects.filter(device=self.device).exists())

    def test_http_and_icmp_faults_are_evaluated_independently(self):
        evaluate_monitoring_record(
            self.record(
                reachable=False,
                latency_ms=None,
                packet_loss_percent=100.0,
                http_ok=False,
                http_status_code=None,
                http_error='HTTP request failed: refused',
            )
        )

        self.assertEqual(
            set(self.active_faults().values_list('fault_type', flat=True)),
            {
                FaultEvent.FaultType.DEVICE_UNREACHABLE,
                FaultEvent.FaultType.HTTP_ENDPOINT_FAILURE,
            },
        )

    def test_disabling_the_endpoint_clears_a_lingering_fault(self):
        evaluate_monitoring_record(
            self.record(http_ok=False, http_status_code=500, http_error='Endpoint returned HTTP 500.')
        )
        self.assertTrue(self.active_faults().exists())

        # A later run with no HTTP probe configured, e.g. the endpoint was turned off.
        evaluate_monitoring_record(self.record())

        self.assertFalse(self.active_faults().exists())


class HTTPMonitoringAPITests(APITestCase):
    def setUp(self):
        user = User.objects.create_user(
            username='admin',
            email='admin@example.com',
            password='admin123',
            is_staff=True,
        )
        token = Token.objects.create(user=user)
        self.client.credentials(HTTP_AUTHORIZATION=f'Token {token.key}')
        self.device = Device.objects.create(
            name='Portal',
            ip_address='192.168.1.70',
            device_type=Device.DeviceType.SERVER,
        )
        self.config_url = f'/api/devices/{self.device.id}/monitoring-config/'
        self.configuration = MonitoringConfiguration.objects.get(device=self.device)

    def test_configuration_round_trips_through_the_api(self):
        response = self.client.patch(
            self.config_url,
            {
                'httpMonitoringEnabled': True,
                'httpUrl': 'https://example.com/health',
                'httpTimeoutSeconds': 3.5,
                'httpExpectedStatus': 204,
            },
            format='json',
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data['httpMonitoringEnabled'])
        self.assertEqual(response.data['httpUrl'], 'https://example.com/health')
        self.assertEqual(response.data['httpTimeoutSeconds'], 3.5)
        self.assertEqual(response.data['httpExpectedStatus'], 204)

        self.configuration.refresh_from_db()
        self.assertTrue(self.configuration.http_monitoring_enabled)

    def test_enabling_without_a_url_is_rejected(self):
        response = self.client.patch(self.config_url, {'httpMonitoringEnabled': True}, format='json')

        self.assertEqual(response.status_code, 400)
        self.assertIn('httpUrl', response.data)
        self.configuration.refresh_from_db()
        self.assertFalse(self.configuration.http_monitoring_enabled)

    def test_unsupported_scheme_is_rejected(self):
        response = self.client.patch(
            self.config_url,
            {'httpMonitoringEnabled': True, 'httpUrl': 'ftp://example.com/x'},
            format='json',
        )

        self.assertEqual(response.status_code, 400)
        self.configuration.refresh_from_db()
        self.assertFalse(self.configuration.http_monitoring_enabled)

    def test_bounds_are_enforced(self):
        self.assertEqual(
            self.client.patch(self.config_url, {'httpTimeoutSeconds': 900}, format='json').status_code,
            400,
        )
        self.assertEqual(
            self.client.patch(self.config_url, {'httpExpectedStatus': 999}, format='json').status_code,
            400,
        )

    def test_configuration_is_visible_on_the_monitoring_snapshot(self):
        self.client.patch(
            self.config_url,
            {'httpMonitoringEnabled': True, 'httpUrl': 'https://example.com/health'},
            format='json',
        )

        response = self.client.get(f'/api/devices/{self.device.id}/monitoring-snapshot/')

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data['configuration']['httpMonitoringEnabled'])
        self.assertEqual(response.data['configuration']['httpUrl'], 'https://example.com/health')

    def test_snapshot_history_depth_honours_the_query_parameter(self):
        for offset in range(5):
            MonitoringRecord.objects.create(
                device=self.device,
                timestamp=timezone.now() + timedelta(seconds=offset),
                reachable=True,
                latency_ms=10.0,
                packet_loss_percent=0.0,
            )

        limited = self.client.get(
            f'/api/devices/{self.device.id}/monitoring-snapshot/?history=2'
        )
        self.assertEqual(limited.status_code, 200)
        self.assertEqual(len(limited.data['history']), 2)

        defaulted = self.client.get(f'/api/devices/{self.device.id}/monitoring-snapshot/')
        self.assertEqual(len(defaulted.data['history']), 5)

        # A non-numeric value must fall back rather than error out.
        ignored = self.client.get(
            f'/api/devices/{self.device.id}/monitoring-snapshot/?history=abc'
        )
        self.assertEqual(ignored.status_code, 200)
        self.assertEqual(len(ignored.data['history']), 5)

    @patch('network.monitoring.services.ping_ipv4')
    @patch('network.httpcheck.services.urllib.request.urlopen')
    def test_monitor_endpoint_returns_http_fields(self, urlopen, ping):
        urlopen.return_value = _response(200)
        ping.return_value = PingResult(True, 15.0, 0.0)
        self.client.patch(
            self.config_url,
            {'httpMonitoringEnabled': True, 'httpUrl': 'https://example.com/health'},
            format='json',
        )

        response = self.client.post(f'/api/devices/{self.device.id}/monitor/', {}, format='json')

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data['httpOk'])
        self.assertEqual(response.data['httpStatusCode'], 200)
        self.assertIsNotNone(response.data['httpResponseTimeMs'])
