import { Link } from 'react-router-dom';
import type { UserProfile } from '../../../types';
import { Card, CardHeader, CardTitle, CardDescription, CardContent, CardFooter } from '../../../components/ui/Card';
import { Button } from '../../../components/ui/Button';
import { AVATAR_OPTIONS } from '../../profile/components/AvatarPicker';
import { UserCog, ArrowRight, Quote } from 'lucide-react';

interface OnboardingPersonaCardProps {
  profile: UserProfile;
}

export function OnboardingPersonaCard({ profile }: OnboardingPersonaCardProps) {
  const avatarOption =
    AVATAR_OPTIONS.find((opt) => opt.key === profile.avatar_key) || AVATAR_OPTIONS[0];

  return (
    <Card glow className="border-white/10">
      <CardHeader>
        <div className="flex items-center gap-2">
          <UserCog className="w-5 h-5 text-[#8B5CF6]" aria-hidden="true" />
          <CardTitle>Player Persona</CardTitle>
        </div>
        <CardDescription>
          Your public presence across the ZENTIQ cognitive ecosystem.
        </CardDescription>
      </CardHeader>

      <CardContent className="space-y-3.5 text-xs">
        <div className="space-y-1">
          <span className="text-[11px] font-semibold uppercase tracking-wider text-[#9298AD]">
            Avatar Persona
          </span>
          <div className="flex items-center gap-2 text-sm text-[#F4F4F8] font-medium">
            <span className="w-2 h-2 rounded-full bg-[#22D3EE]" aria-hidden="true" />
            <span>{avatarOption.name}</span>
            <span className="text-xs text-[#9298AD] font-normal">({avatarOption.description})</span>
          </div>
        </div>

        <div className="space-y-1">
          <span className="text-[11px] font-semibold uppercase tracking-wider text-[#9298AD]">
            Bio Statement
          </span>
          {profile.bio?.trim() ? (
            <div className="flex items-start gap-2 p-2.5 rounded-lg bg-white/5 border border-white/5 text-[#F4F4F8] italic text-xs leading-relaxed">
              <Quote className="w-3.5 h-3.5 text-[#8B5CF6] shrink-0 mt-0.5" aria-hidden="true" />
              <span>{profile.bio}</span>
            </div>
          ) : (
            <p className="text-[#9298AD] italic text-xs">
              No bio statement added yet. You can set one in your persona settings.
            </p>
          )}
        </div>
      </CardContent>

      <CardFooter>
        <Link to="/profile" className="w-full">
          <Button
            variant="secondary"
            size="sm"
            className="w-full justify-between group"
            rightIcon={
              <ArrowRight className="w-4 h-4 text-[#8B5CF6] transition-transform group-hover:translate-x-1" />
            }
          >
            Edit Persona Settings
          </Button>
        </Link>
      </CardFooter>
    </Card>
  );
}

