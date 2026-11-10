import { describe, it } from 'node:test';
import assert from 'node:assert/strict';

import {
  createSingleFlight,
  deriveHealthState,
  HEALTH_POLL_INTERVAL_MS,
  HEALTH_RATE_LIMIT_BACKOFF_MS,
  resolveNextPollDelay,
} from '../src/features/health/healthMonitor.ts';
import type { HealthResponse } from '../src/types/index.ts';

function makeHealth(status: HealthResponse['status']): HealthResponse {
  return {
    status,
    version: '1.0.0',
    timestamp: '2026-11-09T00:00:00Z',
    services: { api: 'operational', database: 'operational' },
  };
}

describe('ZENTIQ Health Monitor', () => {
  describe('deriveHealthState', () => {
    it('reports loading before the first payload', () => {
      assert.equal(deriveHealthState(null, null), 'loading');
    });

    it('reports offline on request failure, even with a stale payload', () => {
      assert.equal(deriveHealthState(makeHealth('healthy'), 'Rate limited'), 'offline');
    });

    it('preserves healthy, degraded and unhealthy payload states', () => {
      assert.equal(deriveHealthState(makeHealth('healthy'), null), 'healthy');
      assert.equal(deriveHealthState(makeHealth('degraded'), null), 'degraded');
      assert.equal(deriveHealthState(makeHealth('unhealthy'), null), 'unhealthy');
    });
  });

  describe('resolveNextPollDelay', () => {
    it('uses the normal polling cadence of 45 seconds', () => {
      assert.equal(HEALTH_POLL_INTERVAL_MS, 45_000);
      assert.equal(resolveNextPollDelay(false), 45_000);
    });

    it('backs off for at least 60 seconds after a 429', () => {
      assert.equal(HEALTH_RATE_LIMIT_BACKOFF_MS, 60_000);
      assert.equal(resolveNextPollDelay(true), 60_000);
      assert.equal(resolveNextPollDelay(true, 120_000), 120_000);
    });
  });

  describe('createSingleFlight', () => {
    it('shares one in-flight request between concurrent callers', async () => {
      let calls = 0;
      let release: (value: string) => void = () => {};
      const deduped = createSingleFlight(() => {
        calls += 1;
        return new Promise<string>((resolve) => {
          release = resolve;
        });
      });

      const first = deduped();
      const second = deduped();
      assert.equal(calls, 1);
      assert.equal(first, second);

      release('ok');
      assert.equal(await first, 'ok');
      assert.equal(await second, 'ok');
    });

    it('starts a fresh request after the previous one settles', async () => {
      let calls = 0;
      const deduped = createSingleFlight(async () => {
        calls += 1;
        return calls;
      });

      assert.equal(await deduped(), 1);
      assert.equal(await deduped(), 2);
      assert.equal(calls, 2);
    });

    it('releases the slot when a request rejects so a retry can run', async () => {
      let calls = 0;
      const deduped = createSingleFlight(async () => {
        calls += 1;
        if (calls === 1) throw new Error('boom');
        return 'recovered';
      });

      await assert.rejects(deduped, /boom/);
      assert.equal(await deduped(), 'recovered');
      assert.equal(calls, 2);
    });
  });
});
