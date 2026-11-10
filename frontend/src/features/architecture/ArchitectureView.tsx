import { Card, CardHeader, CardTitle, CardDescription, CardContent } from '../../components/ui/Card';
import { Badge } from '../../components/ui/Badge';
import { Layers, ShieldCheck, Cpu, Smartphone, Database, Lock } from 'lucide-react';
import { ARCHITECTURE_MODULES } from '../dashboard/constants/upcomingModules';

export function ArchitectureView() {

  const architecturalRules = [
    {
      title: 'Auditable XP Ledger',
      description: 'XP, scores, ranks, and badges must never be directly incremented on a user record. Every point change requires an immutable ledger entry calculated strictly on the backend.',
      icon: Database,
    },
    {
      title: 'Zero Client Trust',
      description: 'Client applications (React web and future Flutter mobile) are untrusted runtimes. Answer submissions and completion tokens are validated entirely on the server.',
      icon: Lock,
    },
    {
      title: 'Assessment Versioning',
      description: 'Questions and assessment schemas must be immutably versioned so historical test results remain historically valid when questions are modified or updated.',
      icon: ShieldCheck,
    },
    {
      title: 'Single Backend for Web & Mobile',
      description: 'The upcoming Flutter mobile application will consume the exact same /api/v1/ endpoints as the React frontend, guaranteeing zero duplicated business logic.',
      icon: Smartphone,
    },
  ];

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-3xl font-bold tracking-tight text-[#F4F4F8]">
          Architecture Specifications
        </h1>
        <p className="mt-1 text-sm text-[#9298AD]">
          Technical foundation, module boundaries, and future domain evolution for ZENTIQ.
        </p>
      </div>

      {/* Modular Monolith Overview */}
      <Card>
        <CardHeader>
          <div className="flex items-center gap-2">
            <Layers className="w-5 h-5 text-[#8B5CF6]" />
            <CardTitle>Modular Monolith Architecture</CardTitle>
          </div>
          <CardDescription>
            Why a modular monolith was chosen over premature microservices.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4 text-sm text-[#9298AD] leading-relaxed">
          <p>
            ZENTIQ is architected as a <strong className="text-[#F4F4F8]">modular monolith</strong> using Django 6.0 and Django REST Framework. Each domain application encapsulates its own models, services, serializers, and permission boundaries while sharing database transactions and configuration.
          </p>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4 pt-2">
            <div className="rounded-lg border border-white/5 bg-[#10121E]/60 p-3.5 space-y-1">
              <span className="text-xs font-semibold text-[#22D3EE] block">Strict Boundaries</span>
              <span className="text-xs text-[#9298AD]">
                Inter-module communication passes through explicit service interfaces, preventing tight database coupling.
              </span>
            </div>
            <div className="rounded-lg border border-white/5 bg-[#10121E]/60 p-3.5 space-y-1">
              <span className="text-xs font-semibold text-[#8B5CF6] block">Operational Simplicity</span>
              <span className="text-xs text-[#9298AD]">
                Zero overhead from distributed consensus, network hops between microservices, or complex service meshes.
              </span>
            </div>
            <div className="rounded-lg border border-white/5 bg-[#10121E]/60 p-3.5 space-y-1">
              <span className="text-xs font-semibold text-[#34D399] block">Evolution Ready</span>
              <span className="text-xs text-[#9298AD]">
                High-throughput modules (such as ZENTIQ DUEL) can be decoupled into standalone microservices in the future without domain refactoring.
              </span>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Domain Modules Matrix */}
      <Card>
        <CardHeader>
          <div className="flex items-center gap-2">
            <Cpu className="w-5 h-5 text-[#22D3EE]" />
            <CardTitle>Planned Domain Boundaries</CardTitle>
          </div>
          <CardDescription>
            Lifecycle breakdown of core and upcoming product modules.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            {ARCHITECTURE_MODULES.map((mod) => (
              <div
                key={mod.name}
                className="flex items-center justify-between p-3.5 rounded-lg border border-white/5 bg-[#10121E]/50"
              >
                <div className="space-y-0.5 pr-2">
                  <span className="text-xs font-semibold text-[#F4F4F8] block">{mod.name}</span>
                  <span className="text-[11px] text-[#9298AD]">{mod.desc}</span>
                </div>
                <Badge
                  variant={mod.status.includes('Implemented') ? 'success' : 'neutral'}
                  className="shrink-0 text-[10px]"
                >
                  {mod.status}
                </Badge>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>

      {/* Critical Future Architectural Constraints */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        {architecturalRules.map((rule) => {
          const Icon = rule.icon;
          return (
            <Card key={rule.title}>
              <CardHeader className="pb-2">
                <div className="flex items-center gap-2">
                  <Icon className="w-4 h-4 text-[#F5C451]" />
                  <CardTitle className="text-sm font-semibold">{rule.title}</CardTitle>
                </div>
              </CardHeader>
              <CardContent>
                <p className="text-xs text-[#9298AD] leading-relaxed">
                  {rule.description}
                </p>
              </CardContent>
            </Card>
          );
        })}
      </div>
    </div>
  );
}

