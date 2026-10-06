'use client';

import { useState, useMemo } from 'react';
import { FilterSidebar } from './FilterSidebar';
import { SearchBar } from './SearchBar';
import { BookmarkList } from './BookmarkList';
import { NotesSync } from './NotesSync';
import { useAuth } from './AuthContext';
import { BookmarkWithAnalysis, getEffectiveBucket } from '@/lib/data';

interface BookmarksContentProps {
  allBookmarks: BookmarkWithAnalysis[];
  allTags: string[];
  onRefresh?: () => void;
  isRefreshing?: boolean;
}

export function BookmarksContent({ allBookmarks, allTags, onRefresh, isRefreshing }: BookmarksContentProps) {
  const { isEditMode } = useAuth();
  const [selectedBucket, setSelectedBucket] = useState('all');
  const [selectedTags, setSelectedTags] = useState<string[]>([]);
  const [searchQuery, setSearchQuery] = useState('');
  
  const filteredBookmarks = useMemo(() => {
    return allBookmarks
      .filter((bookmark) => {
        // Bucket filter
        if (selectedBucket !== 'all') {
          if (getEffectiveBucket(bookmark.analysis) !== selectedBucket) {
            return false;
          }
        }
        
        // Tag filter
        if (selectedTags.length > 0) {
          const hasSelectedTag = selectedTags.some(tag => 
            bookmark.tags?.includes(tag)
          );
          if (!hasSelectedTag) return false;
        }
        
        // Search filter - full text search
        if (searchQuery.trim()) {
          const query = searchQuery.toLowerCase();
          const searchableText = `
            ${bookmark.title} 
            ${bookmark.text} 
            ${bookmark.author || ''} 
            ${bookmark.analysis?.summary || ''}
            ${bookmark.analysis?.recommendation_reason || ''}
            ${bookmark.analysis?.key_insights?.join(' ') || ''}
            ${bookmark.tags?.join(' ') || ''}
          `.toLowerCase();
          
          if (!searchableText.includes(query)) {
            return false;
          }
        }
        
        return true;
      })
      .sort((a, b) => new Date(b.bookmarked_at).getTime() - new Date(a.bookmarked_at).getTime());
  }, [allBookmarks, selectedBucket, selectedTags, searchQuery]);
  
  const handleTagChange = (tag: string) => {
    setSelectedTags(prev => 
      prev.includes(tag) 
        ? prev.filter(t => t !== tag)
        : [...prev, tag]
    );
  };

  return (
    <div className="filter-layout">
      <FilterSidebar
        availableTags={allTags}
        selectedBucket={selectedBucket}
        onBucketChange={setSelectedBucket}
        selectedTags={selectedTags}
        onTagChange={handleTagChange}
        bookmarks={allBookmarks}
      />
      
      <div>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
          <SearchBar 
            value={searchQuery} 
            onChange={setSearchQuery}
            placeholder="Search titles, content, summaries, tags..."
          />
          {onRefresh && (
            <button
              onClick={onRefresh}
              disabled={isRefreshing}
              style={{
                padding: '6px 14px',
                background: 'var(--surface)',
                color: 'var(--text)',
                border: '1px solid var(--border)',
                borderRadius: '6px',
                cursor: 'pointer',
                fontSize: '0.875rem',
                opacity: isRefreshing ? 0.6 : 1,
                marginLeft: '8px',
                whiteSpace: 'nowrap',
              }}
            >
              {isRefreshing ? 'Loading...' : '↻ Refresh'}
            </button>
          )}
        </div>
        <NotesSync />

        {isEditMode && (
          <div style={{
            marginBottom: '12px',
            padding: '10px 12px',
            background: 'rgba(34, 197, 94, 0.12)',
            border: '1px solid rgba(34, 197, 94, 0.35)',
            color: 'var(--text)',
            borderRadius: '8px',
            fontSize: '0.9rem'
          }}>
            Edit mode is on — delete, move, and notes controls are enabled.
          </div>
        )}
        
        <BookmarkList bookmarks={filteredBookmarks} />
      </div>
    </div>
  );
}
