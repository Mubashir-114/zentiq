/**
 * ZENTIQ Core TypeScript Definitions
 */

export interface SystemServices {
  api?: 'operational' | 'unavailable' | string;
  database: 'operational' | 'unavailable' | string;
  database_connection?: 'operational' | 'unavailable' | string;
  database_engine?: 'mysql' | 'sqlite' | 'postgresql' | string;
  [key: string]: string | undefined;
}

export interface HealthResponse {
  status: 'healthy' | 'degraded' | 'unhealthy';
  version: string;
  timestamp: string;
  services: SystemServices;
}

export interface ApiError {
  code: string;
  message: string;
  details?: unknown;
}

export type VariantColor = 'violet' | 'cyan' | 'gold' | 'emerald' | 'amber' | 'rose' | 'neutral';

export type AvatarKey =
  | 'default'
  | 'cyber_ninja'
  | 'data_hacker'
  | 'quantum_mage'
  | 'logic_sentinel'
  | 'binary_phantom';

export interface UserPreferences {
  theme?: string;
  email_notifications?: boolean;
  sound_effects?: boolean;
  [key: string]: unknown;
}

export interface User {
  id: number;
  email: string;
  date_joined: string;
}

export interface UserProfile {
  username: string;
  display_name: string;
  avatar_key: AvatarKey;
  bio: string;
  preferences: UserPreferences;
  created_at: string;
  updated_at: string;
}

export interface AuthSession {
  user: User;
  profile: UserProfile;
}

export interface RegisterPayload {
  email: string;
  username: string;
  password: string;
}

export interface LoginPayload {
  email: string;
  password: string;
}

export interface ProfileUpdatePayload {
  display_name?: string;
  avatar_key?: AvatarKey;
  bio?: string;
  preferences?: Partial<UserPreferences>;
}

export interface CsrfResponse {
  csrfToken: string;
}

