---
name: ship
description: Commit, push, and watch the GitHub Actions run to green for this repo — the only accepted definition of shipped. Use after /verify (and /review-domains where applicable) pass.
---

# Ship protocol

## 1. Pre-flight
- `/verify` passed in THIS session, after the last edit. If anything changed since, re-run it.
- `git status --short` review: every path staged belongs to the change; no `data/`,
  no `.DS_Store`, no scratch files; `uv.lock` staged iff dependencies/build config changed.
- Secrets check happens in the pre-commit hook (detect-secrets); never bypass hooks with
  `--no-verify`.

## 2. Commit
- Message starts with the doc-20 task ID: `P0-XX: <one-line summary>` (infra/meta work not
  in doc 20 uses `ops:`). Body: what + why bullets, notable findings, doc updates included.
- End the message with the Co-Authored-By line the harness mandates for your model.
- One commit per task — code, tests, and doc propagation in the SAME commit.

## 3. Push and watch Actions to completion
```bash
git push origin main
sha=$(git rev-parse HEAD)
for i in $(seq 1 30); do
  curl -sf "https://api.github.com/repos/DhruvJ2k4/platform/actions/runs?head_sha=$sha" -o /tmp/ci.json 2>/dev/null \
    || { echo "API error"; break; }
  st=$(jq -r '.workflow_runs[0].status // "none"' /tmp/ci.json)
  cc=$(jq -r '.workflow_runs[0].conclusion // "pending"' /tmp/ci.json)
  echo "[$i] $st/$cc"
  [ "$st" = "completed" ] && { jq -r '.workflow_runs[0].html_url' /tmp/ci.json; break; }
  sleep 10
done
```
(Write the temp file into the session scratchpad directory if one exists; `gh run watch`
is fine instead when the gh CLI is installed.)

## 4. Outcomes
- **Green** → report the commit hash + run URL. Only now is the task shipped.
- **Red** → fetch the failing step's log via the API/gh, fix locally, re-run `/verify`,
  commit the fix (same task-ID prefix), push, watch again. Never leave main red; never
  weaken a gate (`|| true`, skipped test, loosened assertion) to get to green.
