// Types
export interface Bookmark {
  id: string;
  title: string;
  source: string;
  url: string;
  text: string;
  author: string | null;
  created_at: string;
  bookmarked_at: string;
  tags: string[];
  bucket?: string;
}

export interface ScoringInputs {
  relevance: number;
  practical_value: number;
  actionability: number;
  stage_fit: number;
  novelty: number;
  excitement: number;
  difficulty: number;
  time_cost: number;
}

export interface AnalysisResult {
  bookmark_id: string;
  title?: string;
  summary: string;
  recommendation_reason: string;
  relates_to?: string;
  key_insights: string[];
  scoring_inputs: ScoringInputs;
  worth_score: number;
  effort_score: number;
  priority_score: number;
  recommendation_bucket: 'test_this_week' | 'build_later' | 'archive' | 'ignore';
  personalized_bucket?: 'test_this_week' | 'build_later' | 'archive' | 'ignore';
  personalized_priority_score?: number;
  analysis_source: string;
  analyzed_at: string;
  personal_notes?: string;
  pinned?: boolean;
  pinned_reason?: string;
  decayed_at?: string;
  decayed_from_bucket?: 'test_this_week' | 'build_later' | 'archive' | 'ignore';
  decay_reason?: string;
}

export interface BookmarkWithAnalysis extends Bookmark {
  analysis: AnalysisResult | null;
}

// NOTE: Static imports removed - data is now fetched client-side via useBookmarks hook
// import bookmarksData from './data.json';
// import analysisData from './analysis.json';

// Types remain exported for backward compatibility

// NOTE: These utility functions now require data to be passed in.
// Use the useBookmarks hook for client-side data fetching.

export function getBookmarksWithAnalysis(
  bookmarks: Bookmark[],
  analysisResults: AnalysisResult[]
): BookmarkWithAnalysis[] {
  const analysisMap = new Map(analysisResults.map(a => [a.bookmark_id, a]));
  return bookmarks
    .map(bookmark => ({
      ...bookmark,
      analysis: analysisMap.get(bookmark.id) || null,
    }))
    .sort((a, b) => new Date(b.bookmarked_at).getTime() - new Date(a.bookmarked_at).getTime());
}

export function getEffectiveBucket(
  analysis: AnalysisResult | null | undefined
): AnalysisResult['recommendation_bucket'] | undefined {
  return analysis?.personalized_bucket || analysis?.recommendation_bucket;
}

export function getEffectivePriority(
  analysis: AnalysisResult | null | undefined
): number | undefined {
  return analysis?.personalized_priority_score ?? analysis?.priority_score;
}

export function getBookmarkAgeDays(bookmark: Pick<Bookmark, 'bookmarked_at' | 'created_at'>): number | null {
  const rawDate = bookmark.bookmarked_at || bookmark.created_at;
  if (!rawDate) return null;
  const ts = new Date(rawDate).getTime();
  if (Number.isNaN(ts)) return null;
  return Math.max(0, Math.floor((Date.now() - ts) / (1000 * 60 * 60 * 24)));
}

export function getStats(bookmarks: Bookmark[], analysisResults: AnalysisResult[]) {
  const withAnalysis = getBookmarksWithAnalysis(bookmarks, analysisResults);
  return {
    total: bookmarks.length,
    test_this_week: withAnalysis.filter(b => getEffectiveBucket(b.analysis) === 'test_this_week').length,
    build_later: withAnalysis.filter(b => getEffectiveBucket(b.analysis) === 'build_later').length,
    archive: withAnalysis.filter(b => getEffectiveBucket(b.analysis) === 'archive').length,
    ignore: withAnalysis.filter(b => getEffectiveBucket(b.analysis) === 'ignore').length,
  };
}

export function getRecentBookmarks(
  bookmarks: Bookmark[],
  analysisResults: AnalysisResult[],
  limit: number = 5
): BookmarkWithAnalysis[] {
  return getBookmarksWithAnalysis(bookmarks, analysisResults)
    .sort((a, b) => new Date(b.bookmarked_at).getTime() - new Date(a.bookmarked_at).getTime())
    .slice(0, limit);
}

export function getBookmarksByBucket(
  bucket: string,
  bookmarks: Bookmark[],
  analysisResults: AnalysisResult[]
): BookmarkWithAnalysis[] {
  return getBookmarksWithAnalysis(bookmarks, analysisResults).filter(
    b => getEffectiveBucket(b.analysis) === bucket
  );
}

export function getAllTags(bookmarks: Bookmark[]): string[] {
  const tagSet = new Set<string>();
  bookmarks.forEach(b => b.tags?.forEach(tag => tagSet.add(tag)));
  return Array.from(tagSet).sort();
}

// Full-text search across all bookmark fields
export function searchBookmarks(
  query: string,
  bookmarks: Bookmark[],
  analysisResults: AnalysisResult[]
): BookmarkWithAnalysis[] {
  if (!query.trim()) {
    return getBookmarksWithAnalysis(bookmarks, analysisResults);
  }
  
  const searchTerm = query.toLowerCase();
  const allBookmarks = getBookmarksWithAnalysis(bookmarks, analysisResults);
  
  return allBookmarks.filter(bookmark => {
    const searchableFields = [
      bookmark.title,
      bookmark.text,
      bookmark.author,
      bookmark.tags?.join(' '),
      bookmark.analysis?.summary,
      bookmark.analysis?.recommendation_reason,
      bookmark.analysis?.key_insights?.join(' '),
    ].filter(Boolean).join(' ').toLowerCase();
    
    return searchableFields.includes(searchTerm);
  });
}

// Advanced search with filters
export function advancedSearch({
  query,
  bucket,
  tags,
  bookmarks,
  analysisResults,
}: {
  query?: string;
  bucket?: string;
  tags?: string[];
  bookmarks: Bookmark[];
  analysisResults: AnalysisResult[];
}): BookmarkWithAnalysis[] {
  let results = getBookmarksWithAnalysis(bookmarks, analysisResults);
  
  // Text search
  if (query?.trim()) {
    const searchTerm = query.toLowerCase();
    results = results.filter(bookmark => {
      const searchableFields = [
        bookmark.title,
        bookmark.text,
        bookmark.author,
        bookmark.tags?.join(' '),
        bookmark.analysis?.summary,
        bookmark.analysis?.recommendation_reason,
        bookmark.analysis?.key_insights?.join(' '),
      ].filter(Boolean).join(' ').toLowerCase();
      
      return searchableFields.includes(searchTerm);
    });
  }
  
  // Bucket filter
  if (bucket && bucket !== 'all') {
    results = results.filter(
      b => getEffectiveBucket(b.analysis) === bucket
    );
  }
  
  // Tags filter
  if (tags && tags.length > 0) {
    results = results.filter(b => 
      tags.some(tag => b.tags?.includes(tag))
    );
  }
  
  return results;
}

// Calculate reading time (average 200 words per minute)
export function getReadingTime(text: string): number {
  if (!text) return 1;
  const wordCount = text.split(/\s+/).length;
  const minutes = Math.ceil(wordCount / 200);
  return Math.max(1, minutes); // Minimum 1 minute
}
