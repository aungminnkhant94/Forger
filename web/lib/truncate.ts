// Word-boundary truncation (mirrors forger.analysis_cleanup).
// `forge sync` already truncates analysis.summary to CARD_SUMMARY_MAX_LENGTH
// in Python; cards display the exported summary as-is. This module remains
// for shared-cases parity (tests/fixtures/shared_cases/text_rules.json).

export const CARD_SUMMARY_MAX_LENGTH = 280;

/**
 * Truncate text to maxLength without splitting a word.
 * Returns the original string when it already fits. Otherwise cuts at the
 * last whitespace before the budget and appends an ellipsis.
 */
export function truncateAtWordBoundary(
  text: string,
  maxLength: number = CARD_SUMMARY_MAX_LENGTH,
  ellipsis: string = '…',
): string {
  const normalized = (text || '').replace(/\s+/g, ' ').trim();
  if (maxLength <= 0) return '';
  if (normalized.length <= maxLength) return normalized;

  const budget = maxLength - ellipsis.length;
  if (budget <= 0) return ellipsis.slice(0, maxLength);

  // Strip a trailing hard ellipsis from older mid-word cuts so we can
  // re-truncate cleanly at a real word boundary.
  let source = normalized.replace(/\.{2,}$/, '').replace(/…$/, '').trimEnd();
  if (source.length <= budget) {
    const lastSpace = source.lastIndexOf(' ');
    if (lastSpace > Math.floor(budget / 2)) {
      source = source.slice(0, lastSpace).trimEnd();
    }
    return source.replace(/[.,;:!?-]+$/u, '') + ellipsis;
  }

  let cut = source.slice(0, budget).trimEnd();
  const lastSpace = cut.lastIndexOf(' ');
  if (lastSpace > Math.floor(budget / 2)) {
    cut = cut.slice(0, lastSpace).trimEnd();
  }
  cut = cut.replace(/[.,;:!?-]+$/u, '');
  if (!cut) {
    cut = source.slice(0, budget).trimEnd();
  }
  return cut + ellipsis;
}
