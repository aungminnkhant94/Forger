import Link from 'next/link';
import { ExternalLink, Calendar, User, Clock } from 'lucide-react';
import { BookmarkWithAnalysis, getBookmarkAgeDays, getEffectiveBucket, getEffectivePriority, getReadingTime } from '@/lib/data';

interface BookmarkCardProps {
  bookmark: BookmarkWithAnalysis;
}

const bucketClasses = {
  test_this_week: 'test',
  build_later: 'build',
  archive: 'archive',
  ignore: 'ignore',
};

const bucketLabels = {
  test_this_week: 'Test This Week',
  build_later: 'Build Later',
  archive: 'Archive',
  ignore: 'Ignore',
};

export function BookmarkCard({ bookmark }: BookmarkCardProps) {
  const analysis = bookmark.analysis;
  const bucket = getEffectiveBucket(analysis) || 'archive';
  const priority = getEffectivePriority(analysis);
  const ageDays = getBookmarkAgeDays(bookmark);

  // Only show reading time for X/Twitter posts (fully scraped)
  const isXPost = bookmark.source === 'x' || bookmark.url.includes('x.com') || bookmark.url.includes('twitter.com');
  const readingTime = isXPost ? getReadingTime(bookmark.text || '') : null;

  return (
    <article className="bookmark-card">
      <div className="card-header">
        <span className={`badge ${bucketClasses[bucket]}`}>
          {bucketLabels[bucket]}
        </span>

        {typeof priority === 'number' && (
          <span className="priority">
            Priority: <strong>{priority.toFixed(1)}</strong>
          </span>
        )}
      </div>

      <div className="card-title-row">
        <h3 className="card-title">
          <Link href={bookmark.url} target="_blank" rel="noopener noreferrer">
            {analysis?.title || bookmark.title}
            <ExternalLink size={16} className="external-icon" />
          </Link>
        </h3>
      </div>

      {analysis?.summary && (
        <p className="card-summary">
          {analysis.summary
            .replace(/\.{3,}$/, '')
            .replace(/\.$/, '')
            .trim()}
          .
        </p>
      )}

      {analysis?.recommendation_reason && (
        <p className="card-why">{analysis.recommendation_reason}</p>
      )}

      {analysis?.relates_to && (
        <div className="card-relates">
          <span className="relates-label">↳ Relates to you</span>
          <p>{analysis.relates_to}</p>
        </div>
      )}

      <div className="card-meta">
        {bookmark.author && (
          <span>
            <User size={14} />
            {bookmark.author}
          </span>
        )}
        <span>
          <Calendar size={14} />
          {new Date(bookmark.bookmarked_at).toLocaleDateString()}
        </span>

        {ageDays !== null && (
          <span>
            <Clock size={14} />
            {ageDays}d old
          </span>
        )}

        {readingTime && (
          <span>
            <Clock size={14} />
            {readingTime} min read
          </span>
        )}

        {analysis && typeof analysis.worth_score === 'number' && typeof analysis.effort_score === 'number' && (
          <span style={{ fontSize: '0.75rem' }}>
            Worth: {analysis.worth_score.toFixed(1)} |
            Effort: {analysis.effort_score.toFixed(1)}
          </span>
        )}
      </div>

      {bookmark.tags?.length > 0 && (
        <div className="tags">
          {bookmark.tags.map((tag) => (
            <span key={tag} className="tag">#{tag}</span>
          ))}
        </div>
      )}
    </article>
  );
}
