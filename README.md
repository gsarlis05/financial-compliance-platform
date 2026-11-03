# Financial Compliance Platform

Accounting, tax, audit, compliance and CFO-level financial planning for accounting firms, businesses
and individuals. Initial market: Cyprus.

- Planning documents and architecture decisions: `docs/` (start with `docs/MASTER-PLAN.md`)
- How to contribute and the engineering rules: `CONTRIBUTING.md`
- User guide: `docs/user-guide/ledger.md`; runbooks: `docs/runbooks/`; API: `docs/api/openapi.json`
- Progress tracker: `docs/PROGRESS.md`; Milestone 1 report: `docs/milestone-1-report.md`

Status: Milestone 1 (secure tenancy and core ledger) complete and in review. Local development
only, synthetic data only.

## Quick start (local)
```sh
make dev            # services, dependencies, migrations
make run-backend    # Django on :8000   (separate terminal)
make run-frontend   # web app on :5173  (separate terminal)
make demo SHARE_WITH=you@example.com   # demo company (sign in once first)
```
