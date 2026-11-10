import { createBrowserRouter, Navigate, Outlet } from 'react-router-dom';
import { Shell } from '../components/layout/Shell';
import { AuthProvider, useAuth } from '../features/auth/context/AuthContext';
import { ProtectedRoute } from '../components/auth/ProtectedRoute';
import { PublicOnlyRoute } from '../components/auth/PublicOnlyRoute';
import { HomeView } from '../features/overview/HomeView';
import { ArchitectureView } from '../features/architecture/ArchitectureView';
import { HealthView } from '../features/health/HealthView';
import { NotFoundView } from '../features/common/NotFoundView';
import { LoginView } from '../features/auth/views/LoginView';
import { RegisterView } from '../features/auth/views/RegisterView';
import { ProfileView } from '../features/profile/views/ProfileView';
import { DashboardView } from '../features/dashboard/views/DashboardView';
import { HealthProvider, useHealth } from '../features/health/context/HealthContext';
import { Loader2 } from 'lucide-react';

function RootIndex() {
  const { isAuthenticated, isInitializing } = useAuth();

  if (isInitializing) {
    return (
      <div className="min-h-[50vh] flex flex-col items-center justify-center p-8">
        <Loader2 className="w-8 h-8 text-[#8B5CF6] animate-spin mb-4" />
        <p className="text-sm font-medium text-[#9298AD]">Verifying session...</p>
      </div>
    );
  }

  if (isAuthenticated) {
    return <Navigate to="/dashboard" replace />;
  }

  return <HomeView />;
}

function AppShell() {
  const { isHealthy } = useHealth();

  return (
    <Shell isHealthy={isHealthy}>
      <Outlet />
    </Shell>
  );
}

function RootLayout() {
  return (
    <AuthProvider>
      <HealthProvider>
        <AppShell />
      </HealthProvider>
    </AuthProvider>
  );
}

export const router = createBrowserRouter([
  {
    path: '/',
    element: <RootLayout />,
    children: [
      {
        index: true,
        element: <RootIndex />,
      },
      {
        path: 'dashboard',
        element: (
          <ProtectedRoute>
            <DashboardView />
          </ProtectedRoute>
        ),
      },
      {
        path: 'architecture',
        element: <ArchitectureView />,
      },
      {
        path: 'health',
        element: <HealthView />,
      },
      {
        path: 'login',
        element: (
          <PublicOnlyRoute>
            <LoginView />
          </PublicOnlyRoute>
        ),
      },
      {
        path: 'register',
        element: (
          <PublicOnlyRoute>
            <RegisterView />
          </PublicOnlyRoute>
        ),
      },
      {
        path: 'profile',
        element: (
          <ProtectedRoute>
            <ProfileView />
          </ProtectedRoute>
        ),
      },
      {
        path: '404',
        element: <NotFoundView />,
      },
      {
        path: '*',
        element: <Navigate to="/404" replace />,
      },
    ],
  },
]);
