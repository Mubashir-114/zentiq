import { Card, CardHeader, CardTitle, CardDescription, CardContent } from '../../../components/ui/Card';
import { Badge } from '../../../components/ui/Badge';
import { Clock, CheckCircle2, Info } from 'lucide-react';

interface AccountRecordCardProps {
  dateJoined: string;
}

export function AccountRecordCard({ dateJoined }: AccountRecordCardProps) {
  const formattedDate = new Date(dateJoined).toLocaleDateString(undefined, {
    year: 'numeric',
    month: 'long',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });

  return (
    <Card className="border-white/10">
      <CardHeader>
        <div className="flex items-center gap-2">
          <Clock className="w-5 h-5 text-[#22D3EE]" aria-hidden="true" />
          <CardTitle>Account Record</CardTitle>
        </div>
        <CardDescription>
          Verified identity milestones on ZENTIQ.
        </CardDescription>
      </CardHeader>

      <CardContent className="space-y-4">
        <div className="flex items-start gap-3 p-3 rounded-lg bg-white/5 border border-white/5">
          <CheckCircle2 className="w-4 h-4 text-[#34D399] shrink-0 mt-0.5" aria-hidden="true" />
          <div className="space-y-1 min-w-0">
            <div className="flex items-center gap-2">
              <span className="text-xs font-semibold text-[#F4F4F8]">
                Account created
              </span>
              <Badge variant="success" className="text-[10px] px-1.5 py-0">
                Verified
              </Badge>
            </div>
            <p className="text-[11px] text-[#9298AD] font-mono">
              {formattedDate}
            </p>
          </div>
        </div>

        <div className="flex items-start gap-2 p-2.5 rounded-lg bg-[#22D3EE]/5 border border-[#22D3EE]/15 text-[11px] text-[#9298AD] leading-relaxed">
          <Info className="w-3.5 h-3.5 text-[#22D3EE] shrink-0 mt-0.5" aria-hidden="true" />
          <span>
            Assessment, challenge, and module activities will appear here as new platform features are released.
          </span>
        </div>
      </CardContent>
    </Card>
  );
}

