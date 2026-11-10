import { HealthStatusCard } from './components/HealthStatusCard';
import { useHealth } from './context/HealthContext';
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from '../../components/ui/Card';
import { Terminal, Shield, CheckCircle2 } from 'lucide-react';

export function HealthView() {
  const { health: rawPayload } = useHealth();

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-3xl font-bold tracking-tight text-[#F4F4F8]">
          System &amp; Service Health
        </h1>
        <p className="mt-1 text-sm text-[#9298AD]">
          Live verification of Django REST Framework backend, database connectivity, and configured engine.
        </p>
      </div>

      <HealthStatusCard />

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {/* Endpoint Technical Specifications */}
        <Card>
          <CardHeader>
            <div className="flex items-center gap-2">
              <Shield className="w-5 h-5 text-[#8B5CF6]" />
              <CardTitle>Endpoint Contract</CardTitle>
            </div>
            <CardDescription>
              GET /api/v1/health/ design and error handling contract.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-3 text-xs text-[#9298AD] leading-relaxed">
            <p>
              The health check endpoint performs an active <code className="text-[#22D3EE] font-mono">SELECT 1;</code> query against the default database connection.
            </p>
            <ul className="space-y-2 pt-1">
              <li className="flex items-start gap-2">
                <CheckCircle2 className="w-4 h-4 text-[#34D399] shrink-0 mt-0.5" />
                <span>
                  <strong className="text-[#F4F4F8]">HTTP 200 OK:</strong> Returned when the Django application is healthy and the database responds successfully.
                </span>
              </li>
              <li className="flex items-start gap-2">
                <CheckCircle2 className="w-4 h-4 text-[#34D399] shrink-0 mt-0.5" />
                <span>
                  <strong className="text-[#F4F4F8]">HTTP 503 Service Unavailable:</strong> Returned when the database connection fails or drops.
                </span>
              </li>
              <li className="flex items-start gap-2">
                <CheckCircle2 className="w-4 h-4 text-[#34D399] shrink-0 mt-0.5" />
                <span>
                  <strong className="text-[#F4F4F8]">Zero Data Leakage:</strong> Internal stack traces, database credentials, hostnames, and ports are strictly omitted from the payload.
                </span>
              </li>
            </ul>
          </CardContent>
        </Card>

        {/* Live Payload Inspector */}
        <Card>
          <CardHeader>
            <div className="flex items-center gap-2">
              <Terminal className="w-5 h-5 text-[#22D3EE]" />
              <CardTitle>Live JSON Payload</CardTitle>
            </div>
            <CardDescription>
              Raw response returned by <code className="text-[#22D3EE] font-mono">/api/v1/health/</code>
            </CardDescription>
          </CardHeader>
          <CardContent>
            <pre className="rounded-lg bg-[#10121E] border border-white/5 p-4 font-mono text-xs text-[#22D3EE] overflow-x-auto leading-relaxed">
              {rawPayload ? JSON.stringify(rawPayload, null, 2) : '{\n  "status": "connecting...",\n  "message": "Awaiting response from backend"\n}'}
            </pre>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

