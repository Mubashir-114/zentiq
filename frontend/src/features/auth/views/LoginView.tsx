import { Link } from 'react-router-dom';
import { LoginForm } from '../components/LoginForm';
import { Card } from '../../../components/ui/Card';
import { Sparkles, Shield } from 'lucide-react';

export function LoginView() {
  return (
    <div className="min-h-[75vh] flex items-center justify-center py-10 px-4 sm:px-6 lg:px-8">
      <div className="w-full max-w-md space-y-6">
        {/* Header Branding */}
        <div className="text-center space-y-2">
          <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-white/5 border border-white/10 text-xs text-[#22D3EE] font-mono mb-2">
            <Sparkles className="w-3.5 h-3.5" />
            <span>AUTHENTICATION GATEWAY</span>
          </div>
          <h1 className="text-2xl sm:text-3xl font-bold tracking-tight text-[#F4F4F8]">
            Welcome Back, Player
          </h1>
          <p className="text-sm text-[#9298AD]">
            Authenticate your session to resume skill mastery and progression.
          </p>
        </div>

        {/* Form Card */}
        <Card glow className="p-6 sm:p-8 border-white/10 shadow-2xl">
          <LoginForm />

          <div className="mt-6 pt-5 border-t border-white/10 text-center text-xs text-[#9298AD]">
            New to ZENTIQ?{' '}
            <Link
              to="/register"
              className="font-semibold text-[#22D3EE] hover:text-[#8B5CF6] transition-colors"
            >
              Create your handle
            </Link>
          </div>
        </Card>

        {/* Security badge */}
        <div className="flex items-center justify-center gap-2 text-[11px] text-[#9298AD]/70">
          <Shield className="w-3.5 h-3.5 text-[#34D399]" />
          <span>Protected with HttpOnly session cookies &amp; CSRF protection</span>
        </div>
      </div>
    </div>
  );
}
