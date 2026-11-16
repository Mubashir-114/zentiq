import { useState, useRef, useEffect } from 'react';
import { Link, NavLink, useLocation, useNavigate } from 'react-router-dom';
import { cn } from '../../lib/utils';
import { Badge } from '../ui/Badge';
import { Button } from '../ui/Button';
import { useAuth } from '../../features/auth/context/AuthContext';
import { AvatarIcon } from '../../features/profile/components/AvatarPicker';
import {
  Activity,
  ShieldCheck,
  Menu,
  User,
  LogOut,
  ChevronDown,
  LayoutDashboard,
  ClipboardList,
} from 'lucide-react';

interface HeaderProps {
  onToggleSidebar?: () => void;
  isHealthy?: boolean | null;
}

export function Header({ onToggleSidebar, isHealthy = null }: HeaderProps) {
  const { user, profile, isAuthenticated, logout } = useAuth();
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const isLanding = pathname === '/';
  const [userMenuOpen, setUserMenuOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  // Close menu on click outside
  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (menuRef.current && !menuRef.current.contains(event.target as Node)) {
        setUserMenuOpen(false);
      }
    }
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  async function handleLogout() {
    setUserMenuOpen(false);
    await logout();
    navigate('/');
  }

  // Guest links get an animated volt underline; authenticated nav keeps its
  // existing treatment so app surfaces are unaffected.
  const navLinkClass = (isActive: boolean) =>
    cn(
      'text-sm font-medium text-[#9298AD] hover:text-[#F4F4F8] transition-colors',
      !isAuthenticated &&
        "relative rounded-sm after:absolute after:-bottom-2 after:left-0 after:h-px after:w-full after:origin-left after:scale-x-0 after:bg-volt after:transition-transform after:duration-[var(--duration-base)] after:ease-[var(--ease-out-expo)] after:content-[''] hover:after:scale-x-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-volt focus-visible:ring-offset-2 focus-visible:ring-offset-void",
      !isAuthenticated && isActive && 'text-[#F4F4F8] after:scale-x-100'
    );

  return (
    <header
      className={cn(
        'sticky top-0 z-40 w-full border-b border-white/10 bg-[#10121E]/80 backdrop-blur-md',
        isLanding && 'zq-header--landing'
      )}
    >
      <div className="flex h-16 items-center justify-between px-4 sm:px-6 lg:px-8">
        <div className="flex items-center gap-4">
          <button
            type="button"
            onClick={onToggleSidebar}
            className="md:hidden p-2 rounded-lg text-[#9298AD] hover:text-[#F4F4F8] hover:bg-white/5 focus:outline-none focus-visible:ring-2 focus-visible:ring-volt"
            aria-label="Toggle navigation sidebar"
          >
            <Menu className="w-5 h-5" />
          </button>

          <Link
            to="/"
            className="group flex items-center gap-3 rounded-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-volt focus-visible:ring-offset-2 focus-visible:ring-offset-void"
          >
            <div className="w-9 h-9 rounded-lg bg-gradient-to-tr from-[#8B5CF6] to-[#22D3EE] p-[1.5px] transition-transform group-hover:scale-105">
              <div className="w-full h-full bg-[#10121E] rounded-[6.5px] flex items-center justify-center">
                <span className="font-bold text-base tracking-wider bg-gradient-to-r from-[#8B5CF6] to-[#22D3EE] bg-clip-text text-transparent">
                  Z
                </span>
              </div>
            </div>
            <div className="flex flex-col">
              <span className="text-lg font-bold tracking-wider text-[#F4F4F8] group-hover:text-[#22D3EE] transition-colors">
                ZENTIQ
              </span>
              <span className="text-[10px] uppercase tracking-widest text-[#9298AD] -mt-1 hidden sm:block">
                Level Up Your Mind
              </span>
            </div>
          </Link>
        </div>

        <nav className="hidden md:flex items-center gap-6" aria-label="Desktop Navigation">
          <NavLink
            to={isAuthenticated ? '/dashboard' : '/'}
            end={!isAuthenticated}
            className={({ isActive }) => navLinkClass(isActive)}
          >
            {isAuthenticated ? 'Dashboard' : 'Overview'}
          </NavLink>
          {isAuthenticated && (
            <Link
              to="/assessments"
              className="text-sm font-medium text-[#9298AD] hover:text-[#F4F4F8] transition-colors"
            >
              Assessments
            </Link>
          )}
          <NavLink to="/architecture" className={({ isActive }) => navLinkClass(isActive)}>
            Architecture
          </NavLink>
          <NavLink to="/health" className={({ isActive }) => navLinkClass(isActive)}>
            System Status
          </NavLink>
        </nav>

        <div className="flex items-center gap-3">
          <Link to="/health" title="View live system connectivity" className="hidden sm:inline-flex">
            <Badge
              variant={isHealthy === true ? 'success' : isHealthy === false ? 'warning' : 'neutral'}
              dot
              className="cursor-pointer hover:bg-opacity-25 transition-all text-xs"
            >
              <Activity className="w-3 h-3 mr-1" />
              {isHealthy === true ? 'Operational' : isHealthy === false ? 'Degraded' : 'Checking...'}
            </Badge>
          </Link>

          <div className="hidden lg:flex items-center gap-1.5 px-2.5 py-1 rounded-md bg-white/5 border border-white/5 text-[11px] text-[#9298AD] font-mono">
            <ShieldCheck className="w-3.5 h-3.5 text-[#22D3EE]" />
            <span>v1.3.0-m3b</span>
          </div>

          {/* Authentication State Controls */}
          {isAuthenticated && user && profile ? (
            <div className="relative" ref={menuRef}>
              <button
                type="button"
                onClick={() => setUserMenuOpen(!userMenuOpen)}
                className="flex items-center gap-2 p-1.5 sm:px-3 sm:py-1.5 rounded-full sm:rounded-lg border border-white/10 bg-[#1B1E2D]/80 hover:bg-[#1B1E2D] hover:border-white/20 transition-all focus:outline-none focus-visible:ring-2 focus-visible:ring-[#8B5CF6]"
                aria-expanded={userMenuOpen}
                aria-haspopup="true"
              >
                <div className="w-7 h-7 rounded-md p-[1px] bg-gradient-to-tr from-[#8B5CF6] to-[#22D3EE] shrink-0">
                  <div className="w-full h-full bg-[#10121E] rounded-[5px] flex items-center justify-center">
                    <AvatarIcon avatarKey={profile.avatar_key} className="w-4 h-4 text-[#22D3EE]" />
                  </div>
                </div>
                <span className="hidden sm:inline font-mono text-xs font-medium text-[#F4F4F8]">
                  @{profile.username}
                </span>
                <ChevronDown className="w-3.5 h-3.5 text-[#9298AD] hidden sm:block" />
              </button>

              {/* Dropdown Menu */}
              {userMenuOpen && (
                <div className="absolute right-0 mt-2 w-48 rounded-xl border border-white/10 bg-[#10121E] shadow-2xl py-1.5 z-50 animate-in fade-in slide-in-from-top-2">
                  <div className="px-3.5 py-2 border-b border-white/5">
                    <p className="text-xs font-semibold text-[#F4F4F8] truncate">
                      {profile.display_name || profile.username}
                    </p>
                    <p className="text-[11px] text-[#9298AD] font-mono truncate">{user.email}</p>
                  </div>

                  <Link
                    to="/dashboard"
                    onClick={() => setUserMenuOpen(false)}
                    className="flex items-center gap-2.5 px-3.5 py-2 text-xs text-[#F4F4F8] hover:bg-white/5 transition-colors"
                  >
                    <LayoutDashboard className="w-3.5 h-3.5 text-[#22D3EE]" />
                    <span>Player Dashboard</span>
                  </Link>

                  <Link
                    to="/assessments"
                    onClick={() => setUserMenuOpen(false)}
                    className="flex items-center gap-2.5 px-3.5 py-2 text-xs text-[#F4F4F8] hover:bg-white/5 transition-colors"
                  >
                    <ClipboardList className="w-3.5 h-3.5 text-[#F5C451]" />
                    <span>Assessment Catalogue</span>
                  </Link>

                  <Link
                    to="/profile"
                    onClick={() => setUserMenuOpen(false)}
                    className="flex items-center gap-2.5 px-3.5 py-2 text-xs text-[#F4F4F8] hover:bg-white/5 transition-colors"
                  >
                    <User className="w-3.5 h-3.5 text-[#8B5CF6]" />
                    <span>Profile &amp; Settings</span>
                  </Link>

                  <button
                    type="button"
                    onClick={handleLogout}
                    className="w-full flex items-center gap-2.5 px-3.5 py-2 text-xs text-[#FB7185] hover:bg-[#FB7185]/10 transition-colors text-left"
                  >
                    <LogOut className="w-3.5 h-3.5" />
                    <span>Sign Out</span>
                  </button>
                </div>
              )}
            </div>
          ) : (
            <div className="flex items-center gap-2">
              <Link to="/login">
                <Button variant="ghost" size="sm" className="text-xs">
                  Sign In
                </Button>
              </Link>
              <Link to="/register">
                <Button variant="primary" size="sm" className="text-xs font-semibold">
                  Get Started
                </Button>
              </Link>
            </div>
          )}
        </div>
      </div>
    </header>
  );
}
