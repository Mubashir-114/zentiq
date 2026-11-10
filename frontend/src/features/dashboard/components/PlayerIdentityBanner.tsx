import type { User, UserProfile } from '../../../types';
import { AvatarIcon } from '../../profile/components/AvatarPicker';
import { Badge } from '../../../components/ui/Badge';
import { Calendar, Mail, ShieldCheck } from 'lucide-react';

interface PlayerIdentityBannerProps {
  user: User;
  profile: UserProfile;
}

export function PlayerIdentityBanner({ user, profile }: PlayerIdentityBannerProps) {
  const formattedJoinDate = new Date(user.date_joined).toLocaleDateString(undefined, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
  });

  const displayName = profile.display_name?.trim() || profile.username;

  return (
    <div className="relative overflow-hidden rounded-2xl border border-white/10 bg-gradient-to-br from-[#1B1E2D] via-[#1B1E2D]/90 to-[#10121E] p-6 sm:p-8">
      {/* Subtle atmospheric glow */}
      <div
        className="absolute -top-24 -right-24 w-80 h-80 rounded-full bg-[#8B5CF6]/10 blur-3xl pointer-events-none"
        aria-hidden="true"
      />
      <div
        className="absolute -bottom-24 -left-24 w-80 h-80 rounded-full bg-[#22D3EE]/10 blur-3xl pointer-events-none"
        aria-hidden="true"
      />

      <div className="relative flex flex-col md:flex-row md:items-center md:justify-between gap-6">
        <div className="flex items-start sm:items-center gap-4 sm:gap-5">
          {/* Avatar representation with frame */}
          <div className="relative shrink-0">
            <div className="w-16 h-16 sm:w-20 sm:h-20 rounded-xl p-[2px] bg-gradient-to-tr from-[#8B5CF6] via-[#22D3EE] to-[#8B5CF6] shadow-lg shadow-[#8B5CF6]/20">
              <div className="w-full h-full bg-[#10121E] rounded-[10px] flex items-center justify-center">
                <AvatarIcon
                  avatarKey={profile.avatar_key}
                  className="w-8 h-8 sm:w-10 sm:h-10 text-[#22D3EE]"
                />
              </div>
            </div>
            <div
              className="absolute -bottom-1 -right-1 w-5 h-5 rounded-full bg-[#34D399] border-2 border-[#10121E] flex items-center justify-center"
              title="Session Active"
              aria-label="Active session indicator"
            >
              <div className="w-1.5 h-1.5 rounded-full bg-white" />
            </div>
          </div>

          <div className="space-y-1.5 min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <Badge variant="cyan" dot>
                Authenticated Pilot
              </Badge>
              <Badge variant="neutral">
                Progression Engine: Coming soon
              </Badge>
            </div>

            <h1 className="text-2xl sm:text-3xl font-bold tracking-tight text-[#F4F4F8] truncate">
              {displayName}
            </h1>

            <div className="flex flex-wrap items-center gap-y-1 gap-x-4 text-xs sm:text-sm text-[#9298AD] font-mono">
              <span className="text-[#22D3EE] font-medium">@{profile.username}</span>
              <span className="flex items-center gap-1.5 truncate">
                <Mail className="w-3.5 h-3.5 shrink-0" aria-hidden="true" />
                <span className="truncate">{user.email}</span>
              </span>
              <span className="flex items-center gap-1.5">
                <Calendar className="w-3.5 h-3.5 shrink-0" aria-hidden="true" />
                <span>Joined {formattedJoinDate}</span>
              </span>
            </div>
          </div>
        </div>

        <div className="shrink-0 flex items-center gap-2 pt-2 md:pt-0 border-t md:border-t-0 border-white/5">
          <div className="flex items-center gap-2 px-3 py-2 rounded-xl bg-white/5 border border-white/10 text-xs text-[#9298AD]">
            <ShieldCheck className="w-4 h-4 text-[#34D399]" aria-hidden="true" />
            <span>ZENTIQ CORE v1</span>
          </div>
        </div>
      </div>
    </div>
  );
}

