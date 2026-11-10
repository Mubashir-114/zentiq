import { useState, useEffect, type FormEvent } from 'react';
import { useAuth } from '../../auth/context/AuthContext';
import { AvatarPicker, AvatarIcon } from '../components/AvatarPicker';
import { Card } from '../../../components/ui/Card';
import { Button } from '../../../components/ui/Button';
import { Badge } from '../../../components/ui/Badge';
import { ApiClientError } from '../../../lib/api-client';
import type { AvatarKey, UserPreferences } from '../../../types';
import {
  User,
  ShieldCheck,
  CheckCircle2,
  AlertCircle,
  Loader2,
  Bell,
  Volume2,
  Moon,
  Calendar,
  Mail,
} from 'lucide-react';

export function ProfileView() {
  const { user, profile, updateProfile, isLoading } = useAuth();

  const [avatarKey, setAvatarKey] = useState<AvatarKey>(profile?.avatar_key || 'default');
  const [displayName, setDisplayName] = useState(profile?.display_name || '');
  const [bio, setBio] = useState(profile?.bio || '');
  const [soundEffects, setSoundEffects] = useState<boolean>(
    profile?.preferences?.sound_effects ?? true
  );
  const [emailNotifications, setEmailNotifications] = useState<boolean>(
    profile?.preferences?.email_notifications ?? true
  );

  const [saveSuccess, setSaveSuccess] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  // Sync state if profile loads asynchronously
  useEffect(() => {
    if (profile) {
      setAvatarKey(profile.avatar_key);
      setDisplayName(profile.display_name);
      setBio(profile.bio || '');
      setSoundEffects(profile.preferences?.sound_effects ?? true);
      setEmailNotifications(profile.preferences?.email_notifications ?? true);
    }
  }, [profile]);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setErrorMessage(null);
    setSaveSuccess(false);

    const preferences: UserPreferences = {
      theme: 'dark',
      sound_effects: soundEffects,
      email_notifications: emailNotifications,
    };

    try {
      await updateProfile({
        avatar_key: avatarKey,
        display_name: displayName.trim(),
        bio: bio.trim(),
        preferences,
      });
      setSaveSuccess(true);
      setTimeout(() => setSaveSuccess(false), 4000);
    } catch (err) {
      if (err instanceof ApiClientError) {
        setErrorMessage(err.message);
      } else {
        setErrorMessage('Failed to update profile. Please try again.');
      }
    }
  }

  const memberSince = user?.date_joined
    ? new Date(user.date_joined).toLocaleDateString(undefined, {
        year: 'numeric',
        month: 'long',
        day: 'numeric',
      })
    : 'Recently';

  return (
    <div className="max-w-4xl mx-auto space-y-8 py-8 px-4 sm:px-6">
      {/* Profile Header Banner */}
      <div className="relative overflow-hidden rounded-2xl border border-white/10 bg-gradient-to-r from-[#1B1E2D] via-[#161928] to-[#10121E] p-6 sm:p-8">
        <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-6">
          <div className="flex items-center gap-4">
            <div className="w-16 h-16 sm:w-20 sm:h-20 rounded-2xl p-[2px] bg-gradient-to-tr from-[#8B5CF6] via-[#22D3EE] to-[#F5C451] shadow-lg">
              <div className="w-full h-full bg-[#10121E] rounded-[14px] flex items-center justify-center">
                <AvatarIcon avatarKey={avatarKey} className="w-8 h-8 sm:w-10 sm:h-10 text-[#22D3EE]" />
              </div>
            </div>
            <div className="space-y-1">
              <div className="flex items-center gap-2">
                <h1 className="text-xl sm:text-2xl font-bold text-[#F4F4F8]">
                  {displayName || profile?.username || 'Player'}
                </h1>
                <Badge variant="cyan" dot className="text-xs">
                  Active
                </Badge>
              </div>
              <p className="font-mono text-sm text-[#22D3EE]">@{profile?.username}</p>
            </div>
          </div>

          <div className="flex items-center gap-4 text-xs text-[#9298AD]">
            <div className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-white/5 border border-white/5">
              <Calendar className="w-3.5 h-3.5 text-[#8B5CF6]" />
              <span>Joined {memberSince}</span>
            </div>
          </div>
        </div>
      </div>

      {saveSuccess && (
        <div className="flex items-center gap-2.5 p-4 rounded-xl border border-[#34D399]/30 bg-[#34D399]/10 text-xs text-[#34D399] animate-in fade-in">
          <CheckCircle2 className="w-4 h-4 shrink-0" />
          <span className="font-medium">Profile and preferences updated successfully!</span>
        </div>
      )}

      {errorMessage && (
        <div className="flex items-center gap-2.5 p-4 rounded-xl border border-[#FB7185]/30 bg-[#FB7185]/10 text-xs text-[#FB7185] animate-in fade-in">
          <AlertCircle className="w-4 h-4 shrink-0" />
          <span>{errorMessage}</span>
        </div>
      )}

      <form onSubmit={handleSubmit} className="space-y-8">
        {/* Avatar Persona */}
        <Card className="p-6 space-y-4">
          <AvatarPicker value={avatarKey} onChange={setAvatarKey} disabled={isLoading} />
        </Card>

        {/* Identity Details */}
        <Card className="p-6 space-y-5">
          <div className="border-b border-white/10 pb-3">
            <h2 className="text-base font-semibold text-[#F4F4F8] flex items-center gap-2">
              <User className="w-4 h-4 text-[#8B5CF6]" />
              Persona Identity
            </h2>
            <p className="text-xs text-[#9298AD] mt-0.5">
              Manage how you appear in competitive arenas and profile previews.
            </p>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-5">
            {/* Username / Handle (Immutable) */}
            <div className="space-y-1.5">
              <label className="block text-xs font-semibold uppercase tracking-wider text-[#9298AD]">
                ZENTIQ Handle
              </label>
              <div className="relative">
                <input
                  type="text"
                  disabled
                  value={`@${profile?.username || ''}`}
                  className="w-full px-3.5 py-2.5 rounded-lg border border-white/5 bg-white/5 text-sm text-[#9298AD] font-mono cursor-not-allowed"
                />
                <div className="absolute inset-y-0 right-0 pr-3 flex items-center pointer-events-none text-[#34D399]">
                  <span title="Verified Permanent Handle">
                    <ShieldCheck className="w-4 h-4" />
                  </span>
                </div>
              </div>
              <p className="text-[11px] text-[#9298AD]/70">
                Your handle is permanently registered to preserve your competition history.
              </p>
            </div>

            {/* Display Name */}
            <div className="space-y-1.5">
              <label className="block text-xs font-semibold uppercase tracking-wider text-[#9298AD]">
                Display Name
              </label>
              <input
                type="text"
                maxLength={50}
                value={displayName}
                onChange={(e) => setDisplayName(e.target.value)}
                placeholder={profile?.username}
                disabled={isLoading}
                className="w-full px-3.5 py-2.5 rounded-lg border border-white/10 bg-[#1B1E2D] text-sm text-[#F4F4F8] placeholder-[#9298AD]/50 focus:outline-none focus:border-[#8B5CF6] focus:ring-1 focus:ring-[#8B5CF6] transition-colors"
              />
              <p className="text-[11px] text-[#9298AD]/70">Friendly name shown across badges (max 50 chars).</p>
            </div>
          </div>

          {/* Biography */}
          <div className="space-y-1.5">
            <div className="flex items-center justify-between">
              <label className="block text-xs font-semibold uppercase tracking-wider text-[#9298AD]">
                Player Bio
              </label>
              <span className="text-[11px] font-mono text-[#9298AD]">{bio.length} / 250</span>
            </div>
            <textarea
              rows={3}
              maxLength={250}
              value={bio}
              onChange={(e) => setBio(e.target.value)}
              placeholder="Tell other players about your skill focus, favorite languages, or learning milestones..."
              disabled={isLoading}
              className="w-full px-3.5 py-2.5 rounded-lg border border-white/10 bg-[#1B1E2D] text-sm text-[#F4F4F8] placeholder-[#9298AD]/50 focus:outline-none focus:border-[#8B5CF6] focus:ring-1 focus:ring-[#8B5CF6] transition-colors resize-none"
            />
          </div>

          {/* Account Email Details */}
          <div className="pt-2 border-t border-white/5">
            <div className="flex items-center gap-2 text-xs text-[#9298AD]">
              <Mail className="w-3.5 h-3.5 text-[#22D3EE]" />
              <span>Registered Authentication Email:</span>
              <span className="font-mono text-[#F4F4F8]">{user?.email}</span>
            </div>
          </div>
        </Card>

        {/* Player Preferences */}
        <Card className="p-6 space-y-5">
          <div className="border-b border-white/10 pb-3">
            <h2 className="text-base font-semibold text-[#F4F4F8] flex items-center gap-2">
              <ShieldCheck className="w-4 h-4 text-[#22D3EE]" />
              System Preferences
            </h2>
            <p className="text-xs text-[#9298AD] mt-0.5">
              Customize client behavior and notification preferences.
            </p>
          </div>

          <div className="space-y-4">
            {/* Theme */}
            <div className="flex items-center justify-between py-2 border-b border-white/5">
              <div className="flex items-center gap-3">
                <div className="w-8 h-8 rounded-lg bg-white/5 flex items-center justify-center text-[#8B5CF6]">
                  <Moon className="w-4 h-4" />
                </div>
                <div>
                  <p className="text-sm font-medium text-[#F4F4F8]">Platform Theme</p>
                  <p className="text-xs text-[#9298AD]">ZENTIQ Deep Space Dark Theme (Active)</p>
                </div>
              </div>
              <Badge variant="violet" className="text-xs">
                Dark Mode
              </Badge>
            </div>

            {/* Sound Effects */}
            <div className="flex items-center justify-between py-2 border-b border-white/5">
              <div className="flex items-center gap-3">
                <div className="w-8 h-8 rounded-lg bg-white/5 flex items-center justify-center text-[#22D3EE]">
                  <Volume2 className="w-4 h-4" />
                </div>
                <div>
                  <p className="text-sm font-medium text-[#F4F4F8]">Sound Effects</p>
                  <p className="text-xs text-[#9298AD]">Auditory cues for quest completions and level ups</p>
                </div>
              </div>
              <label className="relative inline-flex items-center cursor-pointer">
                <input
                  type="checkbox"
                  checked={soundEffects}
                  onChange={(e) => setSoundEffects(e.target.checked)}
                  disabled={isLoading}
                  className="sr-only peer"
                />
                <div className="w-11 h-6 bg-white/10 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-[#22D3EE]"></div>
              </label>
            </div>

            {/* Email Notifications */}
            <div className="flex items-center justify-between py-2">
              <div className="flex items-center gap-3">
                <div className="w-8 h-8 rounded-lg bg-white/5 flex items-center justify-center text-[#F5C451]">
                  <Bell className="w-4 h-4" />
                </div>
                <div>
                  <p className="text-sm font-medium text-[#F4F4F8]">Email Notifications</p>
                  <p className="text-xs text-[#9298AD]">Weekly skill digests and system announcements</p>
                </div>
              </div>
              <label className="relative inline-flex items-center cursor-pointer">
                <input
                  type="checkbox"
                  checked={emailNotifications}
                  onChange={(e) => setEmailNotifications(e.target.checked)}
                  disabled={isLoading}
                  className="sr-only peer"
                />
                <div className="w-11 h-6 bg-white/10 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-[#8B5CF6]"></div>
              </label>
            </div>
          </div>
        </Card>

        {/* Submit Actions */}
        <div className="flex justify-end gap-3 pt-2">
          <Button
            type="submit"
            variant="primary"
            disabled={isLoading}
            className="px-6 py-2.5 font-semibold text-sm"
          >
            {isLoading ? (
              <span className="flex items-center gap-2">
                <Loader2 className="w-4 h-4 animate-spin" />
                Saving Changes...
              </span>
            ) : (
              'Save Profile Changes'
            )}
          </Button>
        </div>
      </form>
    </div>
  );
}
