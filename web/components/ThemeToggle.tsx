'use client';

import { useState, useEffect } from 'react';
import { Moon, Sun } from 'lucide-react';

export function ThemeToggle() {
  const [isDark, setIsDark] = useState(false);
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
    // Check localStorage or system preference
    const saved = localStorage.getItem('theme');
    const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
    const shouldBeDark = saved === 'dark' || (!saved && prefersDark);
    
    setIsDark(shouldBeDark);
    document.documentElement.setAttribute('data-theme', shouldBeDark ? 'dark' : 'light');
  }, []);

  const toggle = () => {
    const newTheme = !isDark;
    setIsDark(newTheme);
    document.documentElement.setAttribute('data-theme', newTheme ? 'dark' : 'light');
    localStorage.setItem('theme', newTheme ? 'dark' : 'light');
  };

  if (!mounted) {
    return (
      <button className="theme-toggle" aria-label="Toggle theme">
        <Sun size={16} />
        <span>Light</span>
      </button>
    );
  }

  return (
    <button onClick={toggle} className="theme-toggle" aria-label="Toggle theme">
      {isDark ? <Moon size={16} /> : <Sun size={16} />}
      <span>{isDark ? 'Dark' : 'Light'}</span>
    </button>
  );
}