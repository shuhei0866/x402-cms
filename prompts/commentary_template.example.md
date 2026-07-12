<!--
commentary_template.example.md — public scaffold for one commentary note.

Copy this into the vault as
  life_value_lab/personal_works/my_vault/x402_digest/views/YYYY-Www-<slug>.md
and fill it in. The real working template (prompts/commentary_template.md)
is gitignored; this example ships so a fresh clone sees the shape.

Principle (do not "optimise" this away): the LLM only ever enters
DOWNSTREAM of judgment. The observation and the hypothesis are written
by hand, first. Expansion / compression / style-lint / candidate
surfacing are opt-in afterthoughts, never the source of the take. The
template is a lens for the author's own reading, not a generator.
-->

---
week: 2026-W19              # required, ISO week (YYYY-Www)
title: <one-line title>     # required
published: false            # flip to true to publish; false = unpublish; delete: true = retract

# Exactly one of the following two shapes:
#  (a) week preface — the publication record and overview for the week.
#      Exactly one published week-level note is allowed per week. Home,
#      archive, and gap-aware navigation only surface weeks with this record:
# week_level: true
#  (b) per-item note — must target at least one item:
target_refs:
  - pr:x402-foundation/x402#0000   # a merged PR
  # - x:0000000000000000000        # an X post id

# Optional: promote this note into the week's Picks (ranked list).
# recommended_rank must be unique within the week (publish fails on a
# collision). tldr is the agent-facing one-liner, <= 280 chars.
# recommended_rank: 1
# tldr: <the single sentence an agent should take away>

tags: []                    # optional, free-form
---

<!--
Body: plain markdown. Write it in your own voice, in the order you
actually think:

1. Observation — what concretely happened (the diff, the thread, the
   number). Stay close to the artifact.
2. Hypothesis — why it matters, stated as a claim you can be wrong
   about. Land the abstract on something concrete (an incentive, a
   person's motive, a cross-domain analogy).

Keep meta out of it — write about the technical substance, not about
the digest or the strategy of writing it. Only after the take exists
should any opt-in downstream pass (tighten / expand / lint) run.
-->

Write the observation here.

Then the hypothesis here.
