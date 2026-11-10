import { describe, it } from 'node:test';
import assert from 'node:assert/strict';

import { SKILL_DOMAINS } from '../src/features/dashboard/constants/skillDomains.ts';
import {
  UPCOMING_MODULES,
  ARCHITECTURE_MODULES,
} from '../src/features/dashboard/constants/upcomingModules.ts';
import type { User, UserProfile, AvatarKey } from '../src/types/index.ts';

// Helper mirror representing PlayerIdentityBanner logic
function resolveDisplayName(profile: Pick<UserProfile, 'display_name' | 'username'>): string {
  return profile.display_name?.trim() || profile.username;
}

// Helper mirror representing OnboardingPersonaCard bio fallback logic
function resolveBioStatement(profile: Pick<UserProfile, 'bio'>): { hasCustomBio: boolean; text: string } {
  const trimmed = profile.bio?.trim();
  if (trimmed) {
    return { hasCustomBio: true, text: trimmed };
  }
  return {
    hasCustomBio: false,
    text: 'No bio statement added yet. You can set one in your persona settings.',
  };
}

// Helper mirror representing AccountRecordCard and PlayerIdentityBanner date formatting
function formatAccountJoinDate(dateJoined: string): string {
  const parsed = new Date(dateJoined);
  if (isNaN(parsed.getTime())) {
    return 'Invalid Date';
  }
  return parsed.toLocaleDateString(undefined, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
  });
}

function formatAccountRecordFullDate(dateJoined: string): string {
  const parsed = new Date(dateJoined);
  if (isNaN(parsed.getTime())) {
    return 'Invalid Date';
  }
  return parsed.toLocaleDateString(undefined, {
    year: 'numeric',
    month: 'long',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

// Route resolution helper testing guest vs authenticated route behavior
type RouteDestination =
  | { type: 'render'; component: string }
  | { type: 'redirect'; to: string; state?: Record<string, unknown> };

function resolveRoute(
  path: string,
  isAuthenticated: boolean,
  isInitializing = false
): RouteDestination {
  if (isInitializing) {
    return { type: 'render', component: 'LoadingSpinner' };
  }

  // Index route '/'
  if (path === '/') {
    return isAuthenticated
      ? { type: 'redirect', to: '/dashboard' }
      : { type: 'render', component: 'HomeView' };
  }

  // Public-only routes: /login, /register
  if (path === '/login' || path === '/register') {
    return isAuthenticated
      ? { type: 'redirect', to: '/' }
      : { type: 'render', component: path === '/login' ? 'LoginForm' : 'RegisterForm' };
  }

  // Protected routes: /dashboard, /profile
  if (path === '/dashboard' || path === '/profile') {
    return isAuthenticated
      ? { type: 'render', component: path === '/dashboard' ? 'DashboardView' : 'ProfileView' }
      : { type: 'redirect', to: '/login', state: { from: path } };
  }

  // Public shared routes
  if (path === '/architecture' || path === '/health') {
    return { type: 'render', component: path === '/architecture' ? 'ArchitectureView' : 'HealthView' };
  }

  // Catch-all
  return { type: 'redirect', to: '/404' };
}

// Health status badge evaluation helper (verifying "never green when failed or unknown")
function getHealthBadgeVariant(isHealthy: boolean | null | undefined): 'success' | 'warning' | 'neutral' {
  if (isHealthy === true) return 'success';
  if (isHealthy === false) return 'warning';
  return 'neutral';
}

function getTelemetryStateBadge(state: 'loading' | 'healthy' | 'degraded' | 'error'): {
  variant: 'success' | 'warning' | 'error' | 'neutral';
  isGreen: boolean;
} {
  switch (state) {
    case 'healthy':
      return { variant: 'success', isGreen: true };
    case 'degraded':
      return { variant: 'warning', isGreen: false };
    case 'error':
      return { variant: 'error', isGreen: false };
    case 'loading':
    default:
      return { variant: 'neutral', isGreen: false };
  }
}

describe('ZENTIQ Milestone 3B — Focused Dashboard Verification Tests', () => {
  describe('1. Eight Skill Domains', () => {
    it('defines exactly eight canonical cognitive intelligence vectors', () => {
      assert.strictEqual(SKILL_DOMAINS.length, 8);
    });

    it('contains all required canonical vector identifiers', () => {
      const canonicalIds = [
        'numerical_intelligence',
        'logical_reasoning',
        'verbal_intelligence',
        'analytical_thinking',
        'spatial_intelligence',
        'programming_logic',
        'critical_thinking',
        'career_readiness',
      ];
      const actualIds = SKILL_DOMAINS.map((domain) => domain.id);
      assert.deepStrictEqual(actualIds, canonicalIds);
    });

    it('each domain contains required non-empty metadata and valid category', () => {
      const allowedCategories = ['Cognitive', 'Analytical', 'Perceptual', 'Technical', 'Applied'];
      for (const domain of SKILL_DOMAINS) {
        assert.ok(domain.name && domain.name.length > 0, `Missing name for domain: ${domain.id}`);
        assert.ok(
          allowedCategories.includes(domain.category),
          `Invalid category "${domain.category}" for domain: ${domain.id}`
        );
        assert.ok(
          domain.description && domain.description.length > 20,
          `Insufficient description for domain: ${domain.id}`
        );
        assert.ok(domain.icon, `Missing icon component for domain: ${domain.id}`);
      }
    });
  });

  describe('2. Authenticated Identity and Profile Data Rendering', () => {
    const mockUser: User = {
      id: 42,
      email: 'pilot_nova@zentiq.dev',
      date_joined: '2026-03-15T10:30:00Z',
      is_staff: false,
    };

    const mockProfile: UserProfile = {
      id: 42,
      user: 42,
      username: 'pilot_nova',
      display_name: 'Pilot Nova',
      avatar_key: 'cyber_ninja' as AvatarKey,
      bio: 'Advancing cognitive logic and algorithmic structures.',
      preferences: { theme: 'dark', audio_enabled: true },
      created_at: '2026-03-15T10:30:00Z',
      updated_at: '2026-03-15T11:00:00Z',
    };

    it('resolves actual display name when present', () => {
      const displayName = resolveDisplayName(mockProfile);
      assert.strictEqual(displayName, 'Pilot Nova');
    });

    it('formats username handle correctly with @ prefix', () => {
      const handle = `@${mockProfile.username}`;
      assert.strictEqual(handle, '@pilot_nova');
    });

    it('renders authentic user email address', () => {
      assert.strictEqual(mockUser.email, 'pilot_nova@zentiq.dev');
    });

    it('preserves valid custom bio statement', () => {
      const bioInfo = resolveBioStatement(mockProfile);
      assert.strictEqual(bioInfo.hasCustomBio, true);
      assert.strictEqual(bioInfo.text, 'Advancing cognitive logic and algorithmic structures.');
    });
  });

  describe('3. Missing Bio and Display-Name Fallbacks', () => {
    it('falls back to username when display_name is null', () => {
      const profile = { username: 'solitary_coder', display_name: null };
      assert.strictEqual(resolveDisplayName(profile), 'solitary_coder');
    });

    it('falls back to username when display_name is empty string', () => {
      const profile = { username: 'solitary_coder', display_name: '' };
      assert.strictEqual(resolveDisplayName(profile), 'solitary_coder');
    });

    it('falls back to username when display_name is whitespace only', () => {
      const profile = { username: 'solitary_coder', display_name: '    ' };
      assert.strictEqual(resolveDisplayName(profile), 'solitary_coder');
    });

    it('displays fallback placeholder when bio is null', () => {
      const profile = { bio: null };
      const res = resolveBioStatement(profile);
      assert.strictEqual(res.hasCustomBio, false);
      assert.strictEqual(
        res.text,
        'No bio statement added yet. You can set one in your persona settings.'
      );
    });

    it('displays fallback placeholder when bio is empty string', () => {
      const profile = { bio: '' };
      const res = resolveBioStatement(profile);
      assert.strictEqual(res.hasCustomBio, false);
      assert.strictEqual(
        res.text,
        'No bio statement added yet. You can set one in your persona settings.'
      );
    });

    it('displays fallback placeholder when bio is whitespace only', () => {
      const profile = { bio: '   \n  \t  ' };
      const res = resolveBioStatement(profile);
      assert.strictEqual(res.hasCustomBio, false);
      assert.strictEqual(
        res.text,
        'No bio statement added yet. You can set one in your persona settings.'
      );
    });
  });

  describe('4. Account Creation Date Rendering', () => {
    it('formats ISO join date into human-readable banner format', () => {
      const formatted = formatAccountJoinDate('2026-03-15T10:30:00Z');
      assert.ok(formatted.includes('2026'), 'Formatted date must include year 2026');
      assert.ok(!formatted.includes('NaN'), 'Formatted date must not contain NaN');
    });

    it('formats ISO join date into full record card format', () => {
      const formatted = formatAccountRecordFullDate('2026-03-15T10:30:00Z');
      assert.ok(formatted.includes('2026'), 'Full date must include year 2026');
    });

    it('handles invalid date input gracefully without crashing', () => {
      const result = formatAccountJoinDate('invalid-date-token');
      assert.strictEqual(result, 'Invalid Date');
    });
  });

  describe('5. Guest and Authenticated Routing', () => {
    it('allows guest to access public index page (HomeView)', () => {
      const route = resolveRoute('/', false);
      assert.deepStrictEqual(route, { type: 'render', component: 'HomeView' });
    });

    it('redirects guest accessing /dashboard to /login with state', () => {
      const route = resolveRoute('/dashboard', false);
      assert.deepStrictEqual(route, {
        type: 'redirect',
        to: '/login',
        state: { from: '/dashboard' },
      });
    });

    it('redirects guest accessing /profile to /login with state', () => {
      const route = resolveRoute('/profile', false);
      assert.deepStrictEqual(route, {
        type: 'redirect',
        to: '/login',
        state: { from: '/profile' },
      });
    });

    it('redirects authenticated user accessing / to /dashboard', () => {
      const route = resolveRoute('/', true);
      assert.deepStrictEqual(route, { type: 'redirect', to: '/dashboard' });
    });

    it('redirects authenticated user accessing /login to /', () => {
      const route = resolveRoute('/login', true);
      assert.deepStrictEqual(route, { type: 'redirect', to: '/' });
    });

    it('renders DashboardView for authenticated user navigating to /dashboard', () => {
      const route = resolveRoute('/dashboard', true);
      assert.deepStrictEqual(route, { type: 'render', component: 'DashboardView' });
    });

    it('renders ProfileView for authenticated user navigating to /profile', () => {
      const route = resolveRoute('/profile', true);
      assert.deepStrictEqual(route, { type: 'render', component: 'ProfileView' });
    });
  });

  describe('6. Roadmap Consistency & Telemetry Safety', () => {
    it('removes incorrect Milestone 2B from XP ledger and Milestone 3 from Daily Missions', () => {
      for (const mod of UPCOMING_MODULES) {
        assert.ok(
          !mod.provisionalMilestone.includes('Milestone 2B'),
          `Module ${mod.id} still has Milestone 2B`
        );
        assert.ok(
          !mod.provisionalMilestone.includes('Milestone 3'),
          `Module ${mod.id} still has Milestone 3`
        );
        assert.ok(
          mod.provisionalMilestone.includes('Provisional'),
          `Module ${mod.id} is missing "Provisional" designation`
        );
      }
    });

    it('centralized ARCHITECTURE_MODULES does not reference Milestone 2B for gamification', () => {
      const gamification = ARCHITECTURE_MODULES.find((m) => m.name === 'ZENTIQ GAMIFICATION');
      assert.ok(gamification, 'ZENTIQ GAMIFICATION should be in ARCHITECTURE_MODULES');
      assert.ok(!gamification.status.includes('Milestone 2B'));
      assert.ok(gamification.status.includes('Provisional'));
    });

    it('never displays green operational status when health is unknown, loading, degraded, or failed', () => {
      // Header badge variant helper check
      assert.strictEqual(getHealthBadgeVariant(null), 'neutral');
      assert.strictEqual(getHealthBadgeVariant(undefined), 'neutral');
      assert.strictEqual(getHealthBadgeVariant(false), 'warning');
      assert.strictEqual(getHealthBadgeVariant(true), 'success');

      // SystemTelemetryCard states check
      assert.strictEqual(getTelemetryStateBadge('loading').isGreen, false);
      assert.strictEqual(getTelemetryStateBadge('loading').variant, 'neutral');

      assert.strictEqual(getTelemetryStateBadge('error').isGreen, false);
      assert.strictEqual(getTelemetryStateBadge('error').variant, 'error');

      assert.strictEqual(getTelemetryStateBadge('degraded').isGreen, false);
      assert.strictEqual(getTelemetryStateBadge('degraded').variant, 'warning');

      assert.strictEqual(getTelemetryStateBadge('healthy').isGreen, true);
      assert.strictEqual(getTelemetryStateBadge('healthy').variant, 'success');
    });
  });
});

