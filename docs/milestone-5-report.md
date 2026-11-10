# Milestone 5 report: personal finances and pilot readiness (Gate P)

Status: **complete, awaiting product owner review** (PRs #129–#134, stacked after Milestone 4;
each is reviewable on its own). **No environment exists beyond local development and CI. Nothing
was created on AWS, and no migration has been applied anywhere else.** Brief:
[planning doc 18](planning/18-milestone-5-brief.md); specification: planning doc 11, on the
planning branch (PR #1), which is not yet merged.

## What you can do now
On top of Milestones 1 to 4, you can:
- **Keep your personal finances** in a personal workspace, separate from any business.
  - One action sets up accounts and categories. Record money **spent**, **received** or **moved**
    in plain words; each is a balanced, posted entry underneath. Undo is a reversal.
  - Give a house, investments or a business stake a **valuation** (an estimate, never booked).
  - See **net worth** today and over the last year, and spending by category.
  - Set a **monthly budget** per category, **goals** (savings, emergency fund, debt payoff) and
    see the **next 12 months** of cash.
- **Get suggestions from your business, if you opt in.** Link a business account such as the
  director's loan account. Payments to you are suggested in your personal books and recorded
  only when you confirm each one. The business never sees your personal workspace.
- **Let an accounting firm in, on your terms.** Grant a firm a scope of roles until a date. The
  firm assigns its people; they work inside your workspace with at most the roles you chose,
  every action is recorded under their name and firm, and **End access** stops them at once.
  Firms see such clients in their portfolio.
- **Own your data.** Download a full export (every record, the document files, and a manifest
  with counts and hashes). Delete a workspace in two steps, with 30 days to change your mind.
- **Be ready for the pilot.** The whole pilot environment is written as code and checked in CI,
  with alarms, backups, a tested restore drill and runbooks. Creating it waits for your approval.

Try it with `make demo` ([demo script](demo.md)); its 28 steps now include the personal
workspace, its budget and goals, the counterpart hint, an engagement grant with its revocation,
and the export with the two-step deletion. User guides: [personal finances](user-guide/personal.md),
[firm access](user-guide/engagements.md) and [export and delete](user-guide/export-and-delete.md).
Runbooks: [pilot environment](runbooks/pilot-environment.md) and
[backup and restore drill](runbooks/backup-restore-drill.md).

## Items
| Item | PR | What |
|---|---|---|
| M5-1 Personal workspace | #129 | `personal` module over the ledger: setup, spent / received / moved, opening balances, undo by reversal, valuations (EXPECTED, never posted), net worth with a 12-month trend, spending by category; personal menu (ADR-0031) |
| M5-2 Budget, goals, projection | #130 | monthly budget per category (versioned), three goal kinds with pace and status, 12-month cash projection labelled BUDGET or FORECAST (ADR-0032) |
| M5-3 Counterpart hint | #131 | opt-in link to a business account; suggestions read in the business workspace with the person's own permission; confirm or dismiss in the personal workspace, once per business entry (ADR-0033) |
| M5-4 Engagement grants | #132 | grants in the client's workspace, staffing in the firm's; access worked out on every request as scope ∩ firm role; audit in both workspaces; portfolio includes engaged clients (ADR-0034) |
| M5-5 Pilot environment | #133 | `infra/terraform/envs/pilot` and six new modules (registry, endpoints, app, edge, monitoring, backup); SBOM in CI; `make restore-drill`; runbooks (ADR-0035). **Never applied.** |
| M5-6 Export and deletion | #134 | full export built from the database catalogue; two-step deletion with a grace period; purge job with the schema-owner role that proves no row is left (ADR-0036) |

## Acceptance criteria (brief §5)
| Criterion | Evidence |
|---|---|
| No route returns personal data in a business context or the reverse | Personal and business workspaces are separate tenants under FORCE row-level security. `tests/personal/test_personal.py` (personal routes refused in a business workspace, a stranger gets 404); `tests/personal/test_counterpart.py` (the business workspace has no personal route; the hint reads business data only with the person's own business permission); `tests/tenancy/test_lifecycle.py` (an export contains nothing of another workspace) |
| Personal transactions always produce balanced, posted entries; corrections are reversals | `test_simplified_transactions_are_balanced_posted_entries` (trial balance in balance, five posted entries, undo is a reversal and the original is kept) |
| Net worth labels valuations as EXPECTED and equals the ledger balances where there is no valuation | `test_valuations_are_expected_and_never_posted`; the demo's net worth is worked out by hand in its test |
| An engagement is limited to its scope; revoking it makes the next request return 404 and removes the client from the firm portfolio | `tests/tenancy/test_engagements.py` (4 tests: intersection, entity scope, immediate revocation, portfolio, expiry, audit attribution, database guards); live check on both sides |
| The export contains every row of the workspace (verified by counts and hashes); a deleted workspace leaves no rows behind after the purge | `tests/tenancy/test_lifecycle.py`: the manifest's row count per table equals the database, every file matches its hash, the document is byte-identical; after the purge every tenant table has 0 rows for the workspace, the other workspace is unchanged and its audit chain verifies; live check with the real purge job |

## Gate P checklist
| Gate P condition (backlog) | Status |
|---|---|
| The owner's business bank format importable | **Needs you.** CAMT.053 and mapped CSV imports work (M2-5). Send a synthetic sample in your bank's export format, or name the bank, so its format can be tested |
| Open items and VAT codes working | Done in Milestone 2 |
| Isolation and coexistence suites green | Green: row-level security suite, personal/business, counterpart, engagement and lifecycle tests |
| Backup and restore tested | Tested on the local stack (82 tables, 62,911 rows identical; integrity checks pass on the restored copy). The pilot drill runs after the environment exists |
| MFA enforced | Yes (M1); every live check signs in with MFA |
| AI disabled | Yes. No AI feature is built yet (M12) |
| A security review of Phases 1–2 | **Open.** Automated checks are green on every PR (Semgrep, gitleaks, dependency audit, Checkov, import contracts, isolation tests). An independent review is your decision before real data |
| Your written approval | **Needs you** |

## Database changes (Milestone 5)
| Module | Migrations | Content |
|---|---|---|
| personal | 0001–0006 | valuations; budget amounts and goals; counterpart links and decisions; guards (supersede only, retire only, revoke only, append-only) |
| tenancy | 0004–0006 | engagements (client side) and engagement staff (firm side) with guards; four narrow SECURITY DEFINER lookups; the global deletion record |

Every new tenant table has FORCE row-level security and composite tenant keys. The deletion
record is a reviewed global table that holds IDs, dates and row counts only. Migrations were
applied locally only.

## Security controls added
- **One workspace per request, still.** The counterpart hint and the firm portfolio never query
  across workspaces. A firm user works inside the client's own row-level security context.
- **Engagements are least privilege.** Ownership and administration cannot be granted; the
  effective roles are the intersection with the person's own firm role; access is worked out on
  every request, so revocation and expiry are immediate; unstaffed users get the same 404 as
  strangers.
- **Attribution.** A firm user's actions are in the client's audit trail under their own name,
  with the firm and engagement.
- **Deletion cannot be started by the application's runtime role.** Only the schema-owner
  maintenance job can purge, only for a deletion an owner confirmed with a recent sign-in, and it
  proves that no row is left before it commits.
- **The pilot environment has no public subnets and no route to the internet.** The load
  balancer is internal and reachable only through CloudFront and its firewall; database roles are
  separated by task; secrets are never in code or Terraform state; images are referenced by
  digest; firewall logs stay in the EU region with cookies and tokens redacted.

## Quality
Measured on 2026-11-10 on the M5-6 branch (`make test`, fresh database):
- Backend: **1,171 tests pass**; **96.8%** line coverage overall.
- Frontend: **60 tests**, including axe on every new screen; ESLint strict, `tsc`, build.
- Infrastructure: `fmt`, `validate` for staging and pilot, tflint (CI) and Checkov (430 checks
  pass, none fail; each exception has a written reason).
- Every PR's CI is green on its head.
- **Live checks** with MFA sign-in on the local stack for every new screen. They and the tests
  found and fixed, among others:
  - a personal workspace that opened on "Journal entries";
  - a budget row that kept showing an old amount after saving;
  - a revoked counterpart link that was fetched once more (a 404 in the console);
  - same-named workspaces that could not be told apart in a list;
  - a new firm without a legal entity whose home page stayed on "Loading";
  - a deletion record that the isolation test rightly flagged as an unprotected tenant table;
  - a purge job that would have lacked permission to delete document files on AWS.

## Known limitations
- **Personal projections are simple**: no seasonality, interest or recurring transactions.
- **The counterpart hint** suggests every debit on the linked account; link an account that only
  holds payments to you.
- **Engagements** count only workspace-wide firm roles. Moving a firm-hosted client into its own
  workspace is a later feature.
- **The export is built in memory**, which suits the pilot; very large workspaces will need a
  background export.
- **Backups keep a deleted workspace** until they expire (up to one year). The privacy notice
  must say so.
- **The pilot environment** has no way out to the internet. An identity provider outside it, and
  antivirus signature updates, need a controlled way out (decision 3 below).
- **Greek wording** for all new screens needs a native speaker's review.

## Decisions and approvals needed from you
1. **Review and merge**, in order: PR #1 (planning documents), the earlier stacks, then
   #129–#134 and this report.
2. **ADRs to accept or change:** 0031 (personal finances), 0032 (personal plans), 0033
   (counterpart hint), 0034 (engagement grants), 0035 (pilot environment), 0036 (export and
   deletion).
3. **For the pilot environment** (nothing is created until you approve in writing):
   - the separate AWS account;
   - the domain and its certificates;
   - where the identity provider runs (Keycloak in the account, or a managed provider);
   - how the antivirus service runs and gets its updates;
   - who receives alarms;
   - whether you want a hosted error tracker (today an error raises an alarm from the logs).
4. **Defaults to confirm** (brief §3 and the ADRs):
   - 30 days' grace before a confirmed deletion is purged;
   - engagements of at most 3 years, with accountant, reviewer and read only as grantable roles;
   - firm partners may export; only owners may delete;
   - daily backups for 35 days and monthly for a year; recovery targets of 5 minutes and 4 hours.
5. **Gate P items on your side:** your bank's statement format; an independent security review
   of Phases 1–2 if you want one before real data; your written approval to start the pilot.
6. **Sign-offs still open from earlier milestones:** the golden 13-week forecast (AC-CW5) and
   the golden goal figures (AC-GO2).

Milestone 6 (three-statement projections and rolling forecasts) waits for your review of this
milestone.
