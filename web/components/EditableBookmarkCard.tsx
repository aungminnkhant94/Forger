'use client';

import { useState } from 'react';
import Link from 'next/link';
import { ExternalLink, Calendar, User, Edit2, Check, X, Trash2, Move, Clock } from 'lucide-react';
import { BookmarkWithAnalysis, AnalysisResult, getBookmarkAgeDays, getEffectiveBucket, getEffectivePriority } from '@/lib/data';

interface EditableBookmarkCardProps {
  bookmark: BookmarkWithAnalysis;
  onUpdate: (id: string, updates: Partial<BookmarkWithAnalysis>) => void;
  onDelete: (id: string) => void;
  onMove: (id: string, newBucket: string) => void;
  isEditMode?: boolean;
}

interface BookmarkAnalysisUpdate {
  analysis: AnalysisResult | null;
}

const bucketColors = {
  test_this_week: 'test',
  build_later: 'build',
  archive: 'archive',
  ignore: 'ignore',
  pending: 'archive'
};

const bucketLabels = {
  test_this_week: 'Test This Week',
  build_later: 'Build Later',
  archive: 'Archive',
  ignore: 'Ignore',
  pending: 'Pending'
};

const allBuckets = ['test_this_week', 'build_later', 'archive', 'ignore'];

export function EditableBookmarkCard({ bookmark, onUpdate, onDelete, onMove, isEditMode = false }: EditableBookmarkCardProps) {
  const [isEditing, setIsEditing] = useState(false);
  const [editedNotes, setEditedNotes] = useState(bookmark.analysis?.personal_notes || '');
  const [showMoveMenu, setShowMoveMenu] = useState(false);

  const bucket = getEffectiveBucket(bookmark.analysis) || 'archive';
  const priority = getEffectivePriority(bookmark.analysis);
  const ageDays = getBookmarkAgeDays(bookmark);

  const handleSaveNotes = () => {
    if (!bookmark.analysis) {
      setIsEditing(false);
      return;
    }
    const updates: BookmarkAnalysisUpdate = {
      analysis: {
        ...bookmark.analysis,
        personal_notes: editedNotes
      }
    };
    onUpdate(bookmark.id, updates);
    setIsEditing(false);
  };

  const handleMove = (newBucket: string) => {
    onMove(bookmark.id, newBucket);
    setShowMoveMenu(false);
  };

  return (
    <article className="bookmark-card">
      <div className="card-header">
        <div style={{ flex: 1 }}>
          {/* Bucket badge with move option */}
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '8px' }}>
            <span className={`badge ${bucketColors[bucket as keyof typeof bucketColors]}`}>
              {bucketLabels[bucket as keyof typeof bucketLabels]}
            </span>

            {/* Move dropdown - only in edit mode */}
            {isEditMode && (
              <div style={{ position: 'relative' }}>
                <button 
                  onClick={() => setShowMoveMenu(!showMoveMenu)}
                  className="theme-toggle"
                  style={{ padding: '4px 8px', fontSize: '0.75rem' }}
                >
                  <Move size={12} /> Move
                </button>

                {showMoveMenu && (
                  <div style={{
                    position: 'absolute',
                    top: '100%',
                    left: 0,
                    background: 'var(--panel)',
                    border: '1px solid var(--line)',
                    borderRadius: '8px',
                    padding: '8px',
                    zIndex: 10,
                    minWidth: '150px'
                  }}>
                    {allBuckets.map(b => (
                      <button
                        key={b}
                        onClick={() => handleMove(b)}
                        style={{
                          display: 'block',
                          width: '100%',
                          padding: '6px 12px',
                          textAlign: 'left',
                          border: 'none',
                          background: b === bucket ? 'var(--panel-strong)' : 'transparent',
                          borderRadius: '4px',
                          cursor: 'pointer',
                          fontSize: '0.875rem'
                        }}
                      >
                        {bucketLabels[b as keyof typeof bucketLabels]}
                      </button>
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>

          {/* Title */}
          <h3 className="card-title">
            <Link href={bookmark.url} target="_blank" rel="noopener noreferrer">
              {bookmark.analysis?.title || bookmark.title}
              <ExternalLink size={16} className="external-icon" />
            </Link>
          </h3>
        </div>

        {/* Actions - only in edit mode */}
        {isEditMode && (
          <div style={{ display: 'flex', gap: '8px' }}>
            {!isEditing ? (
              <button
                onClick={() => setIsEditing(true)}
                className="theme-toggle"
                style={{ padding: '6px' }}
                title="Edit notes"
              >
                <Edit2 size={16} />
              </button>
            ) : (
              <>
                <button
                  onClick={handleSaveNotes}
                  className="theme-toggle"
                  style={{ padding: '6px', background: 'var(--good)', color: 'white' }}
                >
                  <Check size={16} />
                </button>
                <button
                  onClick={() => {setIsEditing(false); setEditedNotes(bookmark.analysis?.personal_notes || '');}}
                  className="theme-toggle"
                  style={{ padding: '6px' }}
                >
                  <X size={16} />
                </button>
              </>
            )}
            <button
              onClick={() => onDelete(bookmark.id)}
              className="theme-toggle"
              style={{ padding: '6px', color: 'var(--bad)' }}
              title="Delete"
            >
              <Trash2 size={16} />
            </button>
          </div>
        )}
      </div>

      {/* Summary */}
      {bookmark.analysis?.summary && (
        <p className="card-summary">{bookmark.analysis.summary}</p>
      )}

      {/* Personal Notes - Editable */}
      <div style={{ marginBottom: '16px' }}>
        {isEditing ? (
          <textarea
            value={editedNotes}
            onChange={(e) => setEditedNotes(e.target.value)}
            placeholder="Add your personal notes..."
            style={{
              width: '100%',
              minHeight: '80px',
              padding: '12px',
              border: '1px solid var(--accent)',
              borderRadius: '8px',
              background: 'var(--panel)',
              color: 'var(--ink)',
              fontFamily: 'inherit',
              fontSize: '0.875rem',
              resize: 'vertical'
            }}
          />
        ) : bookmark.analysis?.personal_notes ? (
          <div style={{
            padding: '12px',
            background: 'var(--panel-strong)',
            borderRadius: '8px',
            fontSize: '0.875rem'
          }}>
            <strong style={{ color: 'var(--accent)' }}>Your Notes:</strong>
            <p style={{ margin: '4px 0 0 0' }}>{bookmark.analysis.personal_notes}</p>
          </div>
        ) : null}
      </div>

      {/* Meta */}
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
        {typeof priority === 'number' && (
          <span style={{ fontSize: '0.75rem' }}>
            Priority: <strong>{priority.toFixed(1)}</strong>
          </span>
        )}
        {ageDays !== null && (
          <span style={{ fontSize: '0.75rem' }}>
            <Clock size={14} />
            {ageDays}d old
          </span>
        )}
      </div>

      {/* Tags */}
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