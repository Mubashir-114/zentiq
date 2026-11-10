import { useAuth } from '../../auth/context/AuthContext';
import { PlayerIdentityBanner } from '../components/PlayerIdentityBanner';
import { DashboardSectionHeader } from '../components/DashboardSectionHeader';
import { SkillDomainGrid } from '../components/SkillDomainGrid';
import { UpcomingModulesGrid } from '../components/UpcomingModulesGrid';
import { OnboardingPersonaCard } from '../components/OnboardingPersonaCard';
import { AccountRecordCard } from '../components/AccountRecordCard';
import { SystemTelemetryCard } from '../components/SystemTelemetryCard';
import { Badge } from '../../../components/ui/Badge';
import { Brain, Layers, Loader2 } from 'lucide-react';

export function DashboardView() {
  const { user, profile, isInitializing } = useAuth();

  if (isInitializing || !user || !profile) {
    return (
      <div className="min-h-[50vh] flex flex-col items-center justify-center p-8 space-y-3">
        <Loader2 className="w-8 h-8 text-[#8B5CF6] animate-spin" aria-hidden="true" />
        <p className="text-sm font-medium text-[#9298AD]">
          Loading ZENTIQ CORE telemetry...
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-8 animate-in fade-in duration-300">
      {/* Primary Identity & Welcome Banner */}
      <PlayerIdentityBanner user={user} profile={profile} />

      {/* Main Asymmetric Grid: 8 cols Primary, 4 cols Rail */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-8 items-start">
        {/* Primary Content (8 Columns) */}
        <div className="lg:col-span-8 space-y-8">
          {/* Section: Cognitive Skill Domains */}
          <section className="space-y-4" aria-labelledby="skill-domains-title">
            <DashboardSectionHeader
              title="Cognitive Skill Domains"
              description="Eight canonical intelligence vectors awaiting diagnostic calibration."
              icon={Brain}
              badge={<Badge variant="violet">8 Vectors</Badge>}
            />
            <SkillDomainGrid />
          </section>

          {/* Section: Planned Platform Capabilities */}
          <section className="space-y-4" aria-labelledby="planned-modules-title">
            <DashboardSectionHeader
              title="Platform Roadmap"
              description="Upcoming challenge engines and learning modules scheduled in the modular monolith."
              icon={Layers}
              badge={<Badge variant="neutral">Roadmap</Badge>}
            />
            <UpcomingModulesGrid />
          </section>
        </div>

        {/* Secondary Rail (4 Columns) */}
        <aside className="lg:col-span-4 space-y-6" aria-label="Player Onboarding & Telemetry">
          {/* Persona Card */}
          <OnboardingPersonaCard profile={profile} />

          {/* Account Record Card */}
          <AccountRecordCard dateJoined={user.date_joined} />

          {/* Live Service Telemetry Card */}
          <SystemTelemetryCard />
        </aside>
      </div>
    </div>
  );
}

