// TypeScript side of tests/fixtures/shared_cases/text_rules.json (Python side:
// tests/test_shared_cases.py). Compiles web/lib rule modules with the project's
// tsc into a temp dir, then checks every case with node:test.
import { execFileSync } from 'node:child_process';
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { tmpdir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { after, test } from 'node:test';
import assert from 'node:assert/strict';
import { fileURLToPath } from 'node:url';

const webDir = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const casesPath = resolve(webDir, '..', 'tests', 'fixtures', 'shared_cases', 'text_rules.json');
const outDir = mkdtempSync(join(tmpdir(), 'forger-shared-cases-'));
after(() => rmSync(outDir, { recursive: true, force: true }));

execFileSync(
  process.execPath,
  [
    join(webDir, 'node_modules', 'typescript', 'bin', 'tsc'),
    'lib/tags.ts', 'lib/search.ts', 'lib/truncate.ts',
    '--outDir', outDir, '--module', 'commonjs', '--target', 'es2020', '--skipLibCheck',
  ],
  { cwd: webDir, stdio: 'inherit' },
);
writeFileSync(join(outDir, 'package.json'), '{"type":"commonjs"}');

const require = createRequire(join(outDir, 'index.js'));
const { normalizeTag } = require('./tags.js');
const { searchQueryTerms, normalizeSearchText, searchTermStem, searchTermIn } = require('./search.js');
const { truncateAtWordBoundary } = require('./truncate.js');
const cases = JSON.parse(readFileSync(casesPath, 'utf8'));

for (const c of cases.normalize_tag) {
  test(`normalizeTag(${JSON.stringify(c.input)})`, () => assert.equal(normalizeTag(c.input), c.expected));
}
for (const c of cases.search_query_terms) {
  test(`searchQueryTerms(${JSON.stringify(c.input)})`, () => assert.deepEqual(searchQueryTerms(c.input), c.expected));
}
for (const c of cases.search_normalize) {
  test(`normalizeSearchText(${JSON.stringify(c.input)})`, () => assert.equal(normalizeSearchText(c.input), c.expected));
}
for (const c of cases.search_term_stem) {
  test(`searchTermStem(${JSON.stringify(c.input)})`, () => assert.equal(searchTermStem(c.input), c.expected));
}
for (const c of cases.truncate_at_word_boundary) {
  test(`truncateAtWordBoundary(${JSON.stringify(c.input)}, ${c.max_length})`, () =>
    assert.equal(truncateAtWordBoundary(c.input, c.max_length, c.ellipsis), c.expected));
}
for (const c of cases.search_term_in) {
  test(`searchTermIn(${JSON.stringify(c.term)}, ${JSON.stringify(c.value)})`, () =>
    assert.equal(searchTermIn(c.term, normalizeSearchText(c.value)), c.expected));
}

