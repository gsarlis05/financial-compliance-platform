# 23 — Gate G Readiness Brief: what must be true before any external customer

Status: **PROPOSED, awaiting the product owner.** Nothing in this brief has been built. Gate G is
an approval gate, not a milestone: work after it (M9 onwards) starts only when you approve the
gate (PROCESS §3). This brief separates what can be prepared in the repository, with synthetic
data and no AWS resource, from what only you or an outside party can do.

Sources: [08](08-implementation-backlog.md) §Phase 3 (Gate G list), [07](07-security-threat-model.md)
(T16 support access, T19 and T34 load, T21 backups; ASVS L2 and an independent penetration test
before general availability), [04](04-auth-and-tenant-isolation.md) L9 (break-glass rules),
[01](01-product-requirements.md) (performance and availability targets), MASTER-PLAN §8 items 4
and 11 (counsel; Greek by Gate G). Epic: #83.

## 1. Why a gate
Phases 1–3 run for the owner's own pilot. An external customer brings personal data the owner is
responsible for under GDPR, contractual promises (availability, support) and attackers with a
reason to try. Gate G asks for evidence that the platform and the operation behind it are ready:
an independent test of the security, written legal terms, a recovery that has been practised, a
load the platform is known to carry, and a controlled way for support to help a customer.

## 2. Dependency on Gate P
Gate P (#78, the pilot environment on AWS) is **not yet approved**. Three Gate G items need a
deployed environment: the penetration test, the production-scale load test and the real
disaster-recovery drill. Until Gate P, they can only be prepared and rehearsed locally. Proposed
order: approve Gate P, run the pilot, then close Gate G.

## 3. The items: what can be prepared here, what needs you
| # | Item | Prepared in the repository (no AWS, synthetic data) | Needs you or an outside party |
|---|---|---|---|
| G-1 | Support access (break-glass) | Build it (doc 04 L9, threat T16): a support request with a reason and ticket, approved by a tenant admin with MFA step-up; time-boxed (at most 4 h), read-only by default; a two-person emergency path; every action audited and shown to the tenant in a support log; automatic expiry | Who may be support staff; whether the emergency path is wanted at all |
| G-2 | ASVS L2 | A self-assessment: each Level 2 requirement of the chosen OWASP ASVS release, with the code, test or setting that meets it, or the gap and an issue for it. No row marked met without evidence | Which ASVS release (4.0.3 or 5.0); the independent sign-off, normally by the penetration tester |
| G-3 | Penetration test | A readiness pack: scope (web app, API, identity, tenant isolation), rules of engagement, synthetic test workspaces and accounts, the threat model, a remediation process (severity, time to fix, retest) | Choose and pay the provider; the test runs against a deployed environment (Gate P) |
| G-4 | Load test | Locust scenarios for the targets in doc 01 (dashboard first load p95 < 1.5 s, scenario re-run < 3 s, trial balance on 1M lines < 3 s, and the others), run against the local stack with a generated synthetic tenant; `make load-test`; a report | Target volumes for the first customers; the production-scale run on a deployed environment |
| G-5 | Disaster recovery | Extend the backup-restore runbook to a full recovery plan (database, object storage, secrets, identity, DNS), with the recovery steps timed locally against RPO 15 min and RTO 4 h | Confirm RPO and RTO (doc 01 says "to confirm"); the real drill on AWS |
| G-6 | Legal documents | Factual inputs for counsel: a data inventory (each module's personal data, purpose, legal basis to confirm, retention, location), a draft record of processing built from it, the list of services that would become sub-processors, and the retention table | Counsel writes the data processing agreement, the terms (including consumer terms for personal workspaces) and the privacy notice. Nothing here is legal advice |
| G-7 | Status page | A short comparison of options (hosted service or a static page) and the health signals it would show | Choose and open the service; no account is created by the developer |
| G-8 | Greek | A list of every Greek string added since M1, grouped by screen, for review | A native speaker reviews the wording (MASTER-PLAN §8 item 11) |

## 4. Proposed order of the in-repository work
One issue and one PR each, as for a milestone:
1. **G-1 Support access**: the only item that is product code; it also needs an ADR.
2. **G-4 Load test** harness and the first local report (it may find work before the pen test).
3. **G-2 ASVS L2** self-assessment, with issues for each gap found.
4. **G-5 Recovery plan** and local timing.
5. **G-3 Pen-test readiness pack**, **G-6 legal inputs**, **G-7 status page options**,
   **G-8 Greek list** (documents only).

## 5. Acceptance criteria (for the in-repository part)
- **AC-G1** Support access cannot read a tenant's data without an approved, unexpired grant;
  writes are refused unless the grant says otherwise; the tenant sees every grant and every
  access in its support log; isolation tests prove a grant for one tenant reads nothing of another.
- **AC-G2** Every ASVS L2 row is met with cited evidence, not applicable with a reason, or a gap
  with an open issue.
- **AC-G3** The load-test report states each doc 01 target, the measured p95, the data volume and
  the machine, locally; the scenarios are repeatable with one command.
- **AC-G4** The recovery plan covers every stateful part; the local timing is recorded.
- **AC-G5** The legal inputs list every table holding personal data (checked by a test against
  the models, so a new table cannot be missed).

## 6. Risks
- A local load test says little about AWS performance; it finds slow queries, not capacity.
- An ASVS self-assessment is not an independent review; it only prepares one.
- Legal documents written without counsel would be worse than none; only inputs are prepared here.

## 7. Decisions needed from you
1. Approve this brief (or change the order in §4).
2. Gate P first, as proposed in §2, or Gate G preparation in parallel with the pilot?
3. ASVS release: 4.0.3 or 5.0? (Proposed: 5.0, the current release.)
4. Confirm RPO 15 minutes and RTO 4 hours, or give other targets.
5. Support access: is the two-person emergency path wanted? (Proposed: yes, as doc 04 says.)
6. When you are ready: a penetration-test provider, counsel, and a native Greek reviewer.
