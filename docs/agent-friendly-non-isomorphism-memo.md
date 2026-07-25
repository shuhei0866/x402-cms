# Design Memo: Semantic Consistency, Functional Non-Isomorphism

[日本語版](agent-friendly-non-isomorphism-memo.ja.md)

- **Date:** 2026-07-19
- **Status:** Accepted direction for R1; schema and production changes remain unapproved
- **Scope:** The relationship between the free human HTML projection and a future paid agent projection

## Decision

The human HTML and agent representation should share a truthful evidence substrate, but they should not remain functionally isomorphic.

The design target is:

> Preserve semantic consistency while allowing functional non-isomorphism.

The human projection exists primarily to help a person perceive the situation, form a view of what matters, and choose where to direct intent. The agent projection should help a delegated agent investigate, decompose, execute, verify, and report back. A JSON serialization of the human article is agent-capable, but it is not yet a compelling agent product.

R0 remains the baseline for the current, highly isomorphic design. This memo does not modify R0 inputs, scoring, or acceptance criteria. It records the direction to test after the baseline.

## Why this changed

The W27 blind review showed that both HTML-derived and JSON-derived answers could be reasonable, while neither could establish whether the highlighted protocol work was grounded in problems outside `x402-foundation/x402`. A follow-up external-grounding pass had to reconstruct four missing layers:

1. evidence that the problem exists;
2. evidence that the proposed mechanism improves it;
3. evidence of independent adoption or use;
4. counterevidence and limits.

That work, rather than JSON parsing, created most of the additional value. It also exposed causal corrections that a narrative-only projection did not make operationally explicit: deployment was not adoption; a missing Bazaar response header was not a single root cause; and receipt binding had stronger external conformance evidence but narrower security coverage than the brief implied.

The product implication is that the paid representation must reduce this reconstruction work. Otherwise an agent can consume the free HTML, recover roughly the same semantics, and rationally avoid the paid route.

## Principal-agent interpretation

AI agency is relational. A human principal supplies intent, constraints, and authority. The AI acts as the agent that realizes them. When that AI decomposes work and delegates to another agent, it becomes a local principal while remaining an agent relative to the human.

```text
human principal
  ↓ intent, scope, authority, budget
agent / local principal
  ↓ bounded task, authority, budget, success criteria
subagent or paid capability
  ↑ result, evidence, cost, receipt, unresolved state
agent
  ↑ synthesized result and escalation
human principal
```

Mandates flow down the delegation graph. Results, evidence, and receipts flow up. The agent projection should therefore be delegation-ready, not merely machine-readable.

## Projection contracts

| Surface | Primary job | Questions it should answer |
|---|---|---|
| Human HTML | cognition, orientation, prioritisation | What happened? Why does it matter? What deserves attention? |
| Agent discovery metadata | capability selection before payment | What can this endpoint do? What does it cost? What input, output, network, and proof can I expect? |
| Paid agent work packet | investigation and execution | What claims are supported? What is uncertain? What can be done next, under what authority, and how is success verified? |
| Receipt / result | upward accountability | What was attempted, what happened, what did it cost, and what evidence can the principal verify? |

The free HTML must not be intentionally degraded. The paid packet earns its price by supplying structure and evidence that are costly to reconstruct, not by withholding basic human understanding.

## Shared substrate, asymmetric projections

Both projections should derive from a common evidence substrate with stable identifiers. They may select and arrange it differently.

The common substrate should eventually be able to express:

- claims and stable claim IDs;
- source observations and timestamps;
- supporting and counterevidence;
- evidence independence and provenance;
- confidence and unresolved questions;
- relationships among actors, proposals, implementations, and deployments.

The human projection can compress this into editorial rhythm. The agent projection can preserve the joins needed for verification and execution. The same fact must not silently change across projections, but the amount of operational detail does not need to match.

## Candidate R1 work packet

R1 should be explored as a delegation-ready work packet rather than a richer article schema. A candidate shape is:

```json
{
  "edition": "2026-W27",
  "thesis": "string",
  "claims": [
    {
      "id": "claim:batch-demand",
      "assertion": "string",
      "status": "supported | contested | unknown",
      "importance": "string",
      "supporting_evidence": [],
      "counterevidence": [],
      "unknowns": [],
      "observed_at": "RFC3339 timestamp"
    }
  ],
  "work_items": [
    {
      "id": "work:onchain-adoption-probe",
      "objective": "string",
      "claim_ids": ["claim:batch-demand"],
      "required_authority": "read_only",
      "estimated_cost": {},
      "preconditions": [],
      "stop_conditions": [],
      "success_criteria": [],
      "verification": [],
      "escalate_when": []
    }
  ],
  "expected_receipt": {
    "result": "required",
    "evidence": "required",
    "cost": "required",
    "unresolved_state": "required"
  }
}
```

This is a hypothesis, not a production schema. The packet should not contain server-side personal ranking or grant authority on behalf of the user. It should expose bounded, verifiable work that a client-side principal may choose to authorize.

## Economic requirement

The paid route is rational only when:

```text
endpoint price + packet processing cost
  < HTML retrieval + reconstruction + verification + error risk
```

The differentiator should therefore be measured as avoided work. Likely sources of avoided work include claim-to-evidence joins, counterevidence, freshness, independent-adoption classification, executable probes, stop conditions, and expected receipts.

Free capability and pricing metadata should remain discoverable before payment. An agent must be able to decide whether the packet is relevant and affordable without buying it blindly.

## Next experiment: one manual golden packet

Do not implement the production schema yet. First build one hand-authored, intentionally non-isomorphic W27 golden packet from the existing external-grounding work.

Compare two end-to-end paths under the same model, tools, authority, and task:

| Arm | Starting surface |
|---|---|
| H | Current human-first W27 HTML-equivalent brief |
| W | W27 delegation-ready golden work packet |

Use a product task rather than the R0 representation task:

> Decide which W27 theme x402-cms should act on next. Produce one bounded execution plan, distinguish observed problems from solution adoption, state the required authority and cost, and define verifiable success and stop conditions.

Unlike R0-A, both arms may use the web. External retrieval is part of the work whose reduction is being measured.

Record:

- wall-clock time, tokens, web/tool calls, and retries;
- unsupported or overstated causal claims;
- whether deployment is distinguished from adoption;
- whether supporting evidence and counterevidence are both present;
- whether the proposed action has authority, preconditions, cost, success, stop, verification, and escalation fields;
- whether another agent could execute the plan without rereading the human brief.

The experiment succeeds if the work-packet arm reduces reconstruction work without degrading judgment or evidence quality. One edition is enough to decide whether a schema spike is warranted; it is not enough to set price or approve mainnet.

## Consequences

If the golden packet is useful:

1. specify a minimal evidence substrate and stable IDs;
2. define a versioned R1 packet schema;
3. add a renderer from the shared substrate;
4. expose free discovery metadata for the paid capability;
5. rerun a multi-edition economic benchmark before production or mainnet changes.

If it is not useful, preserve R0 and do not add schema complexity merely to make the JSON look more agent-like.

## Non-goals

- degrading the human HTML;
- making all source material paid;
- treating JSON syntax as agent value;
- giving the server authority to act for the user;
- granting subagents broader authority than the incoming mandate;
- claiming that a work packet or receipt solves every payment, delivery, or accountability failure;
- changing production routing, price, settlement scheme, or mainnet status in this experiment.
