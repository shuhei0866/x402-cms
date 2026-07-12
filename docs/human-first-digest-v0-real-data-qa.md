# Human-first Digest v0 — real-data QA

Date: 2026-07-12  
Branch: `codex/human-first-digest-v0`

## Environment

- Production Cloud Run revision `x402-cms-00015-5hm`
- Production Firestore project `my-utilities-490202`
- W19–W28 week-level commentary published through the vault sync path
- Desktop viewport and 390 × 844 mobile viewport

## Data inventory

| Week | Has source content | Week-level publication |
|---|---:|---|
| 2026-W18 | No | — |
| 2026-W19–W28 | Yes | Exactly one published edition per week |

The latest raw digest and the latest editorially published edition are both
W28. The archive contains ten consecutive editorial editions from W19 through
W28.

## Results

| Scenario | Result |
|---|---|
| Browser `/` | 200 HTML; latest published edition shown |
| Browser `/archive` | 200 HTML; ten editions from W28 through W19 listed newest first |
| Archive → W28 navigation | Passed |
| Browser `/digest/2026-W19` through `/digest/2026-W28` | All returned 200 HTML with editorial titles |
| Browser `/digest/2026-W28` | 200 HTML; published title, commentary, sources, and calendar range shown |
| Browser `/digest/2026-W18` | 404 HTML; latest and archive recovery links shown |
| Japanese → English toggle | Passed; locale and URL persisted |
| Mobile home/archive/digest | No horizontal overflow at 390 px |
| Browser console | No errors or warnings |
| Agent `/` | 200 JSON |
| Agent `/archive` | 200 JSON |
| Agent `/digest/2026-W28` without payment | 402 JSON |

The production smoke test after deployment confirmed browser 200 responses for
home, archive, W19, and W28; a browser 404 for empty W18; an agent 200 response
for `/`; and an agent 402 response for W28 without payment.

Observed local response times against production Firestore were approximately
0.7–2.1 seconds for the tested human routes. This is acceptable for functional
QA, but should be measured after deployment before adding caching.

## Publication backfill status

The W19–W28 publication backfill is complete. Every source week intended for
the initial archive now has exactly one published week-level commentary.

Do not silently promote raw source weeks into published editions. That would
undo the product decision that the archive represents editorial publication,
not merely successful ingestion.

## Non-blocking observation

`/favicon.ico` returns 404. This does not affect the release behavior and can be
handled separately.
