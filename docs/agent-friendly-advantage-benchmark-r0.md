# Agent-friendly Advantage Benchmark R0

[日本語版](agent-friendly-advantage-benchmark-r0.ja.md)

## 1. Status

- **Status:** Accepted for implementation
- **Initial user:** Shuhei + Codex
- **First prospective edition:** `2026-W29`
- **Production changes in R0:** None

## 2. Purpose

R0 establishes a repeatable benchmark for a single product question:

> Can the paid agent representation reduce the total work required to turn an
> x402 weekly digest into three useful decisions, compared with taking the free
> HTML route?

The benchmark exists before the agent JSON is redesigned. A result showing
that the current JSON has no economic advantage is a valid and useful R0
outcome. R0 measures the baseline; a later release must earn the right to call
the paid representation **agent-friendly**.

## 3. Product hypothesis

Machine-readable data has a structural advantage over HTML only when that
advantage survives the whole decision task. The paid path is rational when:

```text
endpoint price + structured-data processing cost
    < HTML retrieval + semantic recovery + verification + error risk
```

For consumer subscription users, model inference often appears to have near
zero marginal cash cost while an x402 payment is explicit. R0 therefore reports
both:

1. **Physical resource metrics** — tokens, elapsed time, tool calls, retries.
2. **Cash-equivalent metrics** — endpoint price and a conservative conversion
   of measured resource savings, where such a conversion is defensible.

Base Sepolia settlement proves protocol behavior but is not evidence of real
economic preference. Mainnet pricing is out of scope until the representation
shows measurable additional value.

## 4. Fixed user task

Every arm receives the same task:

> From this week's x402 digest, identify the three items Shuhei should pay
> attention to. For each item, explain why it matters, cite supporting source
> URLs, and recommend one concrete next action. State any material uncertainty.

The target completion time is **90 seconds**.

The response must match this logical shape:

```json
{
  "weekly_thesis": "string",
  "top_items": [
    {
      "id": "string",
      "reason": "string",
      "evidence_urls": ["https://..."],
      "recommended_action": "string"
    }
  ],
  "uncertainties": ["string"]
}
```

`top_items` must contain exactly three items.

## 5. Fixed personal context

Personalisation remains a client-side concern in R0. Both arms receive the
same versioned interest profile covering Shuhei's current x402 work, including
the batch-settlement effort, Japanese contributor activity, acli adjacency,
and x402-cms itself.

The real profile is a private benchmark input and is never committed to this
public repository. The implementation may include a public example profile,
but it must not silently substitute for the private profile in an official
run. The manifest records only the profile version or digest.

## 6. Experimental design

R0 has two separate experiments so representation value is not confused with
payment transport overhead.

### 6.1 Experiment A — representation value

Purpose: isolate the effect of the input representation.

| Arm | Input |
|---|---|
| H | Raw human HTML response body |
| J | Current agent JSON response body |

Rules:

- Both representations come from one frozen source snapshot for the edition.
- The same Codex model, effort, system instructions, task prompt, and personal
  context are used in both arms.
- Each arm runs in a fresh context with no access to the other arm.
- Web search and unrelated retrieval tools are disabled.
- The agent may use only URLs and facts contained in its supplied input.
- Arm order is randomised and the seed is recorded.
- Payment settlement is excluded from timing and cost in Experiment A.

### 6.2 Experiment B — end-to-end agent economics

Purpose: measure the real route an agent must traverse.

| Arm | Route |
|---|---|
| H | Live digest request using the free browser/HTML route |
| J | Live agent request, HTTP 402 challenge, signing, settlement, paid JSON |

Experiment B records discovery, fetch, settlement, parsing, and answer
generation as one end-to-end run. It must record:

- HTTP request count and status sequence;
- settlement network and nominal price;
- settlement latency, transaction identifier, retries, and failures;
- total elapsed time and model usage;
- the same quality measures used in Experiment A.

The current User-Agent dispatch is routing, not a security boundary. R0 does
not attempt to block an agent from taking the HTML route.

## 7. Dataset and contamination control

The initial study contains five eligible editions:

- four historical dry-run editions, provisionally `2026-W24` through
  `2026-W27`;
- one prospective dogfood edition, `2026-W29`.

`2026-W28` is excluded from formal scoring because the evaluator and the active
Codex context have already inspected it.

An edition is eligible only when:

- both renderings are available and non-empty;
- the capture records equivalent source coverage for both arms;
- the capture is frozen before either arm runs;
- the evaluating Codex context has not previously seen the edition contents.

If a provisional historical week is ineligible, use the nearest earlier
eligible edition and record the substitution.

## 8. Model control

R0 uses Codex only. Multi-model generalisation is deferred until the benchmark
works and the JSON shows an advantage for the initial user.

Every run manifest records:

- model identifier;
- effort level;
- prompt version;
- profile version or digest;
- edition and source-snapshot digest;
- arm and randomisation seed;
- start and completion timestamps;
- tool policy.

A comparison is invalid if the two arms used different model or effort
settings.

## 9. Metrics

### 9.1 Automated metrics

- input and output tokens;
- input bytes;
- wall-clock duration;
- model/API calls and tool calls;
- HTTP requests and payment retries for Experiment B;
- response-schema validity;
- exactly-three-items validity;
- evidence URL presence in the supplied representation;
- duplicate recommendation count;
- run failure and timeout status.

Raw metrics remain separate. R0 does not hide trade-offs behind one arbitrary
composite score.

### 9.2 Blind human evaluation

For each edition, the two short outputs are labelled neutrally and shown in a
random order without revealing whether they came from HTML or JSON.

Shuhei evaluates:

- which output better identified what matters this week;
- which output offered more useful next actions;
- whether either output contains a material factual or evidence error;
- overall preference: first, second, or tie.

The benchmark does not ask Shuhei to label every source item. Normal reactions
such as “follow”, “noise”, “reply”, “investigate”, or “implement” are recorded
separately as downstream-value signals.

## 10. Benchmark success and product gate

R0 is complete when the harness can produce reproducible comparisons and a
blind review packet. The current JSON is not required to win.

A future agent-friendly representation is considered ready for economic
validation when, across the five-edition study:

1. it is not worse than HTML in at least four of five blind comparisons;
2. it has no critical factual or evidence failures;
3. it reduces the median of at least one primary resource metric by at least
   30%;
4. it does not regress another primary resource metric by more than 10%
   without an explicitly accepted trade-off;
5. its proposed price remains well below a conservative estimate of the value
   saved.

Passing this gate permits pricing and mainnet experiments; it does not mandate
them.

## 11. Artifact and result policy

Tracked in git:

- this specification and its Japanese parallel;
- benchmark code and public example inputs;
- versioned prompt and output schema;
- run manifest schema;
- aggregate reports that contain metrics, judgments, and artifact digests.

Not tracked in git:

- captured HTML and JSON bodies;
- private interest profiles;
- raw model transcripts;
- payment credentials or wallet material;
- unredacted run artifacts.

Generated artifacts live under an ignored benchmark artifact directory. An
aggregate report refers to them by digest and, when needed, an external
artifact pointer.

## 12. Ownership boundary

`x402-cms` owns digest collection, rendering, benchmark capture, and the
human/agent representation comparison.

`x-402-contents-manager` remains the future boundary for reusable offers,
entitlements, and feedback infrastructure. R0 introduces no dependency on it.

## 13. Non-goals

- changing the production agent JSON schema;
- intentionally degrading or truncating the free HTML;
- preventing User-Agent spoofing or HTML scraping;
- personalised ranking on the server;
- adding a benchmark database;
- multi-model evaluation;
- Base mainnet migration;
- setting a production price;
- batch-settlement integration.

## 14. Delivery sequence

### R0-A — representation harness

- define versioned task prompt, private-profile interface, output schema, and
  run manifest;
- freeze one edition snapshot and render both arms;
- execute isolated Codex runs;
- collect automated metrics and generate a blind packet.

### R0-B — historical baseline

- run the four eligible historical editions;
- identify where HTML or JSON creates avoidable work;
- publish an aggregate baseline without raw content.

### R0-C — prospective dogfood

- freeze `2026-W29` before review;
- complete the blind evaluation;
- record which recommendations led to real follow-up actions;
- decide the smallest R1 representation change from observed bottlenecks.

### R1 — agent decision packet

The W27 blind review and external-grounding follow-up now give R1 a design
direction while leaving its production schema unapproved. R0 remains the
baseline for the current isomorphic projections. R1 will test a functionally
non-isomorphic, delegation-ready work packet with claims, evidence,
counterevidence, bounded actions, verification, and expected receipts. See
[Semantic Consistency, Functional Non-Isomorphism](agent-friendly-non-isomorphism-memo.md).

## 15. R0 acceptance criteria

- [ ] One command can run either arm for an eligible frozen edition.
- [ ] The two arms are guaranteed to use identical model, effort, prompt, and
      profile versions.
- [ ] Each arm runs in a fresh context with the defined tool policy.
- [ ] Every run emits a valid manifest and fixed-shape result.
- [ ] Automated metrics are collected without a composite score.
- [ ] A randomised, origin-blind human review packet can be generated.
- [ ] Historical raw captures and model transcripts remain gitignored.
- [ ] Experiment A excludes payment overhead.
- [ ] Experiment B records the complete 402 settlement path.
- [ ] `2026-W28` cannot be included in formal scoring.
- [ ] The full existing test suite remains green.
