import type { AvatarKey } from '../../../types';
import { Shield, Terminal, Cpu, Sparkles, Orbit, Binary } from 'lucide-react';
import { cn } from '../../../lib/utils';

interface AvatarPickerProps {
  value: AvatarKey;
  onChange: (key: AvatarKey) => void;
  disabled?: boolean;
}

export const AVATAR_OPTIONS: {
  key: AvatarKey;
  name: string;
  description: string;
  icon: typeof Shield;
  gradient: string;
}[] = [
  {
    key: 'default',
    name: 'Default Sentinel',
    description: 'Balanced platform guardian',
    icon: Shield,
    gradient: 'from-[#8B5CF6] to-[#22D3EE]',
  },
  {
    key: 'cyber_ninja',
    name: 'Cyber Ninja',
    description: 'Swift and stealthy analytical precision',
    icon: Terminal,
    gradient: 'from-[#34D399] to-[#22D3EE]',
  },
  {
    key: 'data_hacker',
    name: 'Data Hacker',
    description: 'Systems architecture & deep inspection',
    icon: Cpu,
    gradient: 'from-[#22D3EE] to-[#8B5CF6]',
  },
  {
    key: 'quantum_mage',
    name: 'Quantum Mage',
    description: 'Advanced probabilistic problem solver',
    icon: Sparkles,
    gradient: 'from-[#F5C451] to-[#FB7185]',
  },
  {
    key: 'logic_sentinel',
    name: 'Logic Sentinel',
    description: 'Uncompromising formal reasoning',
    icon: Orbit,
    gradient: 'from-[#8B5CF6] to-[#EC4899]',
  },
  {
    key: 'binary_phantom',
    name: 'Binary Phantom',
    description: 'Zero-overhead low-level mastery',
    icon: Binary,
    gradient: 'from-[#6366F1] to-[#34D399]',
  },
];

export function AvatarIcon({
  avatarKey,
  className = 'w-6 h-6',
}: {
  avatarKey?: AvatarKey;
  className?: string;
}) {
  const avatar = AVATAR_OPTIONS.find((a) => a.key === avatarKey) || AVATAR_OPTIONS[0];
  const Icon = avatar.icon;
  return <Icon className={className} />;
}

export function AvatarPicker({ value, onChange, disabled }: AvatarPickerProps) {
  return (
    <div className="space-y-3">
      <label className="block text-xs font-semibold uppercase tracking-wider text-[#9298AD]">
        Select Avatar Persona
      </label>
      <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
        {AVATAR_OPTIONS.map((avatar) => {
          const isSelected = value === avatar.key;
          const Icon = avatar.icon;

          return (
            <button
              key={avatar.key}
              type="button"
              disabled={disabled}
              onClick={() => onChange(avatar.key)}
              className={cn(
                'relative flex items-center gap-3 p-3 rounded-xl border text-left transition-all',
                isSelected
                  ? 'border-[#22D3EE] bg-[#22D3EE]/10 shadow-[0_0_15px_rgba(34,211,238,0.15)] ring-1 ring-[#22D3EE]'
                  : 'border-white/10 bg-[#1B1E2D]/60 hover:bg-[#1B1E2D] hover:border-white/20',
                disabled && 'opacity-50 cursor-not-allowed'
              )}
            >
              <div
                className={cn(
                  'w-10 h-10 rounded-lg p-[1.5px] bg-gradient-to-tr shrink-0',
                  avatar.gradient
                )}
              >
                <div className="w-full h-full bg-[#10121E] rounded-[6.5px] flex items-center justify-center">
                  <Icon className="w-5 h-5 text-[#F4F4F8]" />
                </div>
              </div>
              <div className="min-w-0">
                <p className="text-xs font-semibold text-[#F4F4F8] truncate">{avatar.name}</p>
                <p className="text-[10px] text-[#9298AD] truncate">{avatar.description}</p>
              </div>
            </button>
          );
        })}
      </div>
    </div>
  );
}

