---
name: task
description: Execute a doc-20 platform task (P0/P1/P2/P3) or any nontrivial edit, refactor, or maintenance change end-to-end with this repo's full discipline. Use for ANY codebase change beyond a trivial one-liner — it is the master workflow; it invokes /verify, /review-domains, and /ship at the right checkpoints.
---

# Platform task workflow

You are the implementing engineer for a money-handling system whose design is frozen in
`docs/design/`. Follow these steps in order; do not improvise around them. Where a step says
"show output", the evidence must appear in your final report — a claim without pasted output
does not count.

## 0. Ground rules (non-negotiable, CI-enforced)
- **Never contact NSE/exchange endpoints from tests or CI.** Committed fixtures power all
  automated tests. Live ingestion is operator-invoked only.
- **Money is Decimal.** No floats on ledger/costs/taxes paths; floats allowed in factor math.
- **The design is frozen; code conforms to it.** When reality contradicts a doc: STOP, surface
  it to the user, propose the resolution (see step 7) — never silently deviate.
- **When a DoD is ambiguous on a money path: ask.** Do not guess.
- New dependencies beyond the ADR-010 stack require explicit user sign-off — flag them
  prominently in the plan, never bury them.

## 1. Read before touching anything
1. `CLAUDE.md` (rules), the task's row in `docs/design/20-implementation-plan.md` (its **DoD**
   is the definition of done — memorize it), and every doc the task references
   (algorithms → 21, contracts → 10/14, standards → 23, component behavior → 06).
2. Tail of `ops/journal.md` — prior surprises often constrain today's work.
3. The existing utility inventory — reuse, never reimplement:
   `quant.errors` (taxonomy), `quant.config` (Settings, RateSchedule.asof, load_yaml),
   `quant.schemas` (TABLES, ddl_sql, arrow_frame — the ONLY typed read path, `.df()` is
   banned for money-bearing reads), `quant.ingest.RawStore`.

## 2. Plan gate
- Task estimated ≥4h in doc 20 → EnterPlanMode, write the plan, get approval before any edit.
- The plan must state: DoD verbatim; files to change; **every doc-vs-reality contradiction
  found** with a proposed resolution; any new dependency flagged for sign-off; the
  verification section including the red→green proof you will run.
- Genuine forks (naming, layout, scope) → AskUserQuestion with a recommended option first.

## 3. Probe before design
Any design that rests on tool behavior must be verified empirically FIRST with a cheap
in-memory probe (python -c / :memory: DuckDB in the scratchpad). Precedents that would have
been production bugs without probes: stdlib `platform` shadowing; DuckDB bare DECIMAL
defaulting to (18,3); `.df()` degrading DECIMAL to float64; Typer collapsing one-command
apps; `asof`/`order` being reserved words. Assume nothing about a library; probe it.

## 4. Implement
- Match the standards mechanically: ruff clean (D100/D104 mean every module/package gets a
  one-paragraph contract docstring), mypy `--strict` must stay green on
  engine/ledger/evaluation, layer rule intact (import-linter), engine purity intact
  (no io/httpx/requests/duckdb imports, no `datetime.now` under `src/quant/engine/` — and
  mind the grep-gate scans docstrings too: never write those literals inside engine files).
- Tables snake_case singular; configs kebab-case yaml; run_ids `{kind}-{yyyymmdd}-{shorthash}`.
- All failures raised as the doc-23 taxonomy; never bare `except`.

## 5. Tests ship in the same change
- Suite placement: `tests/unit` (fast logic), `tests/property` (hypothesis invariants),
  `tests/golden` (hand-computed scenarios — NEVER update an expected value to make a run
  pass without written justification), `tests/integration` (committed-fixture pipelines).
- Unique basenames across suites (pytest prepend import mode). No network. Hypothesis
  determinism comes from tests/conftest.py profiles — do not bypass it.
- Every CI pytest step must collect ≥1 test or CI exits 5 and goes red.

## 6. Verify → review
- Run `/verify` (the full battery + red→green enforcement proof + live DoD demo).
- Run `/review-domains` for any change touching src/quant, schemas/, config/, or CI —
  fix CONFIRMED findings, justify or fix PLAUSIBLE ones, then re-run `/verify`.

## 7. Doc propagation — same pass, never later
- Surprise → dated entry in `ops/journal.md`.
- Contract/algorithm change → 5-line mini-ADR appended to `docs/design/07-adr.md`
  (Problem → Alternatives → Decision → Trade-offs → Implications) + propagate to every
  affected doc in this same change (doc 10 mirrors schemas/; doc 20 tree; CLAUDE.md paths).
- Finish with a scoped sweep proving no stale references:
  `git grep -nE "<old-name-pattern>" -- ':!docs/design/07-adr.md' ':!ops/journal.md'` → empty.

## 8. Ship
Run `/ship`. The task is done only when the doc-20 DoD is demonstrated by output you showed
AND the GitHub Actions run on the pushed commit is green. Report: what shipped, DoD proof,
findings recorded, next task in doc 20.
