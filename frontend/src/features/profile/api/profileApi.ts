import { apiClient } from '../../../lib/api-client';
import type { ProfileUpdatePayload, UserProfile } from '../../../types';

/**
 * User Profile API Service.
 * Manages player handles, avatars, bio, and preferences under /api/v1/profile/.
 */
export const profileApi = {
  /**
   * Retrieves profile data for the authenticated player.
   */
  async getProfile(): Promise<UserProfile> {
    return apiClient.get<UserProfile>('/profile/');
  },

  /**
   * Partially updates profile data (display_name, avatar_key, bio, preferences).
   */
  async updateProfile(payload: ProfileUpdatePayload): Promise<UserProfile> {
    return apiClient.patch<UserProfile>('/profile/', payload);
  },
};

