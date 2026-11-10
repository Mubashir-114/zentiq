import React, { useState } from 'react';
import { Header } from './Header';
import { Sidebar } from './Sidebar';

interface ShellProps {
  children: React.ReactNode;
  isHealthy?: boolean | null;
}

export function Shell({ children, isHealthy = null }: ShellProps) {
  const [sidebarOpen, setSidebarOpen] = useState(false);

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

      <footer className="border-t border-white/5 bg-[#10121E] py-4 px-6 text-center text-xs text-[#9298AD]">
        <div className="flex flex-col sm:flex-row items-center justify-between max-w-6xl mx-auto gap-2">
          <span>&copy; 2026 ZENTIQ. Level Up Your Mind.</span>
          <div className="flex items-center gap-4 text-[11px] font-mono">
            <span>MySQL 8.4</span>
            <span>&bull;</span>
            <span>Django 6.0</span>
            <span>&bull;</span>
            <span>React 19</span>
          </div>
        </div>
      </footer>
    </div>
  );
}

