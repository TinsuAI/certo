# 2026-07-09 — Skills workflow standardization + git guardrails

Tooling/meta session (no app code changed). Aligned this box with the remote's
`mattpocock/skills` workflow and added a project git guardrail.

## What was done
1. **Synced** local `main` (was 23 behind) → `origin/main` (`ecd9179`) via `git merge --ff-only`
   (plain `git pull` was blocked by `pull.rebase=true` + dirty `uv.lock`; FF is clean, `uv.lock`
   and untracked `.ai/`/`docs/` files preserved). The 23 commits include the remote's Pocock setup:
   `AGENTS.md` Skills/Agent-skills sections + `docs/agents/{issue-tracker,triage-labels,domain}.md`.
2. **Installed the mattpocock/skills engineering set** (27 skills) user-level (global) at
   `~/.claude/skills/` via `npx skills add mattpocock/skills -g --copy --agent claude-code -s <list>`.
   Excluded the content/design skills (already curated in `~/dotfiles/ai/skills/`). Full inventory,
   management commands, and the global side-effects are recorded in memory
   `[[mattpocock-skills-global-install]]` — not repeated here.
3. **Created `~/.claude/skills-guide.md`** — Vietnamese, CO-tailored: risk-tiered flow table + the
   `.ai/` remaps for skills that assume GitHub issues / `CONTEXT.md` / `docs/adr`.
4. **Standardized "How We Work"** in `AGENTS.md` (`CLAUDE.md` is a symlink → same file): risky/standard/bug
   flows now `/grill-with-docs → /implement → /code-review`, `/diagnosing-bugs`; legacy `/discover,/rev,/fix`
   noted as retiring. Committed with the guardrail as **`da6e381`**.
5. **Enabled git guardrails, project-scope** — `.claude/hooks/block-dangerous-git.sh` (copied from the
   skill, `chmod +x`) + `.claude/settings.json` PreToolUse `Bash` hook. Verified: blocks `push`,
   `reset --hard`, `clean -f/-fd`, `branch -D`, `checkout/restore .` (exit 2); passes `commit/add/checkout <branch>/pull`.

## Decisions (user-made)
- **Install mechanism:** `npx` direct into `~/.claude/skills` (mirror the remote), NOT dotfiles-tracked.
- **Collisions:** Pocock set is authoritative — `tdd`/`handoff` symlinks unlinked, now Pocock's; `rev/fix/discover`
  retire in favour of `code-review/diagnosing-bugs/grill-with-docs`. (This is GLOBAL — affects every project.)
- **Guardrail scope:** project only (`.claude/settings.json`), because push-`main`→prod-CD risk is repo-local.

## What didn't work / gotchas
- `git pull` fails under `pull.rebase=true` with unstaged changes → use `git merge --ff-only`.
- `npx skills add` symlinks into a hidden store by default → used `--copy` for self-contained real dirs.
- Had to unlink `tdd`/`handoff` symlinks first so `--copy` wouldn't write through into the dotfiles repo.
- **CLAUDE.md is a symlink to AGENTS.md** — edit AGENTS.md only; a CLAUDE.md edit races the symlink target.
- **PreToolUse hooks load at session start** — the guardrail may not be live in the session that created it;
  effective next session.

## Open items
- **`da6e381` is unpushed** — `main` is ahead of `origin/main` by 1. Push (deploy) is the user's manual step:
  `!git push origin main` (push `main` triggers prod CD).
- Untracked, intentionally left alone: `uv.lock` (M), `.ai/api-requests/2026-06-20-bom-*`,
  `.ai/features/2026-06-20-co-datahub-user-guide/`, `docs/huong-dan-su-dung/`.
- Pocock `/handoff` does NOT write STATUS.md/`.ai/sessions` — this file + the STATUS entry were done manually.

App-state work is unrelated to this session; see the top of `.ai/STATUS.md` and the `2026-07-08-*` session docs.
