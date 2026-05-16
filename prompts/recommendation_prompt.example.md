<!--
recommendation_prompt.example.md — public articulation of the rubric
used to choose a week's Picks (recommended_rank 1/2/3).

The real working lens (prompts/recommendation_prompt.md) is gitignored
because the weighting is a personal judgment layer. This example ships
so the structure is legible to anyone reading the repo, and so the
criteria are reproducible rather than vibes.

Principle: this is a RUBRIC THE HUMAN APPLIES, not an instruction to an
LLM to auto-select. The ranking is a judgment call made by hand. An
LLM may, opt-in, surface candidates or argue a case — it never assigns
the rank. Picks are the one place the digest's curation is most
exposed; keep the hand on it.
-->

# Weekly Picks rubric

Pick at most three notes for the week. A slow week may have one or
zero — do not manufacture three. Rank is 1 (lead) to 3, unique within
the week.

A note earns a Pick when it scores on the substance axes, not on
volume or recency:

1. Technical substance — it changes what is possible or how something
   must be built (a new scheme, a wire-format break, a primitive),
   not a docs tidy or a version bump. Prefer the change that a builder
   has to act on.

2. Cross-domain leverage — it connects to a structure outside its own
   corner (an incentive design, a market-lifecycle shift, a legal /
   financial analogy). The note should land the abstract on something
   concrete.

3. Same-generation signal — it surfaces a peer building in the open,
   cited flatly as a peer. Do not inflate by leaning on
   bubble-era or media-class authority; cite the person doing the
   work.

4. Movement over meta — the take is about the technology itself, with
   real heat, not about the strategy of the digest or the framing of
   the ecosystem.

The tldr (<= 280 chars) is the single sentence an agent should take
away if it reads nothing else. It states the claim, not the topic:
"X now makes Y possible, which matters because Z" — not "a note about
X".

When two notes tie, prefer the one a reader can act on this week over
the one that is merely interesting.
