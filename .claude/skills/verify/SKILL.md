---
name: verify
description: Run this repo's full CI-parity verification battery plus the red→green enforcement proof and a live DoD demo. Run before EVERY commit and after applying review fixes. Never claim green without showing the output.
---

# Platform verification battery

Run every step; paste real output in your report. A step you did not run is a step that
failed. All commands from the repo root.

## 1. The battery (CI's gates plus two stricter local checks)
The full-tree `pytest -q` and `pre-commit run --all-files` steps are local supersets of CI —
the full-tree run also catches tests accidentally placed outside the four CI-split suite
directories, which CI would silently skip.
```bash
uv run ruff check . && uv run ruff format --check .
uv run mypy src/quant/engine src/quant/ledger src/quant/evaluation --strict
uv run lint-imports                       # expect: "Contracts: N kept, 0 broken."
test -d src/quant/engine && ! grep -rE "(^|[^A-Za-z0-9_.])(import|from)[[:space:]]+(io|requests|httpx|duckdb)\b|datetime\.now" src/quant/engine/
uv run pytest -q                          # full tree
HYPOTHESIS_PROFILE=ci uv run pytest tests/unit tests/property -q
HYPOTHESIS_PROFILE=ci uv run pytest tests/golden -q
HYPOTHESIS_PROFILE=ci uv run pytest tests/integration -q
uv run pre-commit run --all-files
```
If dependencies or build config changed: `uv sync` first and confirm `uv.lock` is modified
and staged — CI runs `uv sync --locked` and goes red on a stale lockfile.

## 2. Red→green enforcement proof (required when the change adds/modifies any gate,
contract, validator, or invariant)
Pattern — prove the mechanism actually binds, then restore byte-identically:
1. `before=$(shasum -a 256 <file> | cut -d' ' -f1)` on the file you will perturb.
2. Inject a violation the new mechanism must catch (a forbidden import, a wrong DECIMAL
   scale, an out-of-order epoch, a mutated golden value…).
3. Run the relevant gate; show it FAILING and its nonzero exit code.
4. Revert; `shasum` must match `before` exactly; show the gate green again.
NOTE for NEW (untracked) files: `git checkout --` cannot restore them — perturb with a
scripted, exactly-reversible edit (e.g. a python string replace you can invert verbatim)
and prove restoration by the shasum comparison in step 4 (P0-09 precedent).
If the gate's code changes AFTER its proof ran, the proof is stale — redo it against the
current code before shipping.
Precedents: layer-violation import into engine (lint-imports exit 1); duckdb import into
engine (forbidden contract); lot.open_price scale flip (pandera SchemaErrors).

## 3. Live DoD demo
Demonstrate the task's doc-20 DoD behavior once, for real, using the scratchpad directory
for any throwaway data (never `/tmp`, never inside the repo). Example precedents: the
raw-store no-op/supersession log sequence; the ConfigError from a deliberately broken yaml.
Show the output.

## 4. Hygiene checks before handing to /ship
```bash
git status --short          # no .DS_Store, no data/, no scratch files, no secrets
git grep -nE "src/platform|docs/decisions" -- ':!docs/design/07-adr.md' ':!ops/journal.md'
```
Both must be clean (the grep must return nothing).
