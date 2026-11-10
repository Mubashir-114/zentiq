"""
Core Views for ZENTIQ.
Includes versioned system health check endpoint with active database connectivity verification.
"""
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status, permissions
from django.db import connection
from django.utils import timezone
from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import serializers
import logging

logger = logging.getLogger('apps.core')

class HealthCheckView(APIView):
    """
    GET /api/v1/health/
    Performs active database connectivity check and returns accurate system health status,
    including backend API status, live database connectivity, and configured database engine.
    No credentials or sensitive internal infrastructure details are exposed.
    """
    permission_classes = [permissions.AllowAny]

    @extend_schema(
        summary="System Health Check",
        description="Verifies API availability, validates live database connectivity, and identifies configured database engine.",
        responses={
            200: inline_serializer(
                name="HealthSuccessResponse",
                fields={
                    "status": serializers.CharField(default="healthy"),
                    "version": serializers.CharField(default="1.0.0"),
                    "timestamp": serializers.DateTimeField(),
                    "services": serializers.DictField(child=serializers.CharField()),
                },
            ),
            503: inline_serializer(
                name="HealthFailureResponse",
                fields={
                    "status": serializers.CharField(default="unhealthy"),
                    "version": serializers.CharField(default="1.0.0"),
                    "timestamp": serializers.DateTimeField(),
                    "services": serializers.DictField(child=serializers.CharField()),
                },
            ),
        },
    )
    def get(self, request, *args, **kwargs):
        db_operational = False
        try:
            # Active database connectivity verification
            connection.ensure_connection()
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1;")
                row = cursor.fetchone()
                if row and row[0] == 1:
                    db_operational = True
        except Exception as exc:
            # Log the specific error internally; never leak to client
            logger.warning("Database connectivity check failed: %s", exc)
            db_operational = False

        # Determine configured database engine dynamically
        configured_engine = connection.settings_dict.get('ENGINE', '')
        if 'mysql' in configured_engine:
            engine_name = 'mysql'
        elif 'sqlite' in configured_engine:
            engine_name = 'sqlite'
        elif 'postgresql' in configured_engine or 'postgres' in configured_engine:
            engine_name = 'postgresql'
        else:
            engine_name = connection.vendor or 'unknown'

        services = {
            "api": "operational",
            "database": "operational" if db_operational else "unavailable",
            "database_connection": "operational" if db_operational else "unavailable",
            "database_engine": engine_name,
        }

        is_healthy = db_operational
        overall_status = "healthy" if is_healthy else "unhealthy"
        http_status = status.HTTP_200_OK if is_healthy else status.HTTP_503_SERVICE_UNAVAILABLE

        response_payload = {
            "status": overall_status,
            "version": "1.0.0",
            "timestamp": timezone.now().isoformat(),
            "services": services,
        }

        return Response(response_payload, status=http_status)
