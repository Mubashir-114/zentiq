"""
Focused Unit Tests for ZENTIQ Custom User Model and Manager.
"""
from django.test import TestCase
from django.contrib.auth import get_user_model
from django.db import IntegrityError

User = get_user_model()

class UserModelTests(TestCase):
    """Test suite for User model and UserManager."""

    def test_create_user_successful(self):
        """Test creating a standard user with valid email and password."""
        email = 'player@zentiq.com'
        password = 'SecurePassword123!'
        user = User.objects.create_user(email=email, password=password)

        self.assertEqual(user.email, email)
        self.assertTrue(user.check_password(password))
        self.assertTrue(user.is_active)
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)
        self.assertEqual(str(user), email)

    def test_create_user_email_normalized(self):
        """Test that the email domain is automatically normalized to lowercase."""
        email = 'PLAYER@ZENtiq.COM'
        expected = 'PLAYER@zentiq.com'
        user = User.objects.create_user(email=email, password='SecurePassword123!')
        self.assertEqual(user.email, expected)

    def test_create_user_missing_email_raises_value_error(self):
        """Test that creating a user without an email raises ValueError."""
        with self.assertRaises(ValueError):
            User.objects.create_user(email='', password='SecurePassword123!')

        with self.assertRaises(ValueError):
            User.objects.create_user(email=None, password='SecurePassword123!')

    def test_duplicate_email_raises_integrity_error(self):
        """Test that email uniqueness is strictly enforced."""
        email = 'unique@zentiq.com'
        User.objects.create_user(email=email, password='Password1!')
        with self.assertRaises(IntegrityError):
            User.objects.create_user(email=email, password='Password2!')

    def test_create_superuser_successful(self):
        """Test creating a superuser has is_staff=True and is_superuser=True."""
        email = 'admin@zentiq.com'
        password = 'AdminPassword123!'
        admin_user = User.objects.create_superuser(email=email, password=password)

        self.assertEqual(admin_user.email, email)
        self.assertTrue(admin_user.check_password(password))
        self.assertTrue(admin_user.is_active)
        self.assertTrue(admin_user.is_staff)
        self.assertTrue(admin_user.is_superuser)

    def test_create_superuser_invalid_staff_flag(self):
        """Test superuser creation requires is_staff=True."""
        with self.assertRaises(ValueError):
            User.objects.create_superuser(
                email='admin_bad@zentiq.com',
                password='Password123!',
                is_staff=False,
            )

    def test_create_superuser_invalid_superuser_flag(self):
        """Test superuser creation requires is_superuser=True."""
        with self.assertRaises(ValueError):
            User.objects.create_superuser(
                email='admin_bad2@zentiq.com',
                password='Password123!',
                is_superuser=False,
            )

