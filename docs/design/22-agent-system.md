# 22 · Multi-Agent System Design
**Purpose:** the concrete design of the agent layer — roster, runtime, flows, guardrails, evals, cost. **Position (ADR-015, unchanged):** agents OPERATE the platform and AUGMENT research; the deterministic engine and the human hold decision authority. Agents cannot move money by construction — no order-submission tool exists in their toolbox. **Build phase:** P4, gated on stable reasons-JSON (P2 exit). Est. 30–50h.

## Why this shape (and not an autonomous swarm)
At ~12–50 portfolio decisions/yr, an autonomous agent cannot demonstrate edge within
years (statistics, not ideology) — but agents are immediately valuable where errors are
cheap and volume is high: reading filings, drafting prose, triaging anomalies, arguing
the other side. So the architecture routes agent effort to high-volume/low-blast-radius
work and lets any agent EARN authority through the same champion/challenger gate as any
model (admission ladder, ADR-015).

## Runtime (deliberately boring)
No resident daemons. `platform agent run <flow> [--asof]` — a single orchestrator
process invoked by cron or the operator; it executes a **declared DAG of agent steps**
(flows below), then exits. LLM = hosted API (Anthropic); model tiering: small/cheap for
triage & extraction, strong for research memos & dissent. Tools = the platform CLI (doc
14) exposed as typed JSON tool schemas; every call runs as a subprocess with read-only
DB access. Structured outputs validated by pydantic; one retry on validation failure,
then the step fails loudly (a missing memo is SEV3; the pipeline never blocks on agents).

## Roster (mission · tools · guardrails · output)
1. **Narrator** — turns `Decision.reasons` JSON + ledger deltas into proposal-report
   prose. Tools: explain, ledger, features (read). Guardrail: *numeric grounding* — a
   validator extracts every number/ticker from the prose and asserts it exists in the
   source JSON; violation ⇒ regenerate once ⇒ fall back to template text. Output:
   `narrative.md` per proposal section.
2. **Dissent agent** — writes the strongest case AGAINST each proposal (concentration,
   regime, liquidity, thesis-drift arguments), citing evidence_refs. Output: dissent
   memo attached to the proposal (doc 24). The human should occasionally veto because of
   it — that is the success metric.
3. **Filing analyst** — summarizes new filings/announcements for held+ranked names into
   evidence packs: {facts[], each with source_ref+quote-span, materiality guess}.
   Guardrail: every fact must carry a resolvable source_ref into raw/; unresolvable ⇒
   fact dropped.
4. **Event triage annotator** — drafts one-paragraph context for events; severity comes
   ONLY from §17 rules (agent annotates, never scores).
5. **Data steward** — reads DQ failures/parse quarantines; proposes parser diffs as git
   patches + fixture files. Never merges; operator reviews the PR.
6. **Research analyst** — drafts pre-registered variant specs + hypothesis memos with
   evidence labels (doc 07 taxonomy). Spends the variant budget like any human idea —
   the harness enforces the cap regardless of who asks.
7. **Runbook copilot** (last) — interactive incident walkthrough grounded in doc 17.

## Flows (DAGs; all outputs land as artifacts, reviewed by the human on their cadence)
- **weekly_ops** (cron Sun): DQ read → steward (if failures) → event annotator →
  digest render. Budget: ≤10 min wall, ≤₹40.
- **results_season_daily** (cron, seasonal): new filings → filing analyst → evidence
  packs → severity table → alerts per §17.
- **quarterly_proposal** (operator-invoked): engine runs FIRST (deterministic) →
  narrator → dissent → report assembly → human. Agents decorate a decision already
  made; they never precede it.
- **research_sprint** (operator-invoked): analyst memo → operator picks → harness runs.

## Guardrails (defense-in-depth, in order of importance)
1. **Capability containment:** read-only tools; no submit_orders, no file writes outside
   `agents/outbox/`; subprocess sandbox; network = LLM API only.
2. **Prompt-injection defense** — filings and announcements are UNTRUSTED third-party
   text that we feed to an LLM. Mitigations: untrusted text is wrapped and labeled as
   data in prompts; agents processing it have the narrowest toolset (analyst: zero
   platform tools — pure text-in/JSON-out); structured-output validation; grounding
   validators (facts need resolvable refs); and containment (#1) bounds the blast radius
   of a successful injection to a bad memo — which the human reads with attribution.
3. **Grounding validators** per agent (numeric grounding, ref resolution) run OUTSIDE
   the model.
4. **Budget guards:** per-flow token/₹ caps; monthly cap ~₹500 (inside the platform
   cost ceiling); circuit-break at 2× expected cost.
5. **Audit:** every call logged {flow, agent, model, prompt_hash, tool calls, tokens, ₹,
   output_hash} to `agent_runs` table — same reproducibility bar as everything else.
6. **Kill switch:** `agents.enabled=false` config; platform is fully functional without
   them (agents are decoration on a deterministic spine — by design).

## Agent evaluation (agents get the same discipline as strategies)
Golden transcripts: frozen input→expected-output pairs per agent (10–20 each), re-run on
any prompt/model change; rubric-graded (faithfulness, grounding, usefulness) with the
strong model as grader + quarterly human spot-check of 10 samples. Drift monitor:
grounding-validator failure rate and regeneration rate charted on the status page;
>5% ⇒ investigate before trusting outputs. Promotion up the ladder (e.g., dissent agent
gaining a veto-recommend field) requires: written ADR + a quarter of logged usefulness
(operator marked ≥N dissents "changed my review") — the champion/challenger norm applied
to agents.

## Latest-techniques map (labels per doc 07 taxonomy — what's in, what's deliberately out)
IN: single-agent tool-use loops (proven) · structured outputs + external validators
(proven) · critic/verifier pattern (battle-tested) · prompt caching for repeated system
context (proven, cost) · retrieval grounded in our own raw store with citations (proven)
· model tiering by task (battle-tested). OUT with reasons: multi-agent debate beyond one
dissent pass (emerging; marginal value over a single strong critic here) · autonomous
computer-use agents (no UI to drive; containment risk) · fine-tuning (no data volume;
maintenance) · agent-written code auto-merged (steward proposes, human merges) ·
LLM-as-decision-maker (fails the baseline rule at our decision count — the whole point).
