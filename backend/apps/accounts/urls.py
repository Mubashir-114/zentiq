"""
URL routing for ZENTIQ Accounts and Authentication.
"""
from django.urls import path
from .views import (
    CsrfBootstrapView,
    LoginView,
    LogoutView,
    MeView,
    RegisterView,
    UserProfileView,
)

app_name = 'accounts'

urlpatterns = [
    # Auth Endpoints
    path('auth/csrf/', CsrfBootstrapView.as_view(), name='auth-csrf'),
    path('auth/register/', RegisterView.as_view(), name='auth-register'),
    path('auth/login/', LoginView.as_view(), name='auth-login'),
    path('auth/logout/', LogoutView.as_view(), name='auth-logout'),
    path('auth/me/', MeView.as_view(), name='auth-me'),
    # Profile Endpoints
    path('profile/', UserProfileView.as_view(), name='user-profile'),
]

