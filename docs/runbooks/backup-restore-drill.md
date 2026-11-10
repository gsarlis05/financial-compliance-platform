# Runbook: backup and restore drill

A backup is only proven when it has been restored. Run this drill before the pilot starts, then
every quarter, and after any change to the database setup. Record each run in the table at the end.

## Local drill (any time; changes nothing)
```
make services
make restore-drill
```
The script:
1. takes a consistent backup of the local database (`pg_dump`, one snapshot);
2. restores it into a scratch database (`fcp_restore_drill`);
3. compares the row count of every table with the snapshot;
4. runs the application's own checks on the restored copy: the audit chain (`audit_verify`), the
   ledger (`ledger_integrity_check`) and the reporting actuals (`actuals_verify`);
5. removes the scratch database and the backup file.

It stops with `FAILED` and the reason if any step does not hold. A pass ends with the timings.

## Pilot drill (after the environment exists; needs the owner's approval)
The pilot database has two kinds of backup: point-in-time recovery (14 days) and AWS Backup
copies in a locked vault (daily for 35 days, monthly for a year).

1. **Agree the drill** with the owner: which recovery point, and when.
2. **Restore to a new instance**, never over the running database:
   - AWS Backup → the vault `fcp-pilot` → choose the recovery point → *Restore*, into the same
     data subnets and security group, with a new identifier such as `fcp-pilot-drill`;
   - or RDS → *Restore to point in time* for a moment inside the last 14 days.
3. **Run the checks against the restored instance** with the `ops` task definition, overriding
   `POSTGRES_HOST` to the restored instance: `audit_verify`, `ledger_integrity_check` and
   `actuals_verify`. All three must exit with 0.
4. **Compare** the latest audit event and the latest posted entry with what the owner expects
   for that moment.
5. **Delete the restored instance** and record the run below.

A failed backup or restore job raises an alarm on the pilot alarm topic.

## Targets for the pilot
| | Target |
|---|---|
| Recovery point (how much work may be lost) | 5 minutes (point-in-time recovery) |
| Recovery time (how long a restore may take) | 4 hours |

## Drill record
| Date | Where | Backup | Restore | Result | By |
|---|---|---|---|---|---|
| 2026-11-10 | Local stack, synthetic data (82 tables, 62,911 rows) | 5 s | 2 s | Passed: identical row counts; audit chain, ledger and actuals checks passed | Claude (development) |
