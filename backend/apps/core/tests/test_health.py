"""
Tests for ZENTIQ Core Health Endpoint.
Verifies active database connectivity reporting, dynamic engine identification, and security.
"""
from django.test import TestCase
from django.urls import reverse
from unittest.mock import patch
from django.db import DatabaseError, connection
from rest_framework import status

class HealthCheckEndpointTests(TestCase):
    """Test suite for GET /api/v1/health/."""

    def test_health_check_operational(self):
        """Test health endpoint returns 200, operational status, API status, and actual engine."""
        url = reverse('core:health-check')
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['status'], 'healthy')
        self.assertEqual(response.data['version'], '1.0.0')
        self.assertIn('timestamp', response.data)
        self.assertEqual(response.data['services']['api'], 'operational')
        self.assertEqual(response.data['services']['database'], 'operational')
        self.assertEqual(response.data['services']['database_connection'], 'operational')
        self.assertEqual(response.data['services']['database_engine'], 'sqlite')

    def test_health_check_database_failure(self):
        """Test health endpoint returns 503 and unavailable status when DB fails, while preserving engine info."""
        url = reverse('core:health-check')
        with patch('django.db.connection.ensure_connection', side_effect=DatabaseError("Simulated DB connection lost")):
            response = self.client.get(url)

            self.assertEqual(response.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)
            self.assertEqual(response.data['status'], 'unhealthy')
            self.assertEqual(response.data['services']['api'], 'operational')
            self.assertEqual(response.data['services']['database'], 'unavailable')
            self.assertEqual(response.data['services']['database_connection'], 'unavailable')
            self.assertEqual(response.data['services']['database_engine'], 'sqlite')
            # Verify no sensitive stack trace or internal message leaked
            self.assertNotIn("Simulated DB connection lost", str(response.data))

    def test_health_check_reports_mysql_engine_when_configured(self):
        """Test health endpoint reports mysql when mysql backend is configured."""
        url = reverse('core:health-check')
        mock_settings = dict(connection.settings_dict)
        mock_settings['ENGINE'] = 'django.db.backends.mysql'

        with patch.object(connection, 'settings_dict', mock_settings):
            response = self.client.get(url)
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertEqual(response.data['services']['database_engine'], 'mysql')

    def test_health_check_payload_structure_and_no_credential_leak(self):
        """Ensure response contains only sanitized system status fields."""
        url = reverse('core:health-check')
        response = self.client.get(url)

        expected_keys = {'status', 'version', 'timestamp', 'services'}
        self.assertEqual(set(response.data.keys()), expected_keys)
        self.assertNotIn('password', response.content.decode().lower())
        self.assertNotIn('secret', response.content.decode().lower())
