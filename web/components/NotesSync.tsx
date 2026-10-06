'use client';

import { Download, Upload } from 'lucide-react';
import { useAuth } from './AuthContext';

export function NotesSync() {
  const { isEditMode } = useAuth();

  const handleExport = () => {
    const saved = localStorage.getItem('rolloforge_bookmarks');
    if (!saved) {
      alert('No notes to export');
      return;
    }
    
    const blob = new Blob([saved], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `rolloforge-notes-${new Date().toISOString().split('T')[0]}.json`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  };

  const handleImport = () => {
    const input = document.createElement('input');
    input.type = 'file';
    input.accept = '.json';
    input.onchange = (e) => {
      const file = (e.target as HTMLInputElement).files?.[0];
      if (!file) return;
      
      const reader = new FileReader();
      reader.onload = (event) => {
        try {
          const data = JSON.parse(event.target?.result as string);
          localStorage.setItem('rolloforge_bookmarks', JSON.stringify(data));
          alert('Notes imported! Refresh to see changes.');
          window.location.reload();
        } catch (err) {
          alert('Invalid JSON file');
        }
      };
      reader.readAsText(file);
    };
    input.click();
  };

  if (!isEditMode) return null;

  return (
    <div style={{
      display: 'flex',
      gap: '8px',
      marginBottom: '16px',
      padding: '12px',
      background: 'var(--panel)',
      borderRadius: '8px',
      border: '1px solid var(--line)'
    }}>
      <button
        onClick={handleExport}
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: '6px',
          padding: '8px 12px',
          background: 'var(--accent)',
          color: 'white',
          border: 'none',
          borderRadius: '6px',
          cursor: 'pointer',
          fontSize: '0.875rem'
        }}
      >
        <Download size={16} /> Export Notes
      </button>
      
      <button
        onClick={handleImport}
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: '6px',
          padding: '8px 12px',
          background: 'var(--panel-strong)',
          color: 'var(--ink)',
          border: '1px solid var(--line)',
          borderRadius: '6px',
          cursor: 'pointer',
          fontSize: '0.875rem'
        }}
      >
        <Upload size={16} /> Import Notes
      </button>
      
      <span style={{
        marginLeft: 'auto',
        fontSize: '0.75rem',
        color: 'var(--muted)',
        alignSelf: 'center'
      }}>
        Notes are stored locally per browser
      </span>
    </div>
  );
}