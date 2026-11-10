import { useHealth } from '../context/HealthContext';
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from '../../../components/ui/Card';
import { Badge } from '../../../components/ui/Badge';
import { Button } from '../../../components/ui/Button';
import { Database, Server, Clock, RefreshCw, AlertCircle, CheckCircle2, Cpu } from 'lucide-react';

export function HealthStatusCard() {
  const { health, state, error, isRefreshing, refresh } = useHealth();
  const loading = state === 'loading';

  const isApiOperational = Boolean(health && health.services?.api === 'operational');
  const isDbOperational = Boolean(
    health && (health.services?.database_connection === 'operational' || health.services?.database === 'operational')
  );
  const detectedEngine = health?.services?.database_engine?.toLowerCase() || '';

  const getEngineDisplay = () => {
    if (!health) return { label: 'Unknown', variant: 'neutral' as const, badge: 'UNAVAILABLE' };
    if (detectedEngine === 'mysql') {
      return { label: 'MySQL 8.4', variant: 'cyan' as const, badge: 'DEFAULT ENGINE' };
    }
    if (detectedEngine === 'sqlite') {
      return { label: 'SQLite', variant: 'warning' as const, badge: 'DEV/TEST FALLBACK' };
    }
    if (detectedEngine === 'postgresql') {
      return { label: 'PostgreSQL', variant: 'violet' as const, badge: 'CONFIGURED' };
    }
    return { label: detectedEngine ? detectedEngine.toUpperCase() : 'Custom Engine', variant: 'neutral' as const, badge: 'CONFIGURED' };
  };

  const engineInfo = getEngineDisplay();

  return (
    <Card glow className="overflow-hidden">
      <CardHeader className="flex flex-row items-start justify-between pb-4">
        <div>
          <div className="flex items-center gap-2.5">
            <CardTitle>System &amp; Database Health</CardTitle>
            {loading && !health && !error && (
              <Badge variant="neutral" dot>
                CHECKING
              </Badge>
            )}
            {health && (
              <Badge
                variant={
                  health.status === 'healthy'
                    ? 'success'
                    : health.status === 'degraded'
                    ? 'warning'
                    : 'error'
                }
                dot
              >
                {health.status.toUpperCase()}
              </Badge>
            )}
            {error && (
              <Badge variant="error" dot>
                DISCONNECTED
              </Badge>
            )}
          </div>
          <CardDescription className="mt-1">
            Real-time verification of backend API availability, database connectivity, and configured engine.
          </CardDescription>
        </div>

        <Button
          variant="outline"
          size="sm"
          onClick={() => void refresh()}
          isLoading={isRefreshing}
          leftIcon={<RefreshCw className="w-3.5 h-3.5" />}
        >
          Check Now
        </Button>
      </CardHeader>

      <CardContent className="space-y-4">
        {error ? (
          <div className="rounded-lg border border-[#FB7185]/20 bg-[#FB7185]/10 p-4 text-sm text-[#FB7185] flex items-start gap-3">
            <AlertCircle className="w-5 h-5 shrink-0 mt-0.5" />
            <div>
              <p className="font-semibold">Backend Unreachable</p>
              <p className="text-xs text-[#FB7185]/80 mt-1">{error}</p>
              <p className="text-xs text-[#9298AD] mt-2">
                Make sure the Django backend is running at <code className="text-[#22D3EE] font-mono">http://127.0.0.1:8000</code>.
              </p>
            </div>
          </div>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
            {/* 1. Backend API Status */}
            <div className="rounded-lg border border-white/5 bg-[#10121E]/70 p-3.5 flex flex-col justify-between">
              <div className="flex items-center justify-between text-xs text-[#9298AD]">
                <span className="flex items-center gap-1.5 font-medium">
                  <Server className="w-3.5 h-3.5 text-[#8B5CF6]" />
                  Backend API
                </span>
                <span className="font-mono text-[11px] text-[#22D3EE]">/api/v1/</span>
              </div>
              <div className="mt-3 flex items-center justify-between">
                <span className="text-sm font-semibold text-[#F4F4F8]">
                  {loading ? 'Checking...' : isApiOperational ? 'Operational' : 'Unavailable'}
                </span>
                {!loading && (
                  isApiOperational ? (
                    <CheckCircle2 className="w-4 h-4 text-[#34D399]" />
                  ) : (
                    <AlertCircle className="w-4 h-4 text-[#FB7185]" />
                  )
                )}
              </div>
            </div>

            {/* 2. Database Connection */}
            <div className="rounded-lg border border-white/5 bg-[#10121E]/70 p-3.5 flex flex-col justify-between">
              <div className="flex items-center justify-between text-xs text-[#9298AD]">
                <span className="flex items-center gap-1.5 font-medium">
                  <Database className="w-3.5 h-3.5 text-[#22D3EE]" />
                  Database Connection
                </span>
                <span className="font-mono text-[11px] text-[#9298AD]">SELECT 1</span>
              </div>
              <div className="mt-3 flex items-center justify-between">
                <span className="text-sm font-semibold text-[#F4F4F8]">
                  {loading ? 'Checking...' : isDbOperational ? 'Operational' : 'Unavailable'}
                </span>
                {!loading && (
                  isDbOperational ? (
                    <CheckCircle2 className="w-4 h-4 text-[#34D399]" />
                  ) : (
                    <AlertCircle className="w-4 h-4 text-[#FB7185]" />
                  )
                )}
              </div>
            </div>

            {/* 3. Database Engine */}
            <div className="rounded-lg border border-white/5 bg-[#10121E]/70 p-3.5 flex flex-col justify-between">
              <div className="flex items-center justify-between text-xs text-[#9298AD]">
                <span className="flex items-center gap-1.5 font-medium">
                  <Cpu className="w-3.5 h-3.5 text-[#34D399]" />
                  Database Engine
                </span>
                <Badge variant={engineInfo.variant} className="text-[9px] py-0 px-1.5 font-mono">
                  {engineInfo.badge}
                </Badge>
              </div>
              <div className="mt-3 flex items-center justify-between">
                <span className="text-sm font-semibold text-[#F4F4F8]">
                  {loading ? 'Detecting...' : engineInfo.label}
                </span>
                {!loading && health && (
                  <span className="text-[10px] text-[#9298AD] font-mono">
                    {detectedEngine}
                  </span>
                )}
              </div>
            </div>

            {/* 4. API Version & Server Clock */}
            <div className="rounded-lg border border-white/5 bg-[#10121E]/70 p-3.5 flex flex-col justify-between">
              <div className="flex items-center justify-between text-xs text-[#9298AD]">
                <span className="flex items-center gap-1.5 font-medium">
                  <Clock className="w-3.5 h-3.5 text-[#F5C451]" />
                  Server Clock / Version
                </span>
                <span className="font-mono text-[11px] text-[#A78BFA]">
                  {health ? `v${health.version}` : 'v1.0.0'}
                </span>
              </div>
              <div className="mt-3 flex items-center justify-between">
                <span className="text-xs font-mono text-[#9298AD] truncate">
                  {loading ? 'Fetching...' : health ? new Date(health.timestamp).toLocaleTimeString() : 'N/A'}
                </span>
                <Badge variant="neutral" className="text-[10px] py-0">SYNCED</Badge>
              </div>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
