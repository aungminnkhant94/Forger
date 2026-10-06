'use client';

import { useState } from 'react';
import Link from 'next/link';
import { StatCard } from '@/components/StatCard';
import { BookmarkCard } from '@/components/BookmarkCard';
import { BookmarkWithAnalysis } from '@/lib/data';

interface OverviewClientProps {
  initialStats: {
    total: number;
    test_this_week: number;
    build_later: number;
    archive: number;
    ignore: number;
  };
  initialBookmarks: BookmarkWithAnalysis[];
}

export default function OverviewClient({ initialStats, initialBookmarks }: OverviewClientProps) {
  const [loading] = useState(false);

  // Auto-fetch disabled - user controls refresh manually

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '32px' }}>
      <section>
        <h2 className="section-title" style={{ marginBottom: '16px' }}>
          Dashboard {loading && <span style={{ fontSize: '0.75rem', color: '#888' }}>(syncing...)</span>}
        </h2>
        <div className="stats-grid">
          <StatCard label="Total Bookmarks" value={initialStats.total} color="gray" />
          <StatCard label="Test This Week" value={initialStats.test_this_week} color="green" />
          <StatCard label="Build Later" value={initialStats.build_later} color="orange" />
          <StatCard label="Archive" value={initialStats.archive} color="gray" />
        </div>
      </section>

      <section>
        <div className="section-header">
          <h2 className="section-title">Recent Bookmarks</h2>
          <Link href="/bookmarks" className="view-all">
            View all →
          </Link>
        </div>
        
        <div className="bookmark-list">
          {initialBookmarks.length > 0 ? (
            initialBookmarks.map((bookmark) => (
              <BookmarkCard key={bookmark.id} bookmark={bookmark} />
            ))
          ) : (
            <div className="empty-state">
              <p>No bookmarks yet.</p>
              <p style={{ fontSize: '0.875rem', marginTop: '8px' }}>
                Save your first bookmark to see it here.
              </p>
            </div>
          )}
        </div>
      </section>
    </div>
  );
}
