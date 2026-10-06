'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { Home, BookOpen } from 'lucide-react';

const tabs = [
  { href: '/', label: 'Overview', icon: Home },
  { href: '/bookmarks', label: 'Bookmarks', icon: BookOpen },
];

export function LayoutTabs() {
  const pathname = usePathname();
  
  return (
    <nav className="nav">
      <ul className="nav-list">
        {tabs.map((tab) => {
          const isActive = pathname === tab.href;
          const Icon = tab.icon;
          
          return (
            <li key={tab.href}>
              <Link
                href={tab.href}
                className={`nav-link ${isActive ? 'active' : ''}`}
              >
                <Icon size={18} />
                <span>{tab.label}</span>
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}