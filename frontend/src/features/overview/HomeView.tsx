import { useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { ArrowRight, CheckCircle2, Layers, Shield, Sparkles } from 'lucide-react';
import { HealthStatusCard } from '../health/components/HealthStatusCard';
import {
  Card,
  CardHeader,
  CardTitle,
  CardDescription,
  CardContent,
} from '../../components/ui/Card';
import { Button } from '../../components/ui/Button';
import { Badge } from '../../components/ui/Badge';
import { HeroAmbience, Spotlight } from './components/HeroAmbience';
import { EcosystemCore } from './components/EcosystemCore';
import { EcosystemFlow } from './components/EcosystemFlow';
import { LandingEnvironment } from './components/LandingEnvironment';
import { Reveal } from './components/Reveal';
import { usePointerParallax } from './hooks/usePointerParallax';
import { useAmbientPause } from './hooks/useAmbientPause';
import { useChapterAmbience } from './hooks/useChapterAmbience';

export function HomeView() {
  const [btnLoading, setBtnLoading] = useState(false);
  const navigate = useNavigate();
  const heroRef = useRef<HTMLElement>(null);
  const pageRef = useRef<HTMLDivElement>(null);

  usePointerParallax(heroRef);
  useAmbientPause(heroRef);
  useAmbientPause(pageRef);
  useChapterAmbience(pageRef);

  const simulateAction = () => {
    setBtnLoading(true);
    setTimeout(() => setBtnLoading(false), 1200);
  };

  return (
    <div
      ref={pageRef}
      data-ambient="active"
      data-chapter="hero"
      className="zq-page relative isolate space-y-8"
    >
      <LandingEnvironment />
      <div className="zq-progress" aria-hidden="true" />

      {/* Hero — living digital environment */}
      <section
        ref={heroRef}
        data-chapter="hero"
        data-ambient="active"
        aria-labelledby="hero-title"
        className="zq-hero relative overflow-hidden rounded-panel border border-hairline"
      >
        <HeroAmbience />

        <div className="relative z-10 grid gap-10 p-6 sm:p-10 lg:min-h-[540px] lg:grid-cols-[minmax(0,1fr)_minmax(0,400px)] lg:items-center lg:gap-8 lg:p-12">
          <div className="max-w-2xl space-y-5">
            <div
              className="zq-hero-enter flex flex-wrap items-center gap-2.5"
              style={{ animationDelay: '40ms' }}
            >
              <Badge variant="volt" dot>
                Milestone 1 Active
              </Badge>
              <span className="font-mono text-[10px] uppercase tracking-[0.2em] text-ink-faint">
                Architecture &amp; Foundation
              </span>
            </div>

            <h1
              id="hero-title"
              className="zq-hero-enter text-display font-bold text-ink"
              style={{ animationDelay: '110ms' }}
            >
              Level Up <span className="zq-hero-accent">Your Mind.</span>
            </h1>

            <p
              className="zq-hero-enter max-w-xl text-base leading-relaxed text-ink-muted sm:text-lg"
              style={{ animationDelay: '180ms' }}
            >
              Gamified skill-development ecosystem engineered for cognitive mastery, technical
              acumen, and career progression.
            </p>

            <div
              className="zq-hero-enter flex flex-wrap items-center gap-2"
              style={{ animationDelay: '250ms' }}
            >
              <Badge variant="cyan">Learn</Badge>
              <Badge variant="violet">Challenge</Badge>
              <Badge variant="gold">Evolve</Badge>
            </div>

            <div
              className="zq-hero-enter flex flex-wrap items-center gap-3 pt-1"
              style={{ animationDelay: '320ms' }}
            >
              <Button
                size="lg"
                className="zq-cta"
                onClick={() => navigate('/register')}
                rightIcon={<ArrowRight className="h-4 w-4" aria-hidden="true" />}
              >
                Enter ZENTIQ
              </Button>
              <Button size="lg" variant="outline" onClick={() => navigate('/health')}>
                System status
              </Button>
            </div>

            <p
              className="zq-hero-enter font-mono text-[10px] uppercase tracking-[0.22em] text-ink-faint"
              style={{ animationDelay: '390ms' }}
            >
              Signal online · Server-authoritative progression
            </p>
          </div>

          <div
            className="zq-hero-enter flex justify-center lg:justify-end"
            style={{ animationDelay: '220ms' }}
          >
            <EcosystemCore />
          </div>
        </div>
      </section>

      {/* Learning protocol — LEARN → CHALLENGE → EVOLVE */}
      <Reveal delay={40} className="zq-chapter-reveal">
        <section
          data-chapter="protocol"
          aria-labelledby="protocol-title"
          className="zq-protocol relative overflow-hidden rounded-card border border-hairline p-6 sm:p-8"
        >
          <div className="zq-protocol__glow" aria-hidden="true" />
          <div className="relative max-w-2xl space-y-2">
            <span className="zq-eyebrow">Learning Protocol</span>
            <h2 id="protocol-title" className="text-title font-semibold text-ink">
              Learn. Challenge. Evolve.
            </h2>
            <p className="text-sm leading-relaxed text-ink-muted">
              Three connected stages turn study into measured progress. Each stage feeds the next
              along a single signal path.
            </p>
          </div>
          <div className="relative">
            <EcosystemFlow />
          </div>
        </section>
      </Reveal>

      {/* Backend & Database Health Live Integration */}
      <Reveal delay={60} className="zq-health-reveal">
        <div className="zq-health" data-chapter="health">
          <HealthStatusCard />
        </div>
      </Reveal>

      {/* Confirmed Technical Foundation Grid */}
      <div className="zq-arch-grid relative" data-chapter="architecture">
        <span className="zq-arch-signal" aria-hidden="true" />

        <div className="grid grid-cols-1 gap-6 md:grid-cols-2">
          <Reveal className="h-full" from="left">
            <Spotlight className="zq-tilt h-full">
              <Card glow className="zq-arch-card zq-arch-card--uv h-full">
                <CardHeader>
                  <div className="flex items-center gap-2">
                    <Layers className="h-5 w-5 text-ultraviolet" aria-hidden="true" />
                    <CardTitle>Frontend Architecture</CardTitle>
                  </div>
                  <CardDescription>
                    Modern, responsive, accessible React foundation with zero-runtime utility
                    styling.
                  </CardDescription>
                </CardHeader>
                <CardContent className="space-y-3">
                  <ul className="space-y-2 text-sm text-ink-muted">
                    <li className="flex items-start gap-2">
                      <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-success" aria-hidden="true" />
                      <span className="text-ink">React 19 &amp; Vite:</span> Ultra-fast development and
                      optimized production builds.
                    </li>
                    <li className="flex items-start gap-2">
                      <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-success" aria-hidden="true" />
                      <span className="text-ink">Tailwind CSS v4:</span> First-party
                      @tailwindcss/vite integration and CSS variables.
                    </li>
                    <li className="flex items-start gap-2">
                      <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-success" aria-hidden="true" />
                      <span className="text-ink">TypeScript Strict:</span> End-to-end type safety and
                      clean interfaces.
                    </li>
                    <li className="flex items-start gap-2">
                      <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-success" aria-hidden="true" />
                      <span className="text-ink">Centralized API Client:</span> Resilient fetch layer
                      with CSRF extraction and error normalization.
                    </li>
                  </ul>
                </CardContent>
              </Card>
            </Spotlight>
          </Reveal>

          <Reveal delay={90} className="h-full" from="right">
            <Spotlight className="zq-tilt h-full">
              <Card glow className="zq-arch-card zq-arch-card--cyan h-full">
                <CardHeader>
                  <div className="flex items-center gap-2">
                    <Shield className="h-5 w-5 text-cyan" aria-hidden="true" />
                    <CardTitle>Backend &amp; Security</CardTitle>
                  </div>
                  <CardDescription>
                    Modular monolithic architecture with Django 6 and Django REST Framework.
                  </CardDescription>
                </CardHeader>
                <CardContent className="space-y-3">
                  <ul className="space-y-2 text-sm text-ink-muted">
                    <li className="flex items-start gap-2">
                      <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-success" aria-hidden="true" />
                      <span className="text-ink">Custom User Model:</span> Email-centric authentication
                      established before initial migrations.
                    </li>
                    <li className="flex items-start gap-2">
                      <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-success" aria-hidden="true" />
                      <span className="text-ink">MySQL 8.4 Default:</span> Environment-configured
                      relational store with PyMySQL bridge.
                    </li>
                    <li className="flex items-start gap-2">
                      <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-success" aria-hidden="true" />
                      <span className="text-ink">Versioned REST API:</span> Base endpoint path{' '}
                      <code className="font-mono text-cyan">/api/v1/</code>.
                    </li>
                    <li className="flex items-start gap-2">
                      <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-success" aria-hidden="true" />
                      <span className="text-ink">OpenAPI 3 / Swagger:</span> Automatic schema generation
                      via drf-spectacular.
                    </li>
                  </ul>
                </CardContent>
              </Card>
            </Spotlight>
          </Reveal>
        </div>
      </div>

      {/* Design System Primitives Showcase */}
      <Reveal delay={120} className="zq-chapter-reveal">
        <Card
          featured
          data-chapter="system"
          className="zq-chapter-card"
        >
          <CardHeader>
            <div className="flex items-center gap-2">
              <Sparkles className="h-5 w-5 text-gold" aria-hidden="true" />
              <CardTitle>ZENTIQ Design System Foundation</CardTitle>
            </div>
            <CardDescription>
              High-contrast dark gaming aesthetic with refined visual hierarchy, semantic tokens,
              and accessible states.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-6">
            {/* Color Tokens */}
            <div>
              <span className="mb-3 block text-xs font-semibold uppercase tracking-wider text-ink-muted">
                Color Tokens
              </span>
              <div className="zq-swatches grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
                <div className="rounded-lg border border-volt/30 bg-volt/10 p-3 text-center">
                  <div className="mx-auto mb-1.5 h-4 w-4 rounded-full bg-volt" />
                  <span className="block text-xs font-semibold text-ink">Volt</span>
                  <span className="font-mono text-[10px] text-ink-muted">#C8FF3D</span>
                </div>
                <div className="rounded-lg border border-ultraviolet/30 bg-ultraviolet/15 p-3 text-center">
                  <div className="mx-auto mb-1.5 h-4 w-4 rounded-full bg-ultraviolet" />
                  <span className="block text-xs font-semibold text-ink">Ultraviolet</span>
                  <span className="font-mono text-[10px] text-ink-muted">#8B5CF6</span>
                </div>
                <div className="rounded-lg border border-cyan/30 bg-cyan/15 p-3 text-center">
                  <div className="mx-auto mb-1.5 h-4 w-4 rounded-full bg-cyan" />
                  <span className="block text-xs font-semibold text-ink">Cyan</span>
                  <span className="font-mono text-[10px] text-ink-muted">#22D3EE</span>
                </div>
                <div className="rounded-lg border border-hairline bg-panel p-3 text-center">
                  <div className="mx-auto mb-1.5 h-4 w-4 rounded-full border border-white/20 bg-panel" />
                  <span className="block text-xs font-semibold text-ink">Panel</span>
                  <span className="font-mono text-[10px] text-ink-muted">#161A25</span>
                </div>
                <div className="rounded-lg border border-success/30 bg-success/15 p-3 text-center">
                  <div className="mx-auto mb-1.5 h-4 w-4 rounded-full bg-success" />
                  <span className="block text-xs font-semibold text-ink">Success</span>
                  <span className="font-mono text-[10px] text-ink-muted">#4ADE80</span>
                </div>
                <div className="rounded-lg border border-gold/30 bg-gold/15 p-3 text-center">
                  <div className="mx-auto mb-1.5 h-4 w-4 rounded-full bg-gold" />
                  <span className="block text-xs font-semibold text-ink">Reward Gold</span>
                  <span className="font-mono text-[10px] text-ink-muted">#F5C451</span>
                </div>
              </div>
            </div>

            {/* Interactive Component States */}
            <div>
              <span className="mb-3 block text-xs font-semibold uppercase tracking-wider text-ink-muted">
                UI Primitives &amp; Interaction States
              </span>
              <div className="zq-primitives flex flex-wrap items-center gap-3">
                <Button variant="primary" onClick={simulateAction} isLoading={btnLoading}>
                  Primary Volt
                </Button>
                <Button variant="cyan" onClick={simulateAction}>
                  Cyan Action
                </Button>
                <Button variant="secondary">Secondary</Button>
                <Button variant="outline">Outline</Button>
                <Button variant="ghost">Ghost</Button>
                <Button disabled variant="primary">
                  Disabled
                </Button>
              </div>
            </div>
          </CardContent>
        </Card>
      </Reveal>
    </div>
  );
}
