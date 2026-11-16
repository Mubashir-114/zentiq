import React, { useState } from 'react';
import { useLocation } from 'react-router-dom';
import { Header } from './Header';
import { Sidebar } from './Sidebar';
import { Reveal } from '../../features/overview/components/Reveal';
import { cn } from '../../lib/utils';

interface ShellProps {
  children: React.ReactNode;
  isHealthy?: boolean | null;
}

export function Shell({ children, isHealthy = null }: ShellProps) {
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const { pathname } = useLocation();
  const isLanding = pathname === '/';

  return (
    <div className="min-h-screen bg-[#10121E] text-[#F4F4F8] flex flex-col">
      <Header
        onToggleSidebar={() => setSidebarOpen(!sidebarOpen)}
        isHealthy={isHealthy}
      />

      <div className="flex flex-1">
        <Sidebar
          isOpen={sidebarOpen}
          onClose={() => setSidebarOpen(false)}
        />

        <main className="flex-1 overflow-y-auto px-4 py-8 sm:px-6 lg:px-10">
          <div className="mx-auto max-w-6xl space-y-8">
            {children}
          </div>
        </main>
      </div>

      <footer
        className={cn(
          'border-t border-white/5 bg-[#10121E] py-4 px-6 text-center text-xs text-[#9298AD]',
          isLanding && 'zq-footer--landing'
        )}
      >
        {isLanding && <div className="zq-footer-horizon" aria-hidden="true" />}
        <div className="relative z-10 flex flex-col sm:flex-row items-center justify-between max-w-6xl mx-auto gap-2">
          <Reveal delay={0} rootMargin="0px" className="w-full sm:w-auto">
            <span>&copy; 2026 ZENTIQ. Level Up Your Mind.</span>
          </Reveal>
          <Reveal delay={90} rootMargin="0px" className="w-full sm:w-auto">
            <div className="flex items-center justify-center sm:justify-end gap-4 text-[11px] font-mono">
              <span>MySQL 8.4</span>
              <span>&bull;</span>
              <span>Django 6.0</span>
              <span>&bull;</span>
              <span>React 19</span>
            </div>
          </Reveal>
        </div>
      </footer>
    </div>
  );
}
