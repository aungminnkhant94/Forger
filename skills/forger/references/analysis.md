# The Analysis Contract

Every bookmark gets judged against the user's `profile.md` — never against a
generic tech audience. You are writing for one person.

## User notes override everything

If the user pasted the link WITH their own words (`forge add --note`), those
words are the single strongest signal you have — they tell you why THIS person
cared enough to save THIS link right now. Judge through the note first, the
page content second, the profile third. A humble link with an excited note
outranks an impressive link with no note.

## The three questions

Answer these honestly; everything else derives from them:

1. **actionable_this_week** — can the user act on this TODAY or within 7 days,
   with concrete steps? Not "someday". THIS week.
2. **reduces_friction** — does it make something they're currently building
   faster, cheaper, easier, better? Does it remove a blocker?
3. **reference_material** — will they want to FIND this again later, even
   without acting now? (Docs, benchmarks, comparisons, guides.)

## Bucket mapping

| Bucket | Rule |
|---|---|
| `test_this_week` | actionable_this_week = true |
| `build_later` | not actionable AND reduces_friction = true |
| `archive` | neither, but reference_material = true |
| `ignore` | all three false |

Default when torn between two buckets: **the more urgent one.** Action beats
reference.

## Hard rule: do NOT park every on-profile paper in archive

Ban **"all science = archive"** (and the twin habit of filing every on-profile
paper as reference-only). On-profile is not enough reason to archive — ask the
three questions. `forge resolve` derives worth from the booleans (~8 / ~6.5 / ~4):

| Situation (biomed example) | Booleans / bucket | Worth |
|---|---|---|
| Protocol or assay the user can run **this week** (e.g. a PCR / ELISA protocol that matches their current wet-lab project and they can try Monday) | `actionable_this_week` → `test_this_week` | ~8 |
| Method that **unblocks current work** but is not this-week runnable (e.g. a sequencing library-prep method that removes a blocker on their pipeline) | `reduces_friction` → `build_later` | ~6.5 |
| Background landmark / review context only (classic paper they may cite later, no near-term action) | `reference_material` → `archive` | ~4 |

If two papers both feel like `archive`, pick the more urgent for **at least
one** — promote it to `build_later` (or `test_this_week` when it is runnable
this week). Action beats reference; current work beats landmarks.

**Batch spread — do not clump worth.** In a batch of on-profile papers, spread
buckets/worth. Two distinct papers must not share the exact same
`worth_score` unless they truly share the same boolean outcomes. Prefer
distinct actionable / reduces_friction / reference choices so worth lands on
different derived values (~8 / ~6.5 / ~4 / ~1.5). Filing nine papers as
`archive@4.0` is the failure mode this rule bans.

## Profile rules

- If the profile names always-relevant topics and this bookmark is one, bump UP.
- If the profile says actively-ignore and this is one, `ignore` — say so in the
  reason.
- `relates_to` is **required** (agent mode + `forge resolve`). Write 2–4
  sentences (≥40 characters) that name the user's actual goals/projects from
  `profile.md`. **Never** write `None`, `N/A`, `null`, `-`, or leave it empty —
  resolve will reject those placeholders. If nothing connects, still write
  real prose explaining the miss (e.g. why it sits outside their current
  projects) — a fake connection is worse than an honest miss, but a bare
  `None` is not allowed.

## Writing style

- `summary`: 3-4 sentences — what it is, core takeaway, why it matters to THIS
  user.
- `recommendation_reason`: ONE blunt sentence. "Not relevant: a general essay
  with zero connection to your Docker work." Good. "This could potentially be
  interesting for some users..." Bad.
- `key_insights`: 3-5 concrete takeaways grounded in the content, not fluff.
- `tags`: 2-6 specific tags. Never `general`. Prefer concrete over broad
  (`docker networking` beats `tech`).
- Never use fake personalization ("you should care because..."). Write like an
  intelligent operator talking to a colleague.

## Scoring derivation (what happens after you write the JSON)

`forge resolve` converts your three booleans into 0-10 scores automatically:
relevance 8/6/4/2, worth ~8 (actionable) / ~6.5 (reduces friction) / ~4
(reference) / ~1.5 (ignore), priority from worth − 0.3×effort. You control the
booleans and the bucket; the numbers follow. If the derived priority looks
wrong for a specific case, trust your bucket — the bucket is the product.
Do not force archive just to "look conservative" on science papers — that
starves worth at 4 when the paper deserved 8 or 6.5.

## JSON shape (strict)

```json
{
  "title": "Polished title, concise, no trailing dots",
  "summary": "...",
  "recommendation_reason": "...",
  "relates_to": "...",
  "key_insights": ["...", "..."],
  "tags": ["...", "..."],
  "actionable_this_week": false,
  "reduces_friction": false,
  "reference_material": false,
  "recommendation_bucket": "test_this_week|build_later|archive|ignore"
}
```

`summary`, `recommendation_bucket`, and `relates_to` are required. Write
valid JSON — no comments, no trailing commas. `relates_to` must be 2+
sentences of profile-grounded prose (not `None`/`N/A`).
