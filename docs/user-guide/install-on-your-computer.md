# Install version 1 on your computer

Version 1 runs entirely on your own computer. Your books, documents and sign-in stay there;
nothing is sent anywhere. It needs **Docker**:
- **macOS or Windows:** Docker Desktop. On Windows, run the commands below in **WSL**
  (Ubuntu).
- **Linux:** Docker Engine with the compose plugin.

Give Docker at least 4 GB of memory and 10 GB of disk.

## Install (once)
1. Get the platform: `git clone https://github.com/gsarlis05/financial-compliance-platform.git`
   and open a terminal in that folder.
2. Run `scripts/local/fcp.sh install --email you@example.com` (or
   `make local-install EMAIL=you@example.com`).
3. The command:
   - builds the platform;
   - starts it;
   - creates your sign-in;
   - prints a **first password**, once.
4. Open **http://localhost:8088** and sign in with that password. You are asked to choose your
   own password and to set up an **authenticator app** (for example Google Authenticator or
   1Password). From then on, signing in needs both.
5. Create your workspace. Then, in **Workspace settings**, turn on **One-person workspace**, so
   you can approve your own entries, budgets, packs and VAT reports.

## Every day
- **Start:** `scripts/local/fcp.sh start`. After a restart of the computer, Docker restarts the
  platform by itself.
- **Stop:** `scripts/local/fcp.sh stop`. Your data is kept.
- **Emails** the platform sends (alerts) appear at **http://localhost:8025**.

## Back up, and restore
- **Back up:** `scripts/local/fcp.sh backup` writes `backups/fcp-<date>.tar.gz`. It contains:
  - your books;
  - your sign-in;
  - your documents;
  - your secrets.

  Copy it to an encrypted disk or another safe place. Do this at least weekly, and before
  every upgrade (the upgrade does it for you).
- **Restore:** `scripts/local/fcp.sh restore backups/fcp-<date>.tar.gz` replaces everything with
  the backup, after you type `RESTORE`. It then checks the audit chain, the ledger and the
  reports. This also moves the platform to a new computer: install Docker there, get the code,
  and restore.

## Upgrade
When a new version is ready:
1. Run `git pull`.
2. Run `scripts/local/fcp.sh upgrade`. It:
   - backs up first;
   - rebuilds;
   - updates the database;
   - checks the books.

## Checks
`scripts/local/fcp.sh verify` re-checks:
- the audit trail's chain;
- the ledger's integrity (every entry balances, numbering has no gaps);
- that the reports agree with the ledger.

The same checks also run every night.

## If something goes wrong
- `scripts/local/fcp.sh status` shows which parts are running.
- `scripts/local/fcp.sh logs api` shows the last messages of a part (`api`, `worker`, `jobs`,
  `keycloak`, `postgres`).
