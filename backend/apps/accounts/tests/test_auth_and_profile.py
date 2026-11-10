"""
Comprehensive Automated Tests for ZENTIQ Authentication and User Profile API.
Covers registration, session login, logout, session restoration, CSRF enforcement,
profile management, input validation, and rate throttling.
"""
from django.contrib.auth import get_user_model
from django.test import override_settings
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase, APIClient
from apps.accounts.models import UserProfile

User = get_user_model()


class AuthenticationAndProfileTests(APITestCase):
    """Test suite covering complete authentication lifecycle and profile endpoints."""

    def setUp(self):
        self.register_url = reverse('accounts:auth-register')
        self.login_url = reverse('accounts:auth-login')
        self.logout_url = reverse('accounts:auth-logout')
        self.me_url = reverse('accounts:auth-me')
        self.csrf_url = reverse('accounts:auth-csrf')
        self.profile_url = reverse('accounts:user-profile')

        self.valid_email = 'pilot@zentiq.com'
        self.valid_username = 'cyber_pilot'
        self.valid_password = 'CyberPassword123!'

        self.user = User.objects.create_user(email=self.valid_email, password=self.valid_password)
        self.profile = UserProfile.objects.create(
            user=self.user,
            username=self.valid_username,
            display_name='Cyber Pilot',
            avatar_key='cyber_ninja',
            bio='Test bio',
            preferences={'theme': 'dark', 'sound_effects': True},
        )

    # 1. CSRF Bootstrap
    def test_csrf_bootstrap_endpoint(self):
        """GET /api/v1/auth/csrf/ returns a valid token and sets csrftoken cookie."""
        response = self.client.get(self.csrf_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('csrfToken', response.data)
        self.assertTrue(len(response.data['csrfToken']) > 0)
        self.assertIn('csrftoken', response.cookies)

    # 2. Registration
    def test_registration_success(self):
        """POST /api/v1/auth/register/ creates user, profile, and establishes session."""
        payload = {
            'email': 'new_recruit@zentiq.com',
            'username': 'new_recruit',
            'password': 'StrongPass456!@#',
        }
        response = self.client.post(self.register_url, payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['user']['email'], 'new_recruit@zentiq.com')
        self.assertEqual(response.data['profile']['username'], 'new_recruit')
        self.assertEqual(response.data['profile']['display_name'], 'new_recruit')
        self.assertEqual(response.data['profile']['avatar_key'], 'default')
        self.assertTrue(response.data['profile']['preferences']['sound_effects'])

        # Verify session cookie was established
        self.assertIn('sessionid', response.cookies)
        self.assertTrue(User.objects.filter(email='new_recruit@zentiq.com').exists())
        self.assertTrue(UserProfile.objects.filter(username='new_recruit').exists())

    def test_registration_duplicate_email(self):
        """Registration fails when email already exists (case-insensitive)."""
        payload = {
            'email': self.valid_email.upper(),
            'username': 'unique_handle',
            'password': 'StrongPass456!@#',
        }
        response = self.client.post(self.register_url, payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('email', response.data['error']['details'])

    def test_registration_duplicate_username(self):
        """Registration fails when username already exists (case-insensitive)."""
        payload = {
            'email': 'unique_email@zentiq.com',
            'username': self.valid_username.upper(),
            'password': 'StrongPass456!@#',
        }
        response = self.client.post(self.register_url, payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('username', response.data['error']['details'])

    def test_registration_invalid_username_format(self):
        """Registration fails when username contains invalid characters or length."""
        # Spaces & symbols
        payload = {
            'email': 'valid@zentiq.com',
            'username': 'bad handle!',
            'password': 'StrongPass456!@#',
        }
        response = self.client.post(self.register_url, payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        # Too short (< 3 characters)
        payload['username'] = 'ab'
        response = self.client.post(self.register_url, payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_registration_weak_password(self):
        """Registration fails when password is too short (< 8 characters)."""
        payload = {
            'email': 'valid@zentiq.com',
            'username': 'good_handle',
            'password': 'short',
        }
        response = self.client.post(self.register_url, payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('password', response.data['error']['details'])

    # 3. Login
    def test_login_success(self):
        """POST /api/v1/auth/login/ returns 200, user/profile, and session cookie."""
        payload = {
            'email': self.valid_email,
            'password': self.valid_password,
        }
        response = self.client.post(self.login_url, payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['user']['email'], self.valid_email)
        self.assertEqual(response.data['profile']['username'], self.valid_username)
        self.assertIn('sessionid', response.cookies)

    def test_login_invalid_credentials(self):
        """Login with wrong password returns 401 Unauthorized."""
        payload = {
            'email': self.valid_email,
            'password': 'WrongPassword!',
        }
        response = self.client.post(self.login_url, payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(response.data['error']['code'], 'invalid_credentials')

    def test_login_inactive_user(self):
        """Login with inactive account returns 403 Forbidden."""
        self.user.is_active = False
        self.user.save()

        payload = {
            'email': self.valid_email,
            'password': self.valid_password,
        }
        response = self.client.post(self.login_url, payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.data['error']['code'], 'account_inactive')

    # 4. Session Restoration & Current User
    def test_me_authenticated(self):
        """GET /api/v1/auth/me/ returns current user and profile data for active session."""
        self.client.force_login(self.user)
        response = self.client.get(self.me_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['user']['email'], self.valid_email)
        self.assertEqual(response.data['profile']['username'], self.valid_username)
        self.assertEqual(response.data['profile']['avatar_key'], 'cyber_ninja')

    def test_me_unauthenticated(self):
        """GET /api/v1/auth/me/ returns 401 Unauthorized when not logged in."""
        response = self.client.get(self.me_url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    # 5. Logout
    def test_logout_success(self):
        """POST /api/v1/auth/logout/ terminates session."""
        self.client.force_login(self.user)
        response = self.client.post(self.logout_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['message'], 'Successfully logged out.')

        # Subsequent authenticated request must now fail
        next_response = self.client.get(self.me_url)
        self.assertEqual(next_response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_logout_unauthenticated(self):
        """POST /api/v1/auth/logout/ without session returns 401."""
        response = self.client.post(self.logout_url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    # 6. Profile Management
    def test_profile_get_authenticated(self):
        """GET /api/v1/profile/ returns profile for logged-in user."""
        self.client.force_login(self.user)
        response = self.client.get(self.profile_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['username'], self.valid_username)
        self.assertEqual(response.data['display_name'], 'Cyber Pilot')
        self.assertEqual(response.data['avatar_key'], 'cyber_ninja')

    def test_profile_patch_display_name_and_bio(self):
        """PATCH /api/v1/profile/ successfully updates display name and bio."""
        self.client.force_login(self.user)
        patch_data = {
            'display_name': 'Commander Pilot',
            'bio': 'Updated biography line.',
            'avatar_key': 'data_hacker',
            'preferences': {'sound_effects': False},
        }
        response = self.client.patch(self.profile_url, patch_data, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['display_name'], 'Commander Pilot')
        self.assertEqual(response.data['bio'], 'Updated biography line.')
        self.assertEqual(response.data['avatar_key'], 'data_hacker')
        # Merged preferences: sound_effects is False, original theme is preserved
        self.assertFalse(response.data['preferences']['sound_effects'])
        self.assertEqual(response.data['preferences']['theme'], 'dark')

    def test_profile_patch_unsupported_preference_key(self):
        """PATCH /api/v1/profile/ rejects arbitrary or unsupported preference keys."""
        self.client.force_login(self.user)
        response = self.client.patch(
            self.profile_url,
            {'preferences': {'unauthorized_key': 'malicious_payload', 'xp': 999999}},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('preferences', response.data['error']['details'])

    def test_profile_patch_invalid_preference_type(self):
        """PATCH /api/v1/profile/ rejects malformed preference types."""
        self.client.force_login(self.user)
        # sound_effects must be boolean, not string
        response = self.client.patch(
            self.profile_url,
            {'preferences': {'sound_effects': 'not-a-boolean'}},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('preferences', response.data['error']['details'])

    def test_profile_patch_invalid_avatar(self):
        """PATCH /api/v1/profile/ rejects unapproved avatar key."""
        self.client.force_login(self.user)
        response = self.client.patch(self.profile_url, {'avatar_key': 'unauthorized_avatar'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('avatar_key', response.data['error']['details'])

    def test_profile_patch_username_is_read_only(self):
        """PATCH /api/v1/profile/ does not allow mutating unique handle."""
        self.client.force_login(self.user)
        response = self.client.patch(self.profile_url, {'username': 'hacked_handle'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Username remains unchanged
        self.assertEqual(response.data['username'], self.valid_username)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.username, self.valid_username)

    def test_profile_unauthenticated_access(self):
        """Unauthenticated access to profile returns 401."""
        response = self.client.get(self.profile_url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        response = self.client.patch(self.profile_url, {'display_name': 'No Auth'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    # 7. CSRF Enforcement with APIClient(enforce_csrf_checks=True)
    def test_csrf_protection_enforced_on_mutating_session_request(self):
        """Mutating request from authenticated session without valid CSRF header is rejected."""
        csrf_client = APIClient(enforce_csrf_checks=True)
        csrf_client.force_login(self.user)

        # Mutating request without X-CSRFToken header should return 403 Forbidden
        response = csrf_client.patch(self.profile_url, {'bio': 'Attempt without CSRF'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

        # Bootstrap CSRF and retry with valid header
        csrf_response = csrf_client.get(self.csrf_url)
        csrf_token = csrf_response.cookies['csrftoken'].value

        valid_response = csrf_client.patch(
            self.profile_url,
            {'bio': 'Attempt with CSRF'},
            format='json',
            HTTP_X_CSRFTOKEN=csrf_token,
        )
        self.assertEqual(valid_response.status_code, status.HTTP_200_OK)

    # 8. Throttling
    def test_login_throttling(self):
        """Brute-force attempts against login endpoint trigger 429 Too Many Requests."""
        from unittest.mock import patch
        from django.core.cache import cache
        from rest_framework.throttling import ScopedRateThrottle

        cache.clear()
        with patch.dict(ScopedRateThrottle.THROTTLE_RATES, {'auth_login': '2/minute'}):
            try:
                # 2 requests fail with 401
                r1 = self.client.post(self.login_url, {'email': 'test@zentiq.com', 'password': 'wrong'}, format='json')
                self.assertEqual(r1.status_code, status.HTTP_401_UNAUTHORIZED)
                r2 = self.client.post(self.login_url, {'email': 'test@zentiq.com', 'password': 'wrong'}, format='json')
                self.assertEqual(r2.status_code, status.HTTP_401_UNAUTHORIZED)
                # 3rd request triggers 429 Too Many Requests
                r3 = self.client.post(self.login_url, {'email': 'test@zentiq.com', 'password': 'wrong'}, format='json')
                self.assertEqual(r3.status_code, status.HTTP_429_TOO_MANY_REQUESTS)
            finally:
                cache.clear()


