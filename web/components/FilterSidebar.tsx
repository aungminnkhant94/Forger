'use client';

import { BookmarkWithAnalysis } from '@/lib/data';

interface FilterSidebarProps {
  selectedBucket: string;
  onBucketChange: (bucket: string) => void;
  selectedTags: string[];
  onTagChange: (tag: string) => void;
  availableTags: string[];
  bookmarks: BookmarkWithAnalysis[];
}

const buckets = [
  { id: 'all', label: 'All Bookmarks', color: 'all' },
  { id: 'test_this_week', label: 'Test This Week', color: 'test' },
  { id: 'build_later', label: 'Build Later', color: 'build' },
  { id: 'archive', label: 'Archive', color: 'archive' },
  { id: 'ignore', label: 'Ignore', color: 'ignore' },
];

export function FilterSidebar({
  selectedBucket,
  onBucketChange,
  selectedTags,
  onTagChange,
  availableTags,
  bookmarks,
}: FilterSidebarProps) {
  const getBucket = (bookmark: BookmarkWithAnalysis) =>
    bookmark.analysis?.personalized_bucket || bookmark.analysis?.recommendation_bucket;

  const getCount = (bucketId: string) => {
    if (bucketId === 'all') return bookmarks.length;
    return bookmarks.filter(b => getBucket(b) === bucketId).length;
  };

  return (
    <aside>
      <div className="filter-section">
        <h3 className="filter-title">Buckets</h3>
        <ul className="filter-list">
          {buckets.map((bucket) => (
            <li key={bucket.id} className="filter-item">
              <button
                onClick={() => onBucketChange(bucket.id)}
                className={`filter-button ${selectedBucket === bucket.id ? 'active' : ''}`}
              >
                <span className="filter-left">
                  <span className={`color-dot ${bucket.color}`} />
                  {bucket.label}
                </span>
                <span style={{ color: '#68624e', fontSize: '0.875rem' }}>{getCount(bucket.id)}</span>
              </button>
            </li>
          ))}
        </ul>
      </div>
      
      {availableTags.length > 0 && (
        <div className="filter-section">
          <h3 className="filter-title">Tags</h3>
          <div className="tag-buttons">
            {availableTags.map((tag) => (
              <button
                key={tag}
                onClick={() => onTagChange(tag)}
                className={`tag-button ${selectedTags.includes(tag) ? 'active' : ''}`}
              >
                #{tag}
              </button>
            ))}
          </div>
        </div>
      )}
    </aside>
  );
}