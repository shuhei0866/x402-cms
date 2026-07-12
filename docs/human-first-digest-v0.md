# Human-first Digest v0

## Goal

Make the weekly digest useful as a Japanese x402 editorial product before
expanding the paid agent projection. The release improves discovery and
reading without changing payment settlement or the agent JSON schema.

## Product boundary

- `x402-cms` owns collection, editorial judgment, publication, and human/agent
  projections.
- `x-402-contents-manager` remains the future boundary for offers, payment,
  entitlement, and feedback.
- User-Agent dispatch is routing convenience, not a confidentiality boundary.

## Publication rule

A week-level published commentary is the v0 publication record for an
editorial edition. Per-item notes may enrich an edition but do not publish one
by themselves. The publisher must reject more than one published week-level
commentary for the same week.

Raw source rows remain readable through the existing direct digest route for
backward compatibility. Home, archive, and generated previous/next links only
surface editorially published editions.

## Human experience

- `/` shows the latest published edition and recent editions to browsers; the
  existing machine-readable service description remains for non-browser calls.
- `/archive` lists published editions newest first.
- `/digest/{week}` leads with the editorial title and calendar date range. The
  ISO week label is secondary metadata.
- Previous/next navigation follows actual published editions and skips gaps.
- An entirely empty direct week returns a human 404 with links to the latest
  edition and archive. Agent payment behavior remains unchanged in this release.

## Editorial voice

Attention should come from the angle, not from friendliness or forceful
conclusions. Headlines surface the unresolved point. Body commentary follows
observation, meaning, and implication, and stops one sentence earlier than a
promotional version would.

The production prompt is private. The public repository carries only a
generalised example and review checklist.

## Acceptance criteria

- Published editions are derived from one canonical publication rule.
- Calendar dates are readable without understanding ISO week numbers.
- Navigation never links to an unpublished gap.
- Home and archive work with zero, one, and multiple published editions.
- Existing digest sections, localisation, agent JSON, and settlement behavior
  remain compatible.
- Tests cover publication uniqueness, ordering, gap navigation, date labels,
  and empty states.

## Deployment prerequisite

Audit production source weeks against week-level commentary before deployment.
Every edition intended for home or archive must have exactly one published
week-level commentary. Existing raw weeks are not promoted automatically.

## Non-goals

- Immutable `DigestRevision` or `PublicationManifest v0`
- Agent JSON schema changes
- Entitlement or pricing policy
- Mainnet migration
- Search, SEO, or a WYSIWYG editor
