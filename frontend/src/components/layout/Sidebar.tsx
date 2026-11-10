import { NavLink } from 'react-router-dom';
import { LayoutDashboard, Layers, Server, Terminal, Code2, User } from 'lucide-react';
import { cn } from '../../lib/utils';
import { useAuth } from '../../features/auth/context/AuthContext';

interface SidebarProps {
  isOpen: boolean;
  onClose?: () => void;
}

export function Sidebar({ isOpen, onClose }: SidebarProps) {
  const { isAuthenticated } = useAuth();

  const navItems = [
    {
      to: isAuthenticated ? '/dashboard' : '/',
      label: isAuthenticated ? 'Player Dashboard' : 'Platform Overview',
      icon: LayoutDashboard,
      description: isAuthenticated
        ? 'Core identity & skill domains'
        : 'ZENTIQ foundation summary',
    },
    ...(isAuthenticated
      ? [
          {
            to: '/profile',
            label: 'Player Persona',
            icon: User,
            description: 'Avatar, handle & preferences',
          },
        ]
      : []),
    {
      to: '/architecture',
      label: 'Architecture Specs',
      icon: Layers,
      description: 'Modular monolith boundaries',
    },
    {
      to: '/health',
      label: 'Service Health',
      icon: Server,
      description: 'Live MySQL 8.4 & API status',
    },
  ];

  return (
    <>
      {/* Mobile backdrop */}
      {isOpen && (
        <div
          className="fixed inset-0 z-40 bg-black/60 backdrop-blur-xs md:hidden"
          onClick={onClose}
          aria-hidden="true"
        />
      )}

      <aside
        className={cn(
          'fixed inset-y-0 left-0 z-50 w-64 border-r border-white/10 bg-[#10121E] pt-16 transition-transform duration-200 md:static md:translate-x-0',
          isOpen ? 'translate-x-0' : '-translate-x-full'
        )}
      >
        <div className="flex h-full flex-col justify-between p-4">
          <div className="space-y-6">
            <div className="px-3 pt-2">
              <span className="text-[11px] font-semibold uppercase tracking-wider text-[#9298AD]">
                Core Platform
              </span>
            </div>

            <nav className="space-y-1.5" aria-label="Main Navigation">
              {navItems.map((item) => {
                const Icon = item.icon;
                return (
                  <NavLink
                    key={item.to}
                    to={item.to}
                    onClick={onClose}
                    className={({ isActive }) =>
                      cn(
                        'flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-all group',
                        isActive
                          ? 'bg-[#8B5CF6]/15 text-[#F4F4F8] border border-[#8B5CF6]/30 shadow-xs'
                          : 'text-[#9298AD] hover:text-[#F4F4F8] hover:bg-white/5'
                      )
                    }
                  >
                    <Icon className="w-4 h-4 shrink-0 text-[#22D3EE] group-hover:scale-110 transition-transform" />
                    <div className="flex flex-col">
                      <span>{item.label}</span>
                      <span className="text-[10px] text-[#9298AD] font-normal">{item.description}</span>
                    </div>
                  </NavLink>
                );
              })}
            </nav>
          </div>

          <div className="rounded-xl border border-white/5 bg-[#1B1E2D]/60 p-3.5 space-y-2">
            <div className="flex items-center gap-2 text-xs font-semibold text-[#F4F4F8]">
              <Terminal className="w-3.5 h-3.5 text-[#8B5CF6]" />
              <span>Developer Specs</span>
            </div>
            <p className="text-[11px] text-[#9298AD] leading-relaxed">
              Platform Architecture &amp; Foundation. REST APIs at{' '}
              <code className="text-[#22D3EE] font-mono">/api/v1/</code>.
            </p>
            <div className="flex items-center justify-between pt-1 border-t border-white/5 text-[10px] text-[#9298AD]">
              <span>Stack</span>
              <span className="flex items-center gap-1 font-mono text-[#F4F4F8]">
                <Code2 className="w-3 h-3 text-[#34D399]" />
                React + Django
              </span>
            </div>
          </div>
        </div>
      </aside>
    </>
  );
}

