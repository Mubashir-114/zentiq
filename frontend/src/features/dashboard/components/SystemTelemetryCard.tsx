import { Link } from 'react-router-dom';
import { Card, CardHeader, CardTitle, CardDescription, CardContent, CardFooter } from '../../../components/ui/Card';
import { Badge } from '../../../components/ui/Badge';
import { Button } from '../../../components/ui/Button';
import { Server, ArrowRight, Activity } from 'lucide-react';
import { useHealth } from '../../health/context/HealthContext';

type TelemetryState = 'loading' | 'healthy' | 'degraded' | 'error';

function toTelemetryState(state: ReturnType<typeof useHealth>['state']): TelemetryState {
  switch (state) {
    case 'healthy':
      return 'healthy';
    case 'degraded':
      return 'degraded';
    case 'loading':
      return 'loading';
    default:
      return 'error';
  }
}

export function SystemTelemetryCard() {
  const { health, state: healthState } = useHealth();
  const state = toTelemetryState(healthState);

  const getStatusConfig = () => {
    switch (state) {
      case 'healthy':
        return {
          iconColor: 'text-[#34D399]',
          badgeVariant: 'success' as const,
          badgeLabel: 'Operational',
          subtitle: 'Live connectivity with ZENTIQ backend services.',
          body: 'Service health checks query live database responsiveness and API routing.',
        };
      case 'degraded':
        return {
          iconColor: 'text-[#F5C451]',
          badgeVariant: 'warning' as const,
          badgeLabel: 'Degraded',
          subtitle: 'Subsystem connectivity reporting degraded state.',
          body: 'One or more database or API subsystem services are reporting issues.',
        };
      case 'error':
        return {
          iconColor: 'text-[#FB7185]',
          badgeVariant: 'error' as const,
          badgeLabel: 'Offline',
          subtitle: 'Backend service currently unreachable.',
          body: 'Failed to connect to backend service. Live telemetry unavailable.',
        };
      case 'loading':
      default:
        return {
          iconColor: 'text-[#9298AD]',
          badgeVariant: 'neutral' as const,
          badgeLabel: 'Checking...',
          subtitle: 'Verifying backend service connectivity...',
          body: 'Service health checks query live database responsiveness and API routing.',
        };
    }
  };

  const config = getStatusConfig();

  return (
    <Card className="border-white/10 bg-[#1B1E2D]/60" data-testid="system-telemetry-card">
      <CardHeader>
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Server className={`w-5 h-5 ${config.iconColor}`} aria-hidden="true" />
            <CardTitle>System Telemetry</CardTitle>
          </div>
          <Badge variant={config.badgeVariant} dot data-testid="telemetry-badge">
            {config.badgeLabel}
          </Badge>
        </div>
        <CardDescription>{config.subtitle}</CardDescription>
      </CardHeader>

      <CardContent className="text-xs text-[#9298AD] space-y-2">
        <p>{config.body}</p>
        {health && (
          <p className="text-[11px] font-mono text-[#9298AD]/80">
            Engine: {health.services?.database_engine || 'unknown'} • Latency: normal
          </p>
        )}
      </CardContent>

      <CardFooter>
        <Link to="/health" className="w-full">
          <Button
            variant="outline"
            size="sm"
            className="w-full justify-between group text-xs"
            rightIcon={
              <ArrowRight className="w-3.5 h-3.5 text-[#22D3EE] transition-transform group-hover:translate-x-1" />
            }
          >
            <span className="flex items-center gap-1.5">
              <Activity className="w-3.5 h-3.5 text-[#34D399]" />
              View Live Health Monitor
            </span>
          </Button>
        </Link>
      </CardFooter>
    </Card>
  );
}
