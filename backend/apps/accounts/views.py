"""
API Views for ZENTIQ Accounts and Authentication.
Provides endpoints for CSRF bootstrap, registration, session login, logout,
session identity retrieval, and profile updates.
"""
from django.contrib.auth import login, logout
from django.middleware.csrf import get_token, rotate_token
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import ensure_csrf_cookie
from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import permissions, status, serializers
from rest_framework.response import Response
from rest_framework.views import APIView

from .serializers import (
    LoginSerializer,
    RegisterSerializer,
    UserProfileSerializer,
    UserWithProfileSerializer,
)


@method_decorator(ensure_csrf_cookie, name='dispatch')
class CsrfBootstrapView(APIView):
    """
    GET /api/v1/auth/csrf/
    Ensures a valid csrftoken cookie is issued to the client browser and returns the token.
    Public endpoint used to bootstrap CSRF protection for single-page applications.
    """
    permission_classes = [permissions.AllowAny]

    @extend_schema(
        summary="CSRF Bootstrap",
        description="Issues a fresh csrftoken cookie and returns the active CSRF token.",
        responses={
            200: inline_serializer(
                name="CsrfBootstrapResponse",
                fields={"csrfToken": serializers.CharField()},
            )
        },
    )
    def get(self, request, *args, **kwargs):
        token = get_token(request)
        return Response({'csrfToken': token}, status=status.HTTP_200_OK)


class RegisterView(APIView):
    """
    POST /api/v1/auth/register/
    Registers a new user and creates their unique public handle and profile.
    Automatically authenticates the newly created user and establishes a session.
    """
    permission_classes = [permissions.AllowAny]
    throttle_scope = 'auth_register'

    @extend_schema(
        summary="Register New User",
        description="Creates a new account and profile, then creates an authenticated session.",
        request=RegisterSerializer,
        responses={
            201: UserWithProfileSerializer,
            400: inline_serializer(
                name="RegisterValidationError",
                fields={
                    "error": serializers.DictField(),
                },
            ),
        },
    )
    def post(self, request, *args, **kwargs):
        serializer = RegisterSerializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        user = serializer.save()

        # Automatically log the user in
        login(request, user)
        rotate_token(request)

        response_data = UserWithProfileSerializer(user).data
        return Response(response_data, status=status.HTTP_201_CREATED)


class LoginView(APIView):
    """
    POST /api/v1/auth/login/
    Authenticates a user via email and password, establishing an HttpOnly session cookie.
    """
    permission_classes = [permissions.AllowAny]
    throttle_scope = 'auth_login'

    @extend_schema(
        summary="User Login",
        description="Validates credentials and establishes an authenticated session.",
        request=LoginSerializer,
        responses={
            200: UserWithProfileSerializer,
            401: inline_serializer(
                name="LoginInvalidCredentialsError",
                fields={
                    "error": serializers.DictField(),
                },
            ),
        },
    )
    def post(self, request, *args, **kwargs):
        serializer = LoginSerializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        user = serializer.validated_data['user']

        # Establish Django session
        login(request, user)
        rotate_token(request)

        response_data = UserWithProfileSerializer(user).data
        return Response(response_data, status=status.HTTP_200_OK)


class LogoutView(APIView):
    """
    POST /api/v1/auth/logout/
    Terminates the current user session and flushes session cookies.
    """
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        summary="User Logout",
        description="Invalidates the session in the database and clears session cookies.",
        responses={
            200: inline_serializer(
                name="LogoutResponse",
                fields={"message": serializers.CharField()},
            )
        },
    )
    def post(self, request, *args, **kwargs):
        logout(request)
        return Response({'message': 'Successfully logged out.'}, status=status.HTTP_200_OK)


class MeView(APIView):
    """
    GET /api/v1/auth/me/
    Retrieves the currently authenticated user's account details and profile.
    """
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        summary="Get Current User",
        description="Returns user identity, profile, and preferences for the active session.",
        responses={200: UserWithProfileSerializer},
    )
    def get(self, request, *args, **kwargs):
        response_data = UserWithProfileSerializer(request.user).data
        return Response(response_data, status=status.HTTP_200_OK)


class UserProfileView(APIView):
    """
    GET /api/v1/profile/ - Retrieve authenticated user's profile.
    PATCH /api/v1/profile/ - Update authenticated user's profile attributes (display name, bio, avatar, preferences).
    """
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        summary="Get Profile",
        description="Retrieves the authenticated user's profile details.",
        responses={200: UserProfileSerializer},
    )
    def get(self, request, *args, **kwargs):
        serializer = UserProfileSerializer(request.user.profile)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @extend_schema(
        summary="Update Profile",
        description="Updates display name, avatar, bio, or preferences.",
        request=UserProfileSerializer,
        responses={200: UserProfileSerializer},
    )
    def patch(self, request, *args, **kwargs):
        serializer = UserProfileSerializer(
            request.user.profile,
            data=request.data,
            partial=True,
        )
        serializer.is_valid(raise_exception=True)
        updated_profile = serializer.save()
        return Response(UserProfileSerializer(updated_profile).data, status=status.HTTP_200_OK)

