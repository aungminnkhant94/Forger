'use client';

import { createContext, useContext, useState, useEffect, ReactNode } from 'react';
import { useRouter } from 'next/navigation';

interface AuthContextType {
  isEditMode: boolean;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [isEditMode, setIsEditMode] = useState(false);
  const router = useRouter();

  useEffect(() => {
    async function initEditMode() {
      if (typeof window === 'undefined') return;

      const url = new URL(window.location.href);
      const editParam = url.searchParams.get('edit');

      if (editParam) {
        try {
          const res = await fetch('/api/auth/edit', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ key: editParam }),
          });

          if (res.ok) {
            url.searchParams.delete('edit');
            window.history.replaceState({}, '', url.toString());
            setIsEditMode(true);
            router.refresh();
            return;
          }
        } catch {
          // Ignore and fall back to existing cookie state.
        }
      }

      setIsEditMode(document.cookie.includes('rolloforge_edit=1'));
    }

    void initEditMode();
  }, [router]);

  return (
    <AuthContext.Provider value={{ isEditMode }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (context === undefined) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
}