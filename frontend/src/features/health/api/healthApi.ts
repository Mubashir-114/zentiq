import { apiClient, ApiClientError } from '../../../lib/api-client';
import type { HealthResponse } from '../../../types';
import { createSingleFlight } from '../healthMonitor';

function isHealthResponse(value: unknown): value is HealthResponse {
  if (!value || typeof value !== 'object') return false;
  const candidate = value as Partial<HealthResponse>;
  return typeof candidate.status === 'string' && typeof candidate.services === 'object';
}

/**
 * Fetches the backend health status from /api/v1/health/.
 * Concurrent callers share a single in-flight request, and the 503 payload
 * (database unavailable) is still returned so the UI can show "unhealthy"
 * instead of treating it as a transport failure.
 */
const requestHealthStatus = createSingleFlight(async (): Promise<HealthResponse> => {
  try {
    return await apiClient.get<HealthResponse>('/health/');
  } catch (error) {
    if (error instanceof ApiClientError && error.status === 503 && isHealthResponse(error.details)) {
      return error.details;
    }
    throw error;
  }
});

export function getHealthStatus(): Promise<HealthResponse> {
  return requestHealthStatus();
}
