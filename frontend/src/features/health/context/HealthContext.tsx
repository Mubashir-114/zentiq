import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react';
import { ApiClientError } from '../../../lib/api-client';
import type { HealthResponse } from '../../../types';
import { getHealthStatus } from '../api/healthApi';
import {
  deriveHealthState,
  HEALTH_POLL_INTERVAL_MS,
  HEALTH_RATE_LIMIT_BACKOFF_MS,
  resolveNextPollDelay,
  type HealthState,
} from '../healthMonitor';

export interface HealthContextValue {
  health: HealthResponse | null;
  state: HealthState;
  isHealthy: boolean | null;
  error: string | null;
  isRefreshing: boolean;
  lastUpdated: number | null;
  /** Manual re-check. Respects the 429 back-off window. */
  refresh: () => Promise<void>;
}

const HealthContext = createContext<HealthContextValue | undefined>(undefined);

interface HealthProviderProps {
  children: ReactNode;
  pollIntervalMs?: number;
}

/**
 * Single owner of /api/v1/health/ polling for the whole application shell.
 * - one shared request at a time (healthApi single-flight + provider guard)
 * - 45s cadence, paused while the document is hidden
 * - 429 responses back off for 60s instead of triggering retries
 * - all timers and listeners are cleaned up on unmount
 */
export function HealthProvider({ children, pollIntervalMs = HEALTH_POLL_INTERVAL_MS }: HealthProviderProps) {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [lastUpdated, setLastUpdated] = useState<number | null>(null);

  const mountedRef = useRef(true);
  const requestRef = useRef<Promise<void> | null>(null);
  const rateLimitedRef = useRef(false);
  const lastUpdatedRef = useRef<number | null>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const check = useCallback((): Promise<void> => {
    if (requestRef.current) return requestRef.current;

    setIsRefreshing(true);

    const request = (async () => {
      try {
        const data = await getHealthStatus();
        if (!mountedRef.current) return;
        setHealth(data);
        setError(null);
        rateLimitedRef.current = false;
      } catch (err) {
        if (!mountedRef.current) return;
        rateLimitedRef.current = err instanceof ApiClientError && err.status === 429;
        setHealth(null);
        setError(err instanceof Error ? err.message : 'Failed to connect to backend');
      } finally {
        const now = Date.now();
        lastUpdatedRef.current = now;
        if (mountedRef.current) {
          setLastUpdated(now);
          setIsRefreshing(false);
        }
        requestRef.current = null;
      }
    })();

    requestRef.current = request;
    return request;
  }, []);

  const refresh = useCallback(async (): Promise<void> => {
    const last = lastUpdatedRef.current;
    const inBackoff =
      rateLimitedRef.current && last !== null && Date.now() - last < HEALTH_RATE_LIMIT_BACKOFF_MS;
    if (inBackoff) return;
    await check();
  }, [check]);

  useEffect(() => {
    mountedRef.current = true;
    let cancelled = false;

    const clearTimer = () => {
      if (timerRef.current !== null) {
        clearTimeout(timerRef.current);
        timerRef.current = null;
      }
    };

    const schedule = (delay: number) => {
      if (cancelled) return;
      clearTimer();
      timerRef.current = setTimeout(() => {
        void tick();
      }, delay);
    };

    const tick = async () => {
      if (cancelled) return;
      if (typeof document !== 'undefined' && document.visibilityState === 'hidden') {
        // App context is inactive: keep the loop idle until visibility returns.
        schedule(pollIntervalMs);
        return;
      }
      await check();
      if (cancelled) return;
      schedule(resolveNextPollDelay(rateLimitedRef.current, pollIntervalMs));
    };

    const handleVisibilityChange = () => {
      if (typeof document === 'undefined') return;
      if (document.visibilityState === 'hidden') {
        clearTimer();
        return;
      }
      const last = lastUpdatedRef.current;
      if (last === null || Date.now() - last >= pollIntervalMs) {
        void tick();
      } else {
        schedule(pollIntervalMs - (Date.now() - last));
      }
    };

    document.addEventListener('visibilitychange', handleVisibilityChange);

    void check().then(() => {
      if (cancelled) return;
      schedule(resolveNextPollDelay(rateLimitedRef.current, pollIntervalMs));
    });

    return () => {
      cancelled = true;
      mountedRef.current = false;
      clearTimer();
      document.removeEventListener('visibilitychange', handleVisibilityChange);
    };
  }, [check, pollIntervalMs]);

  const state = deriveHealthState(health, error);
  const isHealthy = state === 'loading' ? null : state === 'healthy';

  const value = useMemo<HealthContextValue>(
    () => ({ health, state, isHealthy, error, isRefreshing, lastUpdated, refresh }),
    [health, state, isHealthy, error, isRefreshing, lastUpdated, refresh]
  );

  return <HealthContext.Provider value={value}>{children}</HealthContext.Provider>;
}

export function useHealth(): HealthContextValue {
  const context = useContext(HealthContext);
  if (!context) {
    throw new Error('useHealth must be used within a HealthProvider');
  }
  return context;
}
