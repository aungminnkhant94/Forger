// Canonical tag form, mirrors forger/tagging.py normalize_tag:
// lowercase kebab-case, so "Machine Learning" / "machine_learning" -> "machine-learning".
export function normalizeTag(tag: string | null | undefined): string {
  return String(tag ?? '')
    .trim()
    .toLowerCase()
    .replace(/^#+/, '')
    .trim()
    .replace(/[\s_-]+/g, '-')
    .replace(/^-+|-+$/g, '');
}

export function hasTag(tags: string[] | null | undefined, tag: string): boolean {
  const want = normalizeTag(tag);
  return !!want && (tags ?? []).some(t => normalizeTag(t) === want);
}
