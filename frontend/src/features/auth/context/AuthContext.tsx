import {
  createContext,
  useContext,
  useEffect,
  useState,
  useCallback,
  useMemo,
  type ReactNode,
} from 'react';
import { authApi } from '../api/authApi';
import { profileApi } from '../../profile/api/profileApi';
import type {
  LoginPayload,
  ProfileUpdatePayload,
  RegisterPayload,
  User,
  UserProfile,
} from '../../../types';

export interface AuthContextType {
  user: User | null;
  profile: UserProfile | null;
  isAuthenticated: boolean;
  isInitializing: boolean;
  isLoading: boolean;
  login: (payload: LoginPayload) => Promise<void>;
  register: (payload: RegisterPayload) => Promise<void>;
  logout: () => Promise<void>;
  updateProfile: (payload: ProfileUpdatePayload) => Promise<UserProfile>;
  refreshSession: () => Promise<void>;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [profile, setProfile] = useState<UserProfile | null>(null);
  const [isInitializing, setIsInitializing] = useState<boolean>(true);
  const [isLoading, setIsLoading] = useState<boolean>(false);

  const refreshSession = useCallback(async () => {
    try {
      const session = await authApi.getMe();
      setUser(session.user);
      setProfile(session.profile);
    } catch {
      setUser(null);
      setProfile(null);
    }
  }, []);

  // Initial session restoration on application boot
  useEffect(() => {
    let isMounted = true;

    async function initSession() {
      try {
        // Bootstrap CSRF cookie first
        await authApi.getCsrf().catch(() => {});
        // Restore existing session
        const session = await authApi.getMe();
        if (isMounted) {
          setUser(session.user);
          setProfile(session.profile);
        }
      } catch {
        if (isMounted) {
          setUser(null);
          setProfile(null);
        }
      } finally {
        if (isMounted) {
          setIsInitializing(false);
        }
      }
    }

    initSession();

    return () => {
      isMounted = false;
    };
  }, []);

  const login = useCallback(async (payload: LoginPayload) => {
    setIsLoading(true);
    try {
      const session = await authApi.login(payload);
      setUser(session.user);
      setProfile(session.profile);
    } finally {
      setIsLoading(false);
    }
  }, []);

  const register = useCallback(async (payload: RegisterPayload) => {
    setIsLoading(true);
    try {
      const session = await authApi.register(payload);
      setUser(session.user);
      setProfile(session.profile);
    } finally {
      setIsLoading(false);
    }
  }, []);

  const logout = useCallback(async () => {
    setIsLoading(true);
    try {
      await authApi.logout();
    } finally {
      setUser(null);
      setProfile(null);
      setIsLoading(false);
    }
  }, []);

  const updateProfile = useCallback(async (payload: ProfileUpdatePayload) => {
    setIsLoading(true);
    try {
      const updated = await profileApi.updateProfile(payload);
      setProfile(updated);
      return updated;
    } finally {
      setIsLoading(false);
    }
  }, []);

  const value = useMemo<AuthContextType>(
    () => ({
      user,
      profile,
      isAuthenticated: Boolean(user),
      isInitializing,
      isLoading,
      login,
      register,
      logout,
      updateProfile,
      refreshSession,
    }),
    [user, profile, isInitializing, isLoading, login, register, logout, updateProfile, refreshSession]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextType {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
}

