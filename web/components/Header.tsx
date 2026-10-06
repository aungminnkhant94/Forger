'use client';

import { useAuth } from './AuthContext';
import { ThemeToggle } from './ThemeToggle';

export function Header() {
  const { isEditMode } = useAuth();

  return (
    <header className="header">
      <div className="header-left">
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
          <h1>RolloForge</h1>
          {isEditMode && (
            <span style={{
              background: 'var(--good)',
              color: 'white',
              padding: '4px 10px',
              borderRadius: '4px',
              fontSize: '0.75rem',
              fontWeight: 'bold',
              textTransform: 'uppercase'
            }}>
              Edit Mode
            </span>
          )}
        </div>
        <p>Bookmark intelligence for AI agents</p>
      </div>
      <ThemeToggle />
    </header>
  );
}