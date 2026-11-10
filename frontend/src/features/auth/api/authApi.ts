import { apiClient } from '../../../lib/api-client';
import type {
  AuthSession,
  CsrfResponse,
  LoginPayload,
  RegisterPayload,
} from '../../../types';

/**
 * Authentication API Service.
 * Interfaces with Django session-based endpoints under /api/v1/auth/.
 */
export const authApi = {
  /**
   * Bootstraps CSRF token and ensures csrftoken cookie is issued.
   */
  async getCsrf(): Promise<CsrfResponse> {
    return apiClient.get<CsrfResponse>('/auth/csrf/');
  },

  /**
   * Registers a new user account with unique handle and establishes session.
   */
  async register(payload: RegisterPayload): Promise<AuthSession> {
    return apiClient.post<AuthSession>('/auth/register/', payload);
  },

  /**
   * Authenticates user via email and password, establishing an HttpOnly session.
   */
  async login(payload: LoginPayload): Promise<AuthSession> {
    return apiClient.post<AuthSession>('/auth/login/', payload);
  },

  /**
   * Invalids current session in database and clears session cookies.
   */
  async logout(): Promise<{ message: string }> {
    return apiClient.post<{ message: string }>('/auth/logout/');
  },

  /**
   * Restores active session and returns user and profile data.
   */
  async getMe(): Promise<AuthSession> {
    return apiClient.get<AuthSession>('/auth/me/');
  },
};

