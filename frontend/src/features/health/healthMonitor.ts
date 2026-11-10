/**
 * Framework-agnostic helpers for the centralized health monitor.
 * Kept free of React / fetch imports so the polling rules are unit-testable.
 */

import type { HealthResponse } from '../../types';

/** Normal polling cadence for /api/v1/health/. */
export const HEALTH_POLL_INTERVAL_MS = 45_000;

/** Back-off applied after a 429 so throttled clients do not create retry loops. */
export const HEALTH_RATE_LIMIT_BACKOFF_MS = 60_000;

export type HealthState = 'loading' | 'healthy' | 'degraded' | 'unhealthy' | 'offline';

/**
 * Derives the UI state from the latest payload and request error.
 * `offline` covers transport failures and 429s; a 503 payload is still a
 * successful response and maps to `unhealthy`.
 */
export function deriveHealthState(
  health: HealthResponse | null,
  error: string | null
): HealthState {
  if (error) return 'offline';
  if (!health) return 'loading';
  if (health.status === 'healthy') return 'healthy';
  if (health.status === 'degraded') return 'degraded';
  return 'unhealthy';
}

/** Chooses the delay before the next automatic poll. */
export function resolveNextPollDelay(
  isRateLimited: boolean,
  pollIntervalMs: number = HEALTH_POLL_INTERVAL_MS
): number {
  return isRateLimited ? Math.max(HEALTH_RATE_LIMIT_BACKOFF_MS, pollIntervalMs) : pollIntervalMs;
}

/**
 * Wraps an async function so concurrent callers share one in-flight request.
 * The slot is released on settle, so the next call starts a fresh request.
 */
export function createSingleFlight<T>(fn: () => Promise<T>): () => Promise<T> {
  let inFlight: Promise<T> | null = null;

  return () => {
    if (!inFlight) {
      inFlight = fn().finally(() => {
        inFlight = null;
      });
    }
    return inFlight;
  };
}
