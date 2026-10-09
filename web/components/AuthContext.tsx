'use client';

import { createContext, useContext, ReactNode } from 'react';

interface AuthContextType {
  isEditMode: boolean;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

/**
 * Public Forger dashboard is read-only. Remote edit unlock (?edit=...) and
 * mutate APIs are disabled — isEditMode is always false.
 */
export function AuthProvider({ children }: { children: ReactNode }) {
  return (
    <AuthContext.Provider value={{ isEditMode: false }}>
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
