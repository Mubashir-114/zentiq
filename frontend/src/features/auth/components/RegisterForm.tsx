import { useState, type FormEvent } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { ApiClientError } from '../../../lib/api-client';
import { Mail, AtSign, Lock, Eye, EyeOff, AlertCircle, Loader2 } from 'lucide-react';
import { Button } from '../../../components/ui/Button';

export function RegisterForm() {
  const { register, isLoading } = useAuth();
  const navigate = useNavigate();

  const [email, setEmail] = useState('');
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);

  const [fieldErrors, setFieldErrors] = useState<Record<string, string[]>>({});
  const [generalError, setGeneralError] = useState<string | null>(null);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setGeneralError(null);
    setFieldErrors({});

    const trimmedEmail = email.trim();
    const trimmedUsername = username.trim().toLowerCase();

    // Client-side quick validations
    const errors: Record<string, string[]> = {};
    if (!trimmedEmail) {
      errors.email = ['Email address is required.'];
    }
    if (!trimmedUsername) {
      errors.username = ['Public handle is required.'];
    } else if (!/^[a-zA-Z0-9_]{3,30}$/.test(trimmedUsername)) {
      errors.username = ['Handle must be 3-30 characters (letters, numbers, underscore only).'];
    }
    if (!password) {
      errors.password = ['Password is required.'];
    } else if (password.length < 8) {
      errors.password = ['Password must be at least 8 characters long.'];
    }

    if (Object.keys(errors).length > 0) {
      setFieldErrors(errors);
      return;
    }

    try {
      await register({
        email: trimmedEmail,
        username: trimmedUsername,
        password,
      });
      navigate('/', { replace: true });
    } catch (err) {
      if (err instanceof ApiClientError) {
        if (err.details && typeof err.details === 'object' && !Array.isArray(err.details)) {
          setFieldErrors(err.details as Record<string, string[]>);
        } else {
          setGeneralError(err.message);
        }
      } else {
        setGeneralError('Failed to create account. Please check your network connection.');
      }
    }
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-4 w-full">
      {generalError && (
        <div className="flex items-start gap-2.5 p-3.5 rounded-xl border border-[#FB7185]/30 bg-[#FB7185]/10 text-xs text-[#FB7185] animate-in fade-in">
          <AlertCircle className="w-4 h-4 shrink-0 mt-0.5" />
          <div className="leading-relaxed">{generalError}</div>
        </div>
      )}

      <div className="space-y-1.5">
        <label className="block text-xs font-semibold uppercase tracking-wider text-[#9298AD]">
          Email Address
        </label>
        <div className="relative">
          <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none text-[#9298AD]">
            <Mail className="w-4 h-4" />
          </div>
          <input
            type="email"
            required
            autoComplete="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="recruit@zentiq.com"
            disabled={isLoading}
            className="w-full pl-9 pr-3.5 py-2.5 rounded-lg border border-white/10 bg-[#1B1E2D] text-sm text-[#F4F4F8] placeholder-[#9298AD]/50 focus:outline-none focus:border-[#8B5CF6] focus:ring-1 focus:ring-[#8B5CF6] transition-colors disabled:opacity-50"
          />
        </div>
        {fieldErrors.email && (
          <p className="text-[11px] text-[#FB7185]">{fieldErrors.email.join(' ')}</p>
        )}
      </div>

      <div className="space-y-1.5">
        <label className="block text-xs font-semibold uppercase tracking-wider text-[#9298AD]">
          ZENTIQ Handle
        </label>
        <div className="relative">
          <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none text-[#9298AD]">
            <AtSign className="w-4 h-4" />
          </div>
          <input
            type="text"
            required
            autoComplete="username"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            placeholder="cyber_samurai"
            disabled={isLoading}
            className="w-full pl-9 pr-3.5 py-2.5 rounded-lg border border-white/10 bg-[#1B1E2D] text-sm text-[#F4F4F8] placeholder-[#9298AD]/50 focus:outline-none focus:border-[#8B5CF6] focus:ring-1 focus:ring-[#8B5CF6] transition-colors font-mono disabled:opacity-50"
          />
        </div>
        <p className="text-[11px] text-[#9298AD]">
          Your unique public handle across leaderboards and arenas (3-30 chars).
        </p>
        {fieldErrors.username && (
          <p className="text-[11px] text-[#FB7185]">{fieldErrors.username.join(' ')}</p>
        )}
      </div>

      <div className="space-y-1.5">
        <label className="block text-xs font-semibold uppercase tracking-wider text-[#9298AD]">
          Password
        </label>
        <div className="relative">
          <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none text-[#9298AD]">
            <Lock className="w-4 h-4" />
          </div>
          <input
            type={showPassword ? 'text' : 'password'}
            required
            autoComplete="new-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder="••••••••"
            disabled={isLoading}
            className="w-full pl-9 pr-10 py-2.5 rounded-lg border border-white/10 bg-[#1B1E2D] text-sm text-[#F4F4F8] placeholder-[#9298AD]/50 focus:outline-none focus:border-[#8B5CF6] focus:ring-1 focus:ring-[#8B5CF6] transition-colors disabled:opacity-50"
          />
          <button
            type="button"
            onClick={() => setShowPassword(!showPassword)}
            className="absolute inset-y-0 right-0 pr-3 flex items-center text-[#9298AD] hover:text-[#F4F4F8] transition-colors"
            tabIndex={-1}
            aria-label={showPassword ? 'Hide password' : 'Show password'}
          >
            {showPassword ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
          </button>
        </div>
        <p className="text-[11px] text-[#9298AD]">Must contain at least 8 characters.</p>
        {fieldErrors.password && (
          <p className="text-[11px] text-[#FB7185]">{fieldErrors.password.join(' ')}</p>
        )}
      </div>

      <Button
        type="submit"
        variant="primary"
        disabled={isLoading}
        className="w-full justify-center mt-2"
      >
        {isLoading ? (
          <span className="flex items-center gap-2">
            <Loader2 className="w-4 h-4 animate-spin" />
            Creating Persona...
          </span>
        ) : (
          'Create ZENTIQ Account'
        )}
      </Button>
    </form>
  );
}

