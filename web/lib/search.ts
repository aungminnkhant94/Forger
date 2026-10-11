// Shared text matching for dashboard search. Mirrors forger/search.py:
// case-insensitive; '-', '_' and '/' act as spaces; every whitespace-separated
// query word must appear somewhere in the fields (any order). A hyphen group with
// a 1-char piece stays one phrase ("C-H" -> "c h") so it can't match everything.

export function normalizeSearchText(text: string | null | undefined): string {
  if (!text) return '';
  return text.toLowerCase().replace(/[-_/]+/g, ' ').replace(/\s+/g, ' ').trim();
}

export function searchQueryTerms(query: string): string[] {
  const terms: string[] = [];
  for (const part of (query || '').split(/\s+/)) {
    const pieces = normalizeSearchText(part).split(' ').filter(Boolean);
    if (pieces.length === 0) continue;
    if (pieces.length > 1 && pieces.some(p => p.length < 2)) {
      terms.push(pieces.join(' '));
    } else {
      terms.push(...pieces);
    }
  }
  return terms;
}

export function matchesSearchQuery(
  query: string,
  fields: Array<string | null | undefined>,
): boolean {
  const terms = searchQueryTerms(query);
  if (terms.length === 0) return true;
  const haystack = fields.map(normalizeSearchText).filter(Boolean).join(' | ');
  return terms.every(term => haystack.includes(term));
}
