'use client';

import { useState, useEffect } from 'react';
import { EditableBookmarkCard } from './EditableBookmarkCard';
import { BookmarkWithAnalysis, AnalysisResult } from '@/lib/data';
import { useAuth } from './AuthContext';

interface BookmarkListProps {
  bookmarks: BookmarkWithAnalysis[];
}

interface SavedBookmarkData {
  analysis?: Partial<AnalysisResult>;
}

export function BookmarkList({ bookmarks }: BookmarkListProps) {
  const { isEditMode } = useAuth();
  const [localBookmarks, setLocalBookmarks] = useState<BookmarkWithAnalysis[]>(bookmarks);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  
  // Update local state when props change
  useEffect(() => {
    setLocalBookmarks(bookmarks);
  }, [bookmarks]);
  
  // Load from localStorage on mount
  useEffect(() => {
    const saved = localStorage.getItem('rolloforge_bookmarks');
    if (saved) {
      try {
        const parsed = JSON.parse(saved) as Record<string, SavedBookmarkData>;
        // Merge saved data with current bookmarks
        setLocalBookmarks(prev =>
          prev.map(bm => {
            const savedBookmark = parsed[bm.id];
            if (!savedBookmark?.analysis || !bm.analysis) return bm;
            return {
              ...bm,
              analysis: {
                ...bm.analysis,
                ...savedBookmark.analysis
              }
            };
          })
        );
      } catch (e) {
        console.error('Failed to load saved bookmarks', e);
      }
    }
  }, []);
  
  // Save to localStorage when bookmarks change
  useEffect(() => {
    const toSave: Record<string, SavedBookmarkData> = {};
    localBookmarks.forEach(bm => {
      if (bm.analysis?.personal_notes || bm.analysis?.recommendation_bucket || bm.analysis?.personalized_bucket) {
        toSave[bm.id] = {
          analysis: {
            personal_notes: bm.analysis.personal_notes,
            recommendation_bucket: bm.analysis.recommendation_bucket,
            personalized_bucket: bm.analysis.personalized_bucket,
            priority_score: bm.analysis.priority_score
          }
        };
      }
    });
    localStorage.setItem('rolloforge_bookmarks', JSON.stringify(toSave));
  }, [localBookmarks]);
  
  const handleUpdate = (id: string, updates: Partial<BookmarkWithAnalysis>) => {
    setLocalBookmarks(prev => 
      prev.map(bm => 
        bm.id === id ? { ...bm, ...updates } : bm
      )
    );
  };
  
  const handleDelete = async (id: string) => {
    if (!confirm('Delete this bookmark? This cannot be undone.')) return;
    
    try {
      const res = await fetch(`/api/bookmarks/${id}`, {
        method: 'DELETE',
      });
      if (res.ok) {
        setLocalBookmarks(prev => prev.filter(bm => bm.id !== id));
      } else {
        const err = await res.json();
        alert(`Delete failed: ${err.error || 'unknown error'}`);
      }
    } catch (e) {
      alert(`Delete failed: API unreachable. Is the delete server running?`);
    }
  };
  
  const handleMove = (id: string, newBucket: string) => {
    setLocalBookmarks(prev =>
      prev.map(bm => {
        if (bm.id !== id) return bm;
        if (!bm.analysis) return bm;
        return {
          ...bm,
          analysis: {
            ...bm.analysis,
            recommendation_bucket: newBucket as AnalysisResult['recommendation_bucket'],
            personalized_bucket: newBucket as AnalysisResult['recommendation_bucket']
          }
        };
      })
    );
  };
  
  const handleSelect = (id: string) => {
    setSelectedIds(prev => {
      const newSet = new Set(prev);
      if (newSet.has(id)) {
        newSet.delete(id);
      } else {
        newSet.add(id);
      }
      return newSet;
    });
  };
  
  const handleBulkMove = (newBucket: string) => {
    setLocalBookmarks(prev =>
      prev.map(bm => {
        if (!selectedIds.has(bm.id)) return bm;
        if (!bm.analysis) return bm;
        return {
          ...bm,
          analysis: {
            ...bm.analysis,
            recommendation_bucket: newBucket as AnalysisResult['recommendation_bucket'],
            personalized_bucket: newBucket as AnalysisResult['recommendation_bucket']
          }
        };
      })
    );
    setSelectedIds(new Set());
  };
  
  const handleBulkDelete = async () => {
    if (!confirm(`Delete ${selectedIds.size} bookmarks? This cannot be undone.`)) return;
    
    let failed = 0;
    for (const id of selectedIds) {
      try {
        const res = await fetch(`/api/bookmarks/${id}`, {
          method: 'DELETE',
        });
        if (res.ok) {
          setLocalBookmarks(prev => prev.filter(bm => bm.id !== id));
        } else {
          failed++;
        }
      } catch {
        failed++;
      }
    }
    setSelectedIds(new Set());
    if (failed > 0) alert(`${failed} deletions failed.`);
  };

  return (
    <>
      {/* Bulk actions bar - only in edit mode */}
      {isEditMode && selectedIds.size > 0 && (
        <div style={{
          background: 'var(--accent)',
          color: 'white',
          padding: '12px 16px',
          borderRadius: '8px',
          marginBottom: '16px',
          display: 'flex',
          alignItems: 'center',
          gap: '12px'
        }}>
          <span>{selectedIds.size} selected</span>
          
          <button 
            onClick={() => handleBulkMove('test_this_week')}
            style={{
              padding: '6px 12px',
              background: 'white',
              color: 'var(--accent)',
              border: 'none',
              borderRadius: '4px',
              cursor: 'pointer',
              fontSize: '0.875rem'
            }}
          >
            Move to Test
          </button>
          <button 
            onClick={() => handleBulkMove('archive')}
            style={{
              padding: '6px 12px',
              background: 'white',
              color: 'var(--accent)',
              border: 'none',
              borderRadius: '4px',
              cursor: 'pointer',
              fontSize: '0.875rem'
            }}
          >
            Move to Archive
          </button>
          <button 
            onClick={handleBulkDelete}
            style={{
              padding: '6px 12px',
              background: 'var(--bad)',
              color: 'white',
              border: 'none',
              borderRadius: '4px',
              cursor: 'pointer',
              fontSize: '0.875rem'
            }}
          >
            Delete
          </button>
          <button 
            onClick={() => setSelectedIds(new Set())}
            style={{
              padding: '6px 12px',
              background: 'transparent',
              color: 'white',
              border: '1px solid white',
              borderRadius: '4px',
              cursor: 'pointer',
              fontSize: '0.875rem'
            }}
          >
            Clear
          </button>
        </div>
      )}
      
      <div className="results-count">
        Showing {localBookmarks.length} bookmarks
        {isEditMode && selectedIds.size > 0 && ` (${selectedIds.size} selected)`}
      </div>
      
      <div className="bookmark-list">
        {localBookmarks.length > 0 ? (
          localBookmarks.map((bookmark) => (
            <div key={bookmark.id} style={{ display: 'flex', gap: '12px', alignItems: 'flex-start' }}>
              {/* Checkbox only in edit mode */}
              {isEditMode && (
                <input
                  type="checkbox"
                  checked={selectedIds.has(bookmark.id)}
                  onChange={() => handleSelect(bookmark.id)}
                  style={{
                    marginTop: '20px',
                    width: '18px',
                    height: '18px',
                    cursor: 'pointer'
                  }}
                />
              )}
              <div style={{ flex: 1 }}>
                <EditableBookmarkCard
                  bookmark={bookmark}
                  onUpdate={handleUpdate}
                  onDelete={handleDelete}
                  onMove={handleMove}
                  isEditMode={isEditMode}
                />
              </div>
            </div>
          ))
        ) : (
          <div className="empty-state">
            <p>No bookmarks match your filters.</p>
          </div>
        )}
      </div>
    </>
  );
}