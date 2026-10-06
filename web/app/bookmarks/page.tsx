'use client';

import { BookmarksContent } from '@/components/BookmarksContent';
import { useBookmarks } from '@/lib/useBookmarks';

export default function BookmarksPage() {
  const { bookmarks, tags, isLoading, error, refetch } = useBookmarks();

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
        <div style={{ fontSize: '48px' }}>⚠️</div>
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
    <>
      {bookmarks.length === 0 && !isLoading && !error && (
        <div style={{
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          minHeight: '60vh',
          gap: '16px',
        }}>
          <p style={{ color: 'var(--text-muted)' }}>No bookmarks loaded yet.</p>
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
        </div>
      )}
      {(bookmarks.length > 0 || isLoading || error) && <BookmarksContent allBookmarks={bookmarks} allTags={tags} onRefresh={refetch} isRefreshing={isLoading} />}
    </>
  );
}
