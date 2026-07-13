---
name: review-domains
description: Fan out the read-only reviewer agents over the current change or plan — the engineering panel (architecture, money, contracts, docs, tests) plus the quant-desk panel (researcher, risk manager, execution trader, portfolio manager) — then triage findings, apply fixes, and re-verify. Run after implementing and before /ship; run the desk panel on plans/ideas too.
---

# Multi-agent domain review — two panels

All reviewers live in `.claude/agents/` and are READ-ONLY: they return findings; you (the
main session) apply fixes. They review two kinds of artifact: a **diff** (code) or a
**plan/idea** (text — pass the plan content in the prompt).

## Panel 1 — engineering (code-focused)
| Agent | Send when the change touches |
|---|---|
| `arch-purity-guard` | anything nontrivial (always send) |
| `test-warden` | anything nontrivial (always send) |
| `money-auditor` | ledger, costs, taxes, config rates, prices, DECIMAL columns |
| `contract-auditor` | schemas/, quant/schemas/, any table shape |
| `docs-warden` | any behavior, path, name, or contract change (almost always) |

## Panel 2 — quant desk (code AND ideas; "as needed" by surface)
| Agent | Seat | Send when the change/plan touches |
|---|---|---|
| `quant-researcher` | methodology | features/, factor math, selection logic, evaluation/, any strategy or factor idea |
| `risk-manager` | risk | engine rules, governor, universe construction, ledger, risk parameters |
| `execution-trader` | execution | drivers/, backtest replay, cost/slippage models, order handling, fill assumptions |
| `portfolio-manager` | product/PM | EVERY plan before approval; any diff changing strategy behavior, operator workflow, or scope |

## Procedure
1. **Scope**: `git status --short && git diff HEAD --stat` (or
   `git diff origin/main...HEAD` if committed-unpushed). For an idea, the artifact is the
   plan text itself.
2. **Select** the relevant agents from BOTH panels using the tables above. When in doubt,
   include the agent — a wasted PASS is cheaper than a missed CRITICAL.
3. **Fan out in ONE message** (parallel Agent calls, by agent name). Each prompt contains:
   (a) task ID + doc-20 DoD verbatim (or the plan text for ideas), (b) the diff-scope
   command, (c) one line of intent, (d) "return findings in your standard format".
   Fallback: if a named agent type is not registered in this session, spawn
   `general-purpose` and instruct it to first Read the agent's `.claude/agents/<name>.md`
   file and adopt that mandate exactly.
4. **Triage**: CRITICAL → fix now, no deferrals. WARN → fix now, or record the explicit
   justification in the report AND ops/journal.md if it is a real accepted risk. NOTE →
   fix if ≤5 minutes, else carry in the report. Disputes are answered with evidence
   (probe or doc citation), never assertion.
5. **Close the loop**: after any fix re-run `/verify` (full battery). Final report includes
   a findings table: agent → finding → severity → outcome (fixed / justified / carried).
   Zero findings is reported as exactly that.
