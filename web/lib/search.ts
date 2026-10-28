// Shared text matching for dashboard search. Mirrors forger/search.py:
// case-insensitive; '-', '_' and '/' act as spaces; every whitespace-separated
// query word must appear somewhere in the fields (any order). A hyphen group with
// a 1-char piece stays one phrase ("C-H" -> "c h") so it can't match everything.
// Terms match whole tokens only (not substrings inside larger words): "roche"
// matches "Roche" but not "electrochemical". A term also matches by its light
// stem ("bidding" -> "bid" matches "bids"); stem matches are token-bounded too.

export function normalizeSearchText(text: string | null | undefined): string {
  if (!text) return '';
  return text.toLowerCase().replace(/[-_/\u2010-\u2015\u2212\ufe58\ufe63\uff0d]+/g, ' ').replace(/\s+/g, ' ').trim();
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

const SUFFIXES = ['ies', 'ing', 'ers', 'er', 'ed', 'es', 's'];

export function searchTermStem(term: string): string {
  if (term.includes(' ') || term.endsWith('ss')) return term;
  for (const suf of SUFFIXES) {
    if (term.endsWith(suf) && term.length - suf.length >= 3) {
      let stem = term.slice(0, -suf.length);
      if (suf === 'ies') return stem + 'y';
      if (stem.length >= 4 && stem[stem.length - 1] === stem[stem.length - 2] && !'aeiouls'.includes(stem[stem.length - 1])) {
        stem = stem.slice(0, -1);
      }
      return stem;
    }
  }
  return term;
}

const TOKEN_RE = /[a-z0-9]+/g;

/** Whole-token match (with light stemming). Mirrors forger.search.term_in. */
export function searchTermIn(term: string, value: string): boolean {
  if (!term || !value) return false;
  const tokens = value.match(TOKEN_RE) || [];
  if (tokens.length === 0) return false;
  if (term.includes(' ')) {
    const parts = term.split(' ').filter(Boolean);
    const n = parts.length;
    for (let i = 0; i <= tokens.length - n; i++) {
      if (parts.every((p, j) => tokens[i + j] === p)) return true;
    }
    return false;
  }
  const stem = searchTermStem(term);
  return tokens.some(tok => tok === term || searchTermStem(tok) === stem);
}

export function matchesSearchQuery(
  query: string,
  fields: Array<string | null | undefined>,
): boolean {
  const terms = searchQueryTerms(query);
  if (terms.length === 0) return true;
  const haystack = fields.map(normalizeSearchText).filter(Boolean).join(' | ');
  return terms.every(term => searchTermIn(term, haystack));
}
