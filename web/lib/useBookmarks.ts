'use client';

import { useState, useEffect, useCallback } from 'react';

// Types (copied from data.ts to avoid import issues)
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
  key_insights: string[];
  scoring_inputs: ScoringInputs;
  worth_score: number;
  effort_score: number;
  priority_score: number;
  recommendation_bucket: 'test_this_week' | 'build_later' | 'archive' | 'ignore';
  relates_to?: string;
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

export interface BookmarksData {
  bookmarks: Bookmark[];
  analysis: AnalysisResult[];
}

export interface UseBookmarksReturn {
  bookmarks: BookmarkWithAnalysis[];
  tags: string[];
  stats: {
    total: number;
    test_this_week: number;
    build_later: number;
    archive: number;
    ignore: number;
  };
  isLoading: boolean;
  error: string | null;
  refetch: () => void;
}


export function useBookmarks(): UseBookmarksReturn {
  const [bookmarks, setBookmarks] = useState<BookmarkWithAnalysis[]>([]);
  const [tags, setTags] = useState<string[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchData = useCallback(async () => {
    try {
      setIsLoading(true);
      setError(null);

      // Fetch both data files from local public directory
      const cacheBust = Date.now();
      const [bookmarksRes, analysisRes] = await Promise.all([
        fetch(`/data.json?ts=${cacheBust}`, { cache: 'no-store' }),
        fetch(`/analysis.json?ts=${cacheBust}`, { cache: 'no-store' }),
      ]);

      if (!bookmarksRes.ok) {
        throw new Error(`Failed to fetch data.json: ${bookmarksRes.status}`);
      }
      if (!analysisRes.ok) {
        throw new Error(`Failed to fetch analysis.json: ${analysisRes.status}`);
      }

      const [bookmarksData, analysisData] = await Promise.all([
        bookmarksRes.json(),
        analysisRes.json(),
      ]);

      // Validate data structure
      if (!Array.isArray(bookmarksData)) {
        throw new Error('data.json is not an array');
      }
      if (!Array.isArray(analysisData)) {
        throw new Error('analysis.json is not an array');
      }

      // Create analysis map
      const analysisMap = new Map<string, AnalysisResult>(
        analysisData.map((a: AnalysisResult) => [a.bookmark_id, a])
      );

      // Merge bookmarks with analysis
      const mergedBookmarks: BookmarkWithAnalysis[] = bookmarksData.map(
        (bookmark: Bookmark) => ({
          ...bookmark,
          analysis: analysisMap.get(bookmark.id) || null,
        })
      );

      // Sort by bookmarked_at desc
      mergedBookmarks.sort(
        (a, b) =>
          new Date(b.bookmarked_at).getTime() -
          new Date(a.bookmarked_at).getTime()
      );

      // Extract unique tags
      const tagSet = new Set<string>();
      bookmarksData.forEach((b: Bookmark) => {
        b.tags?.forEach((tag: string) => tagSet.add(tag));
      });
      const uniqueTags = Array.from(tagSet).sort();

      const getBucket = (analysis: AnalysisResult | null | undefined) =>
        analysis?.personalized_bucket || analysis?.recommendation_bucket;

      // Calculate stats
      const stats = {
        total: bookmarksData.length,
        test_this_week: mergedBookmarks.filter(
          (b) => getBucket(b.analysis) === 'test_this_week'
        ).length,
        build_later: mergedBookmarks.filter(
          (b) => getBucket(b.analysis) === 'build_later'
        ).length,
        archive: mergedBookmarks.filter(
          (b) => getBucket(b.analysis) === 'archive'
        ).length,
        ignore: mergedBookmarks.filter(
          (b) => getBucket(b.analysis) === 'ignore'
        ).length,
      };

      setBookmarks(mergedBookmarks);
      setTags(uniqueTags);

      // Store stats in a way that can be accessed
      (useBookmarks as any).cachedStats = stats;
    } catch (err) {
      const errorMessage =
        err instanceof Error ? err.message : 'Failed to fetch bookmarks';
      setError(errorMessage);
      console.error('Error fetching bookmarks:', err);
    } finally {
      setIsLoading(false);
    }
  }, []);

  // Initial fetch on mount - load once when page opens
  useEffect(() => {
    fetchData();
  }, [fetchData]);

  // Auto-refresh disabled - user controls refresh manually
  // useEffect(() => {
  //   const interval = setInterval(fetchData, REFRESH_INTERVAL);
  //   return () => clearInterval(interval);
  // }, [fetchData]);

  const stats = (useBookmarks as any).cachedStats || {
    total: 0,
    test_this_week: 0,
    build_later: 0,
    archive: 0,
    ignore: 0,
  };

  return {
    bookmarks,
    tags,
    stats,
    isLoading,
    error,
    refetch: fetchData,
  };
}
