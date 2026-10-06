'use client';

import { useState, useEffect } from 'react';

interface SearchBarProps {
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
}

export function SearchBar({ value, onChange, placeholder = "Search bookmarks..." }: SearchBarProps) {
  const [inputValue, setInputValue] = useState(value);
  
  // Debounce search
  useEffect(() => {
    const timer = setTimeout(() => {
      onChange(inputValue);
    }, 300);
    return () => clearTimeout(timer);
  }, [inputValue, onChange]);
  
  return (
    <div className="search-container" style={{ marginBottom: '20px' }}>
      <div className="search-input-wrapper" style={{
        position: 'relative',
        display: 'flex',
        alignItems: 'center',
      }}>
        <svg 
          xmlns="http://www.w3.org/2000/svg" 
          width="18" 
          height="18" 
          viewBox="0 0 24 24" 
          fill="none" 
          stroke="currentColor" 
          strokeWidth="2" 
          strokeLinecap="round" 
          strokeLinejoin="round"
          style={{
            position: 'absolute',
            left: '12px',
            color: 'var(--muted)',
          }}
        >
          <circle cx="11" cy="11" r="8"></circle>
          <path d="m21 21-4.3-4.3"></path>
        </svg>
        
        <input
          type="text"
          value={inputValue}
          onChange={(e) => setInputValue(e.target.value)}
          placeholder={placeholder}
          className="search-input"
          style={{
            width: '100%',
            padding: '12px 12px 12px 40px',
            border: '1px solid var(--border)',
            borderRadius: '8px',
            background: 'var(--card-bg)',
            color: 'var(--text)',
            fontSize: '0.875rem',
          }}
        />
        
        {inputValue && (
          <button
            onClick={() => {
              setInputValue('');
              onChange('');
            }}
            style={{
              position: 'absolute',
              right: '12px',
              background: 'none',
              border: 'none',
              cursor: 'pointer',
              color: 'var(--muted)',
              padding: '4px',
            }}
          >
            ✕
          </button>
        )}
      </div>
    </div>
  );
}
