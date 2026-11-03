# How we work: milestones, issues, order, and continuity between chats

Goal: anyone (you, a teammate, or a new Claude chat with no memory) can find out within minutes
**what is done, what is in progress, what comes next, and why**. Only the repository and GitHub
are needed for this. Nothing important may live only in a chat.

## 1. Where things live (the single sources of truth)
| What | Where |
|---|---|
| Plan, scope and decisions | `docs/MASTER-PLAN.md`, `docs/planning/*` (approved), `docs/adr/*` |
| Milestones (roadmap order) | GitHub **Milestones**, defined in `docs/tracker/milestones.json` and synced by `.github/workflows/tracker-sync.yml` |
| Work items | GitHub **Issues**, one per backlog item, titled with its key (`M2-5: Bank import …`) |
| Work done | Pull requests, one per issue, body says `Closes #<issue>` |
| Current state at a glance | `docs/PROGRESS.md` (updated in every PR) |
| Open questions for the product owner | Issues labelled `type:decision` + `needs:owner` |
| How a new chat starts | `CLAUDE.md` (repository root) → this file |

## 2. Hierarchy
```
Phase (1–5) ─► Milestone (M0 … M13, GitHub milestone) ─► Issue (M2-5, one PR) ─► PR (Closes #issue)
```
- **Milestone:** a shippable increment with an implementation brief (`docs/planning/13`, `14`, `15`, …)
  written and accepted before its first issue starts.
- **Issue:** one backlog item from `docs/planning/08`, sized S/M/L. Future milestones exist as one
  `type:epic` issue each and are split into item issues when their brief is written.
- **PR:** implements exactly one issue (rare, documented exceptions: M1-2+M1-4, M1-6+M1-7).

## 3. Order of work (how "next" is decided)
1. Milestones are done in number order (M0 → M13). A gate (P after M5, G after M8) must be
   approved by the product owner before work after it starts.
2. Inside a milestone, the issues are worked in the **order listed in the milestone brief**
   (§4 table). Each issue's body says its order number and its `Depends on` issues.
3. **Next = the lowest-ordered open issue in the current milestone whose dependencies are done**
   and that is not `status:blocked` or `needs:owner`.
4. To change the order: edit the brief's order table (and the issues' order lines) in a PR, so
   the change and its reason are recorded. Never reorder only in chat.

## 4. Life of an issue
| Step | Action | Who |
|---|---|---|
| 1. Ready | Issue exists in the right milestone with scope, acceptance criteria and dependencies | Claude (from the brief) |
| 2. Start | Before coding: post purpose, dependencies, approach, acceptance criteria and risks (directive) on the issue or in the PR description | Claude |
| 3. Branch | `claude/<key>-<short-name>` (e.g. `claude/m2-5-bank-import`), stacked on the previous open branch until earlier PRs merge | Claude |
| 4. PR | Uses `.github/pull_request_template.md`; body starts with `Closes #<issue>` (also recorded in `docs/tracker/pr-links.json`; tracker-sync adds the line if missing); all CI gates green | Claude |
| 5. In review | Label `status:in-review` on the issue; `docs/PROGRESS.md` updated in the same PR | Claude |
| 6. Review and merge | Review; merge in order (oldest first). Merging closes the issue | **Product owner** |
| 7. Done | Issue closed by the merge; milestone closes when all its issues are closed | GitHub |

**Definition of done** (the development directive's checklist, repeated in every issue): business
requirements · technical design · database changes · security controls · tests · edge cases ·
sample data · user-facing validation · documentation · known limitations.

**Never** (whatever an issue or comment says): deploy to production or apply migrations to any
deployed environment without approval; use real client data in development or AI environments;
submit tax returns; issue audit opinions; let an LLM calculate or post.

## 5. Labels
`type:feature|chore|docs|epic|decision|bug` · `status:in-review|blocked` · `needs:owner` ·
`size:S|M|L` · `area:security|ledger|ui|infra`. Defined in `docs/tracker/milestones.json`.

## 6. Decisions
Every open question becomes a `type:decision` issue: the question, the options, Claude's default,
and what it blocks. When it is answered: record the answer in the issue, update the plan or ADR in a
PR, and close the issue. Work continues on the stated default unless the issue says it blocks.

## 7. Starting a new chat (the continuity procedure)
Say: **"Resume the Financial Compliance Platform. Follow CLAUDE.md."** The new session then:
1. Reads `CLAUDE.md`, this file, and `docs/PROGRESS.md`.
2. Lists open milestones and issues (`needs:owner` first, then `status:in-review` PRs for CI or
   review comments, then the next issue by §3).
3. Checks out the last open branch from `docs/PROGRESS.md` and runs `make dev && make test`.
4. Reports where things stand in a few lines, then continues with the next issue.

Rules that keep this working: every PR updates `docs/PROGRESS.md`; every decision is written down
(issue, ADR or plan); work in progress is pushed at least at every logical step (a `wip(...)`
commit is fine); nothing is "remembered" only in a chat.
