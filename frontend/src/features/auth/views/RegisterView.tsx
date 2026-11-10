import { Link } from 'react-router-dom';
import { RegisterForm } from '../components/RegisterForm';
import { Card } from '../../../components/ui/Card';
import { Terminal, Shield } from 'lucide-react';

export function RegisterView() {
  return (
    <div className="min-h-[75vh] flex items-center justify-center py-10 px-4 sm:px-6 lg:px-8">
      <div className="w-full max-w-md space-y-6">
        {/* Header Branding */}
        <div className="text-center space-y-2">
          <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-white/5 border border-white/10 text-xs text-[#8B5CF6] font-mono mb-2">
            <Terminal className="w-3.5 h-3.5" />
            <span>PLAYER ENLISTMENT</span>
          </div>
          <h1 className="text-2xl sm:text-3xl font-bold tracking-tight text-[#F4F4F8]">
            Claim Your ZENTIQ Identity
          </h1>
          <p className="text-sm text-[#9298AD]">
            Choose your permanent handle and commence your cognitive development journey.
          </p>
        </div>

        {/* Form Card */}
        <Card glow className="p-6 sm:p-8 border-white/10 shadow-2xl">
          <RegisterForm />

          <div className="mt-6 pt-5 border-t border-white/10 text-center text-xs text-[#9298AD]">
            Already have an active persona?{' '}
            <Link
              to="/login"
              className="font-semibold text-[#8B5CF6] hover:text-[#22D3EE] transition-colors"
            >
              Sign In
            </Link>
          </div>
        </Card>

        {/* Security badge */}
        <div className="flex items-center justify-center gap-2 text-[11px] text-[#9298AD]/70">
          <Shield className="w-3.5 h-3.5 text-[#34D399]" />
          <span>Zero-tracking, encrypted passwords &amp; secure session validation</span>
        </div>
      </div>
    </div>
  );
}
