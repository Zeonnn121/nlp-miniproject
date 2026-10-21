"""Tests for the optional fault explainer endpoint.

Model generation is always patched in these tests, so they never load any
model weights and remain runnable in a plain backend-only environment.
"""

from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APITestCase

from .llm_service import _parse_sections, build_prompt
from .models import Device, FaultEvent


LLM_RESULT = {
    'explanation': 'Latency is elevated because the path is congested.',
    'likely_causes': ['Congestion on the uplink.', 'QoS misconfiguration.'],
    'recommended_actions': ['Inspect uplink utilisation.', 'Review QoS policy.'],
    'source': 'llm',
}


class FaultExplainerTests(APITestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='admin',
            password='password123',
            is_staff=True,
        )
        self.device = Device.objects.create(
            name='Core Router',
            ip_address='10.0.0.1',
            device_type=Device.DeviceType.ROUTER,
        )
        self.fault = FaultEvent.objects.create(
            device=self.device,
            fault_type=FaultEvent.FaultType.HIGH_LATENCY,
            severity=FaultEvent.Severity.HIGH,
            detected_at=timezone.now() - timedelta(minutes=12),
            status=FaultEvent.Status.ACTIVE,
            description='Latency is 640.000 ms, above 500.000 ms.',
        )
        self.client.force_authenticate(self.user)

    def test_explain_endpoint_is_protected(self):
        self.client.force_authenticate(user=None)
        response = self.client.post(f'/api/faults/{self.fault.id}/explain/')
        self.assertEqual(response.status_code, 401)

    def test_explain_endpoint_requires_admin(self):
        operator = get_user_model().objects.create_user(
            username='operator',
            password='operator123',
        )
        self.client.force_authenticate(operator)
        response = self.client.post(f'/api/faults/{self.fault.id}/explain/')
        self.assertEqual(response.status_code, 403)

    def test_explain_missing_fault_returns_404(self):
        response = self.client.post('/api/faults/00000000-0000-0000-0000-000000000000/explain/')
        self.assertEqual(response.status_code, 404)

    @override_settings(LLM_ENABLED=False)
    def test_disabled_llm_returns_deterministic_fallback(self):
        response = self.client.post(f'/api/faults/{self.fault.id}/explain/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            set(response.data),
            {'explanation', 'likely_causes', 'recommended_actions', 'source'},
        )
        self.assertEqual(response.data['source'], 'fallback')
        self.assertIn('Round-trip latency', response.data['explanation'])
        self.assertIn('Latency is 640.000 ms', response.data['explanation'])
        self.assertGreaterEqual(len(response.data['likely_causes']), 3)
        self.assertGreaterEqual(len(response.data['recommended_actions']), 3)
        self.assertIsInstance(response.data['likely_causes'], list)
        self.assertIsInstance(response.data['recommended_actions'], list)

        self.fault.refresh_from_db()
        self.assertEqual(self.fault.explanation_cache, response.data)

    @override_settings(LLM_ENABLED=False)
    @patch('network.llm_service._load_model')
    def test_disabled_llm_never_loads_the_model(self, load_model):
        response = self.client.post(f'/api/faults/{self.fault.id}/explain/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['source'], 'fallback')
        load_model.assert_not_called()

    @override_settings(LLM_ENABLED=False)
    def test_fallback_covers_every_fault_type(self):
        for index, fault_type in enumerate(FaultEvent.FaultType.values):
            with self.subTest(fault_type=fault_type):
                device = Device.objects.create(
                    name=f'Device {index}',
                    ip_address=f'10.0.0.{index + 10}',
                    device_type=Device.DeviceType.ROUTER,
                )
                fault = FaultEvent.objects.create(
                    device=device,
                    fault_type=fault_type,
                    severity=FaultEvent.Severity.HIGH,
                    detected_at=timezone.now() - timedelta(minutes=5),
                    status=FaultEvent.Status.ACTIVE,
                )
                response = self.client.post(f'/api/faults/{fault.id}/explain/')

                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.data['source'], 'fallback')
                self.assertTrue(response.data['explanation'])
                self.assertTrue(response.data['likely_causes'])
                self.assertTrue(response.data['recommended_actions'])

    @override_settings(LLM_ENABLED=True)
    @patch('network.llm_service._generate_llm', side_effect=RuntimeError('model failed'))
    def test_llm_failure_falls_back_without_breaking_request(self, generate):
        response = self.client.post(f'/api/faults/{self.fault.id}/explain/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['source'], 'fallback')
        generate.assert_called_once()

    @override_settings(LLM_ENABLED=True)
    @patch('network.llm_service._generate_llm', return_value=LLM_RESULT)
    def test_llm_result_is_cached_on_the_fault(self, generate):
        first = self.client.post(f'/api/faults/{self.fault.id}/explain/')
        second = self.client.post(f'/api/faults/{self.fault.id}/explain/')

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(first.data['source'], 'llm')
        self.assertEqual(second.data, first.data)
        self.assertEqual(generate.call_count, 1)

        self.fault.refresh_from_db()
        self.assertEqual(self.fault.explanation_cache['source'], 'llm')

    @override_settings(LLM_ENABLED=True)
    @patch('network.llm_service._generate_llm', return_value=LLM_RESULT)
    def test_refresh_query_parameter_bypasses_cache(self, generate):
        self.fault.explanation_cache = {'explanation': 'stale'}
        self.fault.save(update_fields=['explanation_cache'])

        response = self.client.post(f'/api/faults/{self.fault.id}/explain/?refresh=true')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['source'], 'llm')
        generate.assert_called_once()

    def test_build_prompt_contains_fault_context(self):
        prompt = build_prompt(self.fault)

        self.assertTrue(prompt.startswith('You are a network operations assistant.'))
        self.assertIn('Device: Core Router (router)', prompt)
        self.assertIn('Fault type: HIGH_LATENCY', prompt)
        self.assertIn('Severity: high', prompt)
        self.assertIn('Fault duration: 12 minutes', prompt)
        self.assertIn('Details: Latency is 640.000 ms', prompt)

    def test_build_prompt_covers_every_fault_type(self):
        for index, fault_type in enumerate(FaultEvent.FaultType.values):
            with self.subTest(fault_type=fault_type):
                device = Device.objects.create(
                    name=f'Prompt Device {index}',
                    ip_address=f'10.0.1.{index + 10}',
                    device_type=Device.DeviceType.SWITCH,
                )
                fault = FaultEvent.objects.create(
                    device=device,
                    fault_type=fault_type,
                    severity=FaultEvent.Severity.MEDIUM,
                    detected_at=timezone.now() - timedelta(minutes=7),
                    status=FaultEvent.Status.ACTIVE,
                    description=f'Synthetic {fault_type} description.',
                )

                prompt = build_prompt(fault)

                self.assertTrue(prompt.startswith('You are a network operations assistant.'))
                self.assertIn(f'Device: Prompt Device {index} (switch)', prompt)
                self.assertIn(f'Fault type: {fault_type}', prompt)
                self.assertIn('Severity: medium', prompt)
                self.assertIn('Fault duration: 7 minutes', prompt)
                self.assertIn(f'Details: Synthetic {fault_type} description.', prompt)
                self.assertEqual(prompt.count('Fault type:'), 1)

    def test_parse_sections_extracts_labelled_lists(self):
        parsed = _parse_sections(
            'Explanation:\nLatency is high.\n\n'
            'Likely causes:\n1. Congestion.\n2. QoS policy.\n\n'
            'Recommended actions:\n- Inspect uplinks.\n- Review QoS.'
        )

        self.assertEqual(parsed['explanation'], 'Latency is high.')
        self.assertEqual(parsed['likely_causes'], ['Congestion.', 'QoS policy.'])
        self.assertEqual(parsed['recommended_actions'], ['Inspect uplinks.', 'Review QoS.'])
