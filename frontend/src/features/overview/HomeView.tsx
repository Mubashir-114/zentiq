import { useState } from 'react';
import { HealthStatusCard } from '../health/components/HealthStatusCard';
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from '../../components/ui/Card';
import { Button } from '../../components/ui/Button';
import { Badge } from '../../components/ui/Badge';
import { Shield, Sparkles, Layers, CheckCircle2 } from 'lucide-react';

export function HomeView() {
  const [btnLoading, setBtnLoading] = useState(false);

  const simulateAction = () => {
    setBtnLoading(true);
    setTimeout(() => setBtnLoading(false), 1200);
  };

  return (
    <div className="space-y-8">
      {/* Hero Section */}
      <div className="relative overflow-hidden rounded-2xl border border-white/10 bg-gradient-to-b from-[#1B1E2D] to-[#10121E] p-6 sm:p-10">
        <div className="absolute top-0 right-0 -mr-16 -mt-16 w-64 h-64 rounded-full bg-[#8B5CF6]/10 blur-3xl pointer-events-none" />
        <div className="absolute bottom-0 right-1/4 -mb-16 w-64 h-64 rounded-full bg-[#22D3EE]/10 blur-3xl pointer-events-none" />

        <div className="relative max-w-2xl space-y-4">
          <div className="flex items-center gap-2">
            <Badge variant="violet" dot>Milestone 1 Active</Badge>
            <span className="text-xs text-[#9298AD] font-mono">Architecture &amp; Foundation</span>
          </div>

          <h1 className="text-3xl sm:text-4xl lg:text-5xl font-bold tracking-tight text-[#F4F4F8]">
            Level Up Your Mind.
          </h1>

          <p className="text-base sm:text-lg text-[#9298AD] leading-relaxed">
            Gamified skill-development ecosystem engineered for cognitive mastery, technical acumen,
            and career progression.
          </p>

          <div className="flex flex-wrap items-center gap-3 pt-2">
            <Badge variant="cyan">Learn</Badge>
            <Badge variant="violet">Challenge</Badge>
            <Badge variant="gold">Evolve</Badge>
          </div>
        </div>
      </div>

      {/* Backend & Database Health Live Integration */}
      <HealthStatusCard />

      {/* Confirmed Technical Foundation Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        <Card>
          <CardHeader>
            <div className="flex items-center gap-2">
              <Layers className="w-5 h-5 text-[#8B5CF6]" />
              <CardTitle>Frontend Architecture</CardTitle>
            </div>
            <CardDescription>
              Modern, responsive, accessible React foundation with zero-runtime utility styling.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            <ul className="space-y-2 text-sm text-[#9298AD]">
              <li className="flex items-center gap-2">
                <CheckCircle2 className="w-4 h-4 text-[#34D399]" />
                <span className="text-[#F4F4F8]">React 19 &amp; Vite:</span> Ultra-fast development and optimized production builds.
              </li>
              <li className="flex items-center gap-2">
                <CheckCircle2 className="w-4 h-4 text-[#34D399]" />
                <span className="text-[#F4F4F8]">Tailwind CSS v4:</span> First-party @tailwindcss/vite integration and CSS variables.
              </li>
              <li className="flex items-center gap-2">
                <CheckCircle2 className="w-4 h-4 text-[#34D399]" />
                <span className="text-[#F4F4F8]">TypeScript Strict:</span> End-to-end type safety and clean interfaces.
              </li>
              <li className="flex items-center gap-2">
                <CheckCircle2 className="w-4 h-4 text-[#34D399]" />
                <span className="text-[#F4F4F8]">Centralized API Client:</span> Resilient fetch layer with CSRF extraction and error normalization.
              </li>
            </ul>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <div className="flex items-center gap-2">
              <Shield className="w-5 h-5 text-[#22D3EE]" />
              <CardTitle>Backend &amp; Security</CardTitle>
            </div>
            <CardDescription>
              Modular monolithic architecture with Django 6 and Django REST Framework.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            <ul className="space-y-2 text-sm text-[#9298AD]">
              <li className="flex items-center gap-2">
                <CheckCircle2 className="w-4 h-4 text-[#34D399]" />
                <span className="text-[#F4F4F8]">Custom User Model:</span> Email-centric authentication established before initial migrations.
              </li>
              <li className="flex items-center gap-2">
                <CheckCircle2 className="w-4 h-4 text-[#34D399]" />
                <span className="text-[#F4F4F8]">MySQL 8.4 Default:</span> Environment-configured relational store with PyMySQL bridge.
              </li>
              <li className="flex items-center gap-2">
                <CheckCircle2 className="w-4 h-4 text-[#34D399]" />
                <span className="text-[#F4F4F8]">Versioned REST API:</span> Base endpoint path <code className="text-[#22D3EE] font-mono">/api/v1/</code>.
              </li>
              <li className="flex items-center gap-2">
                <CheckCircle2 className="w-4 h-4 text-[#34D399]" />
                <span className="text-[#F4F4F8]">OpenAPI 3 / Swagger:</span> Automatic schema generation via drf-spectacular.
              </li>
            </ul>
          </CardContent>
        </Card>
      </div>

      {/* Design System Primitives Showcase */}
      <Card>
        <CardHeader>
          <div className="flex items-center gap-2">
            <Sparkles className="w-5 h-5 text-[#F5C451]" />
            <CardTitle>ZENTIQ Design System Foundation</CardTitle>
          </div>
          <CardDescription>
            High-contrast dark gaming aesthetic with refined visual hierarchy, semantic tokens, and accessible states.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-6">
          {/* Color Tokens */}
          <div>
            <span className="text-xs font-semibold text-[#9298AD] uppercase tracking-wider block mb-3">
              Color Tokens
            </span>
            <div className="grid grid-cols-2 sm:grid-cols-5 gap-3">
              <div className="p-3 rounded-lg bg-[#8B5CF6]/15 border border-[#8B5CF6]/30 text-center">
                <div className="w-4 h-4 rounded-full bg-[#8B5CF6] mx-auto mb-1.5" />
                <span className="text-xs font-semibold text-[#F4F4F8] block">Electric Violet</span>
                <span className="text-[10px] text-[#9298AD] font-mono">#8B5CF6</span>
              </div>
              <div className="p-3 rounded-lg bg-[#22D3EE]/15 border border-[#22D3EE]/30 text-center">
                <div className="w-4 h-4 rounded-full bg-[#22D3EE] mx-auto mb-1.5" />
                <span className="text-xs font-semibold text-[#F4F4F8] block">Neon Cyan</span>
                <span className="text-[10px] text-[#9298AD] font-mono">#22D3EE</span>
              </div>
              <div className="p-3 rounded-lg bg-[#1B1E2D] border border-white/10 text-center">
                <div className="w-4 h-4 rounded-full bg-[#1B1E2D] border border-white/20 mx-auto mb-1.5" />
                <span className="text-xs font-semibold text-[#F4F4F8] block">Surface</span>
                <span className="text-[10px] text-[#9298AD] font-mono">#1B1E2D</span>
              </div>
              <div className="p-3 rounded-lg bg-[#34D399]/15 border border-[#34D399]/30 text-center">
                <div className="w-4 h-4 rounded-full bg-[#34D399] mx-auto mb-1.5" />
                <span className="text-xs font-semibold text-[#F4F4F8] block">Success</span>
                <span className="text-[10px] text-[#9298AD] font-mono">#34D399</span>
              </div>
              <div className="p-3 rounded-lg bg-[#F5C451]/15 border border-[#F5C451]/30 text-center">
                <div className="w-4 h-4 rounded-full bg-[#F5C451] mx-auto mb-1.5" />
                <span className="text-xs font-semibold text-[#F4F4F8] block">Reward Gold</span>
                <span className="text-[10px] text-[#9298AD] font-mono">#F5C451</span>
              </div>
            </div>
          </div>

          {/* Interactive Component States */}
          <div>
            <span className="text-xs font-semibold text-[#9298AD] uppercase tracking-wider block mb-3">
              UI Primitives &amp; Interaction States
            </span>
            <div className="flex flex-wrap items-center gap-3">
              <Button
                variant="primary"
                onClick={simulateAction}
                isLoading={btnLoading}
              >
                Primary Violet
              </Button>
              <Button variant="cyan" onClick={simulateAction}>
                Cyan Action
              </Button>
              <Button variant="secondary">Secondary</Button>
              <Button variant="outline">Outline</Button>
              <Button variant="ghost">Ghost</Button>
              <Button disabled variant="primary">Disabled</Button>
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
