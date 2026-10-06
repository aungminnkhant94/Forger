'use client';

import { useState, useMemo } from 'react';
import Link from 'next/link';
import { StatCard } from '@/components/StatCard';
import { BookmarkCard } from '@/components/BookmarkCard';
import { SearchBar } from '@/components/SearchBar';
import { useBookmarks } from '@/lib/useBookmarks';
import { BookmarkWithAnalysis } from '@/lib/useBookmarks';

export default function OverviewPage() {
  const { bookmarks, stats, isLoading, error, refetch } = useBookmarks();
  const [searchQuery, setSearchQuery] = useState('');

  // Filter bookmarks by search
  const filteredBookmarks = useMemo(() => {
    let filtered = bookmarks;

    if (searchQuery.trim()) {
      const query = searchQuery.toLowerCase();
      filtered = bookmarks.filter((bookmark: BookmarkWithAnalysis) => {
        const searchableText = `
          ${bookmark.title} 
          ${bookmark.text} 
          ${bookmark.author || ''} 
          ${bookmark.analysis?.summary || ''}
          ${bookmark.analysis?.recommendation_reason || ''}
          ${bookmark.analysis?.key_insights?.join(' ') || ''}
          ${bookmark.tags?.join(' ') || ''}
        `.toLowerCase();

        return searchableText.includes(query);
      });
    }

    // Take top 10
    return filtered.slice(0, 10);
  }, [bookmarks, searchQuery]);

  // Loading state
  if (isLoading) {
    return (
      <div
        style={{
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          minHeight: '60vh',
          gap: '16px',
        }}
      >
        <div
          style={{
            width: '48px',
            height: '48px',
            border: '3px solid var(--border)',
            borderTop: '3px solid var(--accent)',
            borderRadius: '50%',
            animation: 'spin 1s linear infinite',
          }}
        />
        <p style={{ color: 'var(--text-muted)' }}>Loading bookmarks...</p>
        <style jsx>{`
          @keyframes spin {
            to {
              transform: rotate(360deg);
            }
          }
        `}</style>
      </div>
    );
  }

  // Error state
  if (error) {
    return (
      <div
        style={{
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          minHeight: '60vh',
          gap: '16px',
          padding: '24px',
        }}
      >
        <div
          style={{
            fontSize: '48px',
          }}
        >
          ⚠️
        </div>
        <h2 style={{ color: 'var(--text)' }}>Failed to load bookmarks</h2>
        <p
          style={{
            color: 'var(--text-muted)',
            textAlign: 'center',
            maxWidth: '400px',
          }}
        >
          {error}
        </p>
        <button
          onClick={() => window.location.reload()}
          style={{
            padding: '8px 16px',
            background: 'var(--accent)',
            color: 'white',
            border: 'none',
            borderRadius: '6px',
            cursor: 'pointer',
            marginTop: '8px',
          }}
        >
          Retry
        </button>
      </div>
    );
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '32px' }}>
      <section>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
          <h2 className="section-title">
            Dashboard
          </h2>
          <button
            onClick={refetch}
            disabled={isLoading}
            style={{
              padding: '6px 14px',
              background: 'var(--surface)',
              color: 'var(--text)',
              border: '1px solid var(--border)',
              borderRadius: '6px',
              cursor: 'pointer',
              fontSize: '0.875rem',
              opacity: isLoading ? 0.6 : 1,
            }}
          >
            {isLoading ? 'Loading...' : '↻ Refresh'}
          </button>
        </div>
        <div className="stats-grid">
          <StatCard label="Total Bookmarks" value={stats.total} color="gray" />
          <StatCard
            label="Test This Week"
            value={stats.test_this_week}
            color="green"
          />
          <StatCard
            label="Build Later"
            value={stats.build_later}
            color="orange"
          />
          <StatCard label="Archive" value={stats.archive} color="gray" />
          <StatCard label="Ignore" value={stats.ignore} color="gray" />
        </div>
      </section>

      <section>
        <div className="section-header">
          <h2 className="section-title">Recent Bookmarks</h2>
          <Link href="/bookmarks" className="view-all">
            View all →
          </Link>
        </div>

        <SearchBar
          value={searchQuery}
          onChange={setSearchQuery}
          placeholder="Search your bookmarks..."
        />
        <div className="bookmark-list">
          {filteredBookmarks.length > 0 ? (
            filteredBookmarks.map((bookmark) => (
              <BookmarkCard key={bookmark.id} bookmark={bookmark} />
            ))
          ) : (
            <div className="empty-state" style={{ textAlign: 'center', padding: '40px 0' }}>
              <p style={{ color: 'var(--text-muted)', marginBottom: '16px' }}>
                {bookmarks.length === 0 ? 'No bookmarks loaded yet.' : 'No bookmarks match your search.'}
              </p>
              {bookmarks.length === 0 && !searchQuery && (
                <button
                  onClick={refetch}
                  disabled={isLoading}
                  style={{
                    padding: '10px 20px',
                    background: 'var(--accent)',
                    color: 'white',
                    border: 'none',
                    borderRadius: '6px',
                    cursor: 'pointer',
                    fontSize: '1rem',
                    opacity: isLoading ? 0.6 : 1,
                  }}
                >
                  {isLoading ? 'Loading...' : 'Load Bookmarks'}
                </button>
              )}
            </div>
          )}
        </div>
      </section>
    </div>
  );
}
