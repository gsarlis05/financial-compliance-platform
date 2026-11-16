import { useState } from "react";
import { Link } from "react-router";
import {
  useAccounts,
  useBankAccountMutations,
  useBankAccounts,
  useBankMutations,
  useBankStatements,
  useCounterparties,
  useLineHelp,
  useScope,
} from "../api/hooks";
import type { BankAccount, StatementLine } from "../api/types";
import { Loading, Page, ProblemMessage } from "../components/common";
import { useI18n } from "../i18n/I18n";
import type { MessageKey } from "../i18n/messages";
import { formatAmount } from "../money";

function today(): string {
  return new Date().toISOString().slice(0, 10);
}

/** Bank accounts, statement import, matching and reconciliation (M2-5). */
export function BankPage() {
  const { t } = useI18n();
  const accounts = useBankAccounts();
  const [chosen, setChosen] = useState("");
  const list = accounts.data ?? [];
  const current = list.find((a) => a.id === chosen) ?? list[0];
  return (
    <Page title={t("bank.title")}>
      <p className="muted">{t("bank.help")}</p>
      {accounts.isPending ? <Loading /> : null}
      <ProblemMessage error={accounts.error} />
      {list.length > 1 ? (
        <label className="form inline">
          {t("bank.account")}
          <select
            value={current?.id ?? ""}
            onChange={(e) => setChosen(e.target.value)}
          >
            {list.map((a) => (
              <option key={a.id} value={a.id}>
                {a.name}
              </option>
            ))}
          </select>
        </label>
      ) : null}
      {current ? <BankAccountView account={current} /> : null}
      {accounts.data ? <NewBankAccount /> : null}
    </Page>
  );
}

function NewBankAccount() {
  const { t, locale } = useI18n();
  const ledgerAccounts = useAccounts();
  const create = useBankAccountMutations();
  const [ledgerId, setLedgerId] = useState("");
  const [name, setName] = useState("");
  const [iban, setIban] = useState("");
  const assets = (ledgerAccounts.data ?? []).filter(
    (a) => a.type === "ASSET" && a.is_postable && a.status === "ACTIVE",
  );
  return (
    <form
      className="panel form inline"
      onSubmit={(e) => {
        e.preventDefault();
        create.mutate(
          { ledger_account_id: ledgerId, name, iban },
          { onSuccess: () => setName("") },
        );
      }}
    >
      <h2>{t("bank.new")}</h2>
      <label>
        {t("bank.ledgerAccount")}
        <select
          value={ledgerId}
          onChange={(e) => setLedgerId(e.target.value)}
          required
        >
          <option value="">—</option>
          {assets.map((a) => (
            <option key={a.id} value={a.id}>
              {a.code} · {locale === "el" && a.name_el ? a.name_el : a.name}
            </option>
          ))}
        </select>
      </label>
      <label>
        {t("bank.name")}
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          required
          maxLength={100}
        />
      </label>
      <label>
        IBAN
        <input
          value={iban}
          onChange={(e) => setIban(e.target.value)}
          maxLength={42}
        />
      </label>
      <ProblemMessage error={create.error} />
      <button type="submit" disabled={create.isPending}>
        {t("bank.create")}
      </button>
    </form>
  );
}

function BankAccountView({ account }: { account: BankAccount }) {
  const { t, locale } = useI18n();
  const [status, setStatus] = useState("UNMATCHED");
  const { imports, lines } = useBankStatements(account.id, status);
  const actions = useBankMutations(account.id);
  const [file, setFile] = useState<File | null>(null);
  const [format, setFormat] = useState("CAMT053");
  const [open, setOpen] = useState("");
  const last = account.last_reconciled;
  return (
    <section className="panel" aria-label={account.name}>
      <h2>
        {account.name} <span className="muted">{account.iban}</span>
      </h2>
      <p data-testid="last-reconciled">
        {last
          ? `${t("bank.lastReconciled")} ${last.as_of}: ${formatAmount(last.statement_balance, locale)}`
          : t("bank.neverReconciled")}
        {" · "}
        {account.unmatched_lines} {t("bank.unmatchedCount")}
      </p>

      <form
        className="form inline"
        onSubmit={(e) => {
          e.preventDefault();
          if (file) {
            actions.upload.mutate({ file, format });
          }
        }}
      >
        <label>
          {t("bank.file")}
          <input
            type="file"
            accept=".xml,.csv,.txt"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
          />
        </label>
        <label>
          {t("bank.format")}
          <select value={format} onChange={(e) => setFormat(e.target.value)}>
            <option value="CAMT053">ISO 20022 CAMT.053 (XML)</option>
            <option value="CSV">CSV</option>
          </select>
        </label>
        <button
          type="submit"
          className="primary"
          disabled={!file || actions.upload.isPending}
        >
          {t("bank.import")}
        </button>
      </form>
      <ProblemMessage error={actions.upload.error} />
      {actions.upload.data ? (
        <p
          className={
            actions.upload.data.status === "FAILED" ? "notice warn" : "notice"
          }
          role="status"
        >
          {actions.upload.data.status === "FAILED"
            ? `${t("bank.importFailed")} ${actions.upload.data.error}`
            : actions.upload.data.status === "PENDING"
              ? t("bank.importPending")
              : `${actions.upload.data.lines_created} ${t("bank.linesImported")}, ${actions.upload.data.lines_duplicate} ${t("bank.linesDuplicate")}`}
        </p>
      ) : null}
      {imports.data?.length ? (
        <details>
          <summary>
            {t("bank.imports")} ({imports.data.length})
          </summary>
          <ul>
            {imports.data.map((i) => (
              <li key={i.id}>
                {i.filename} · {i.status} · {i.lines_created}{" "}
                {t("bank.linesImported")}
                {i.error ? ` · ${i.error}` : ""}
              </li>
            ))}
          </ul>
        </details>
      ) : null}

      <div className="form inline">
        <label>
          {t("bank.show")}
          <select value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="UNMATCHED">{t("bank.status.UNMATCHED")}</option>
            <option value="MATCHED">{t("bank.status.MATCHED")}</option>
            <option value="IGNORED">{t("bank.status.IGNORED")}</option>
            <option value="">{t("bank.all")}</option>
          </select>
        </label>
        <button
          type="button"
          onClick={() => actions.autoMatch.mutate()}
          disabled={actions.autoMatch.isPending}
        >
          {t("bank.autoMatch")}
        </button>
        {actions.autoMatch.data ? (
          <span role="status">
            {actions.autoMatch.data.matched} {t("bank.matchedNow")}
          </span>
        ) : null}
      </div>
      <ProblemMessage error={lines.error ?? actions.autoMatch.error} />
      {lines.isPending ? <Loading /> : null}
      {lines.data && lines.data.length === 0 ? (
        <p className="muted">{t("bank.noLines")}</p>
      ) : null}
      {lines.data?.length ? (
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th scope="col">{t("je.date")}</th>
                <th scope="col">{t("je.description")}</th>
                <th scope="col">{t("bank.reference")}</th>
                <th scope="col" className="amount">
                  {t("bank.amount")}
                </th>
                <th scope="col">{t("bank.statusCol")}</th>
              </tr>
            </thead>
            <tbody>
              {lines.data.map((ln) => (
                <LineRow
                  key={ln.id}
                  line={ln}
                  open={open === ln.id}
                  onOpen={(o) => setOpen(o ? ln.id : "")}
                  accountId={account.id}
                />
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
      <Reconcile accountId={account.id} />
    </section>
  );
}

function LineRow({
  line,
  open,
  onOpen,
  accountId,
}: {
  line: StatementLine;
  open: boolean;
  onOpen: (open: boolean) => void;
  accountId: string;
}) {
  const { t, locale } = useI18n();
  const actions = useBankMutations(accountId);
  return (
    <>
      <tr>
        <td>{line.booking_date}</td>
        <td>
          {line.description}
          {line.counterparty_name ? (
            <span className="muted"> · {line.counterparty_name}</span>
          ) : null}
        </td>
        <td>{line.reference}</td>
        <td className="amount">{formatAmount(line.amount, locale)}</td>
        <td>
          {t(`bank.status.${line.status}` as MessageKey)}{" "}
          {line.status === "UNMATCHED" ? (
            <button
              type="button"
              className="link-button"
              aria-expanded={open}
              onClick={() => onOpen(!open)}
            >
              {t("bank.resolve")}
            </button>
          ) : (
            <button
              type="button"
              className="link-button"
              onClick={() => actions.unmatch.mutate(line.id)}
            >
              {t("bank.undo")}
            </button>
          )}
        </td>
      </tr>
      {open ? (
        <tr>
          <td colSpan={5}>
            <Resolve line={line} accountId={accountId} />
          </td>
        </tr>
      ) : null}
    </>
  );
}

function Resolve({
  line,
  accountId,
}: {
  line: StatementLine;
  accountId: string;
}) {
  const { t, locale } = useI18n();
  const { slug, entityId } = useScope();
  const { candidates, suggestions } = useLineHelp(line.id);
  const actions = useBankMutations(accountId);
  const ledgerAccounts = useAccounts();
  const parties = useCounterparties();
  const [account, setAccount] = useState("");
  const [party, setParty] = useState("");
  const [reference, setReference] = useState(line.reference);
  const [note, setNote] = useState("");
  const chosen = (ledgerAccounts.data ?? []).find((a) => a.id === account);
  const postable = (ledgerAccounts.data ?? []).filter(
    (a) => a.is_postable && a.status === "ACTIVE",
  );
  return (
    <div className="resolve">
      {candidates.data?.length ? (
        <div>
          <h3>{t("bank.candidates")}</h3>
          <ul>
            {candidates.data.map((c) => (
              <li key={c.journal_line_id}>
                {c.accounting_date} · {c.entry_ref} · {c.description}{" "}
                <button
                  type="button"
                  onClick={() =>
                    actions.match.mutate({
                      lineId: line.id,
                      journalLineId: c.journal_line_id,
                    })
                  }
                >
                  {t("bank.match")}
                </button>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      {suggestions.data?.length ? (
        <div>
          <h3>{t("bank.suggestions")}</h3>
          <ul>
            {suggestions.data.map((s) => (
              <li key={`${s.counterparty_id}:${s.reference}`}>
                {s.counterparty_code} · {s.reference} ·{" "}
                {formatAmount(s.open_amount, locale)}{" "}
                <button
                  type="button"
                  onClick={() => {
                    const control = (ledgerAccounts.data ?? []).find(
                      (a) => a.code === s.account_code,
                    );
                    setAccount(control?.id ?? "");
                    setParty(s.counterparty_id);
                    setReference(s.reference);
                  }}
                >
                  {t("bank.use")}
                </button>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      <form
        className="form inline"
        onSubmit={(e) => {
          e.preventDefault();
          actions.book.mutate({
            lineId: line.id,
            body: {
              account_id: account,
              counterparty_id: party || null,
              reference,
            },
          });
        }}
      >
        <label>
          {t("bank.bookTo")}
          <select
            value={account}
            onChange={(e) => setAccount(e.target.value)}
            required
          >
            <option value="">—</option>
            {postable.map((a) => (
              <option key={a.id} value={a.id}>
                {a.code} · {locale === "el" && a.name_el ? a.name_el : a.name}
              </option>
            ))}
          </select>
        </label>
        {chosen?.control_type ? (
          <label>
            {t("bank.counterparty")}
            <select
              value={party}
              onChange={(e) => setParty(e.target.value)}
              required
            >
              <option value="">—</option>
              {(parties.data ?? []).map((p) => (
                <option key={p.id} value={p.id}>
                  {p.code} · {p.name}
                </option>
              ))}
            </select>
          </label>
        ) : null}
        <label>
          {t("bank.reference")}
          <input
            value={reference}
            onChange={(e) => setReference(e.target.value)}
            maxLength={50}
          />
        </label>
        <button type="submit" disabled={actions.book.isPending || !account}>
          {t("bank.book")}
        </button>
      </form>
      {actions.book.data ? (
        <p role="status">
          <Link
            to={`/w/${slug}/e/${entityId}/entries/${actions.book.data.entry_id}`}
          >
            {t("bank.draftCreated")}
          </Link>
        </p>
      ) : null}
      <form
        className="inline-form"
        onSubmit={(e) => {
          e.preventDefault();
          actions.ignore.mutate({ lineId: line.id, note });
        }}
      >
        <label>
          <span className="visually-hidden">{t("bank.ignoreNote")}</span>
          <input
            placeholder={t("bank.ignoreNote")}
            value={note}
            onChange={(e) => setNote(e.target.value)}
            minLength={5}
            required
          />
        </label>
        <button type="submit">{t("bank.ignore")}</button>
      </form>
      <ProblemMessage
        error={
          actions.match.error ?? actions.book.error ?? actions.ignore.error
        }
      />
    </div>
  );
}

function Reconcile({ accountId }: { accountId: string }) {
  const { t, locale } = useI18n();
  const { reconcile } = useBankMutations(accountId);
  const [asOf, setAsOf] = useState(today());
  const [balance, setBalance] = useState("");
  const r = reconcile.data;
  return (
    <form
      className="form inline reconcile"
      onSubmit={(e) => {
        e.preventDefault();
        reconcile.mutate({ as_of: asOf, statement_balance: balance || null });
      }}
    >
      <h3>{t("bank.reconcile")}</h3>
      <label>
        {t("tb.asOf")}
        <input
          type="date"
          value={asOf}
          onChange={(e) => setAsOf(e.target.value)}
          required
        />
      </label>
      <label>
        {t("bank.statementBalance")}
        <input
          value={balance}
          onChange={(e) => setBalance(e.target.value)}
          placeholder={t("bank.fromStatement")}
          inputMode="decimal"
          pattern="^-?\d{1,15}(\.\d{1,2})?$"
        />
      </label>
      <button type="submit" disabled={reconcile.isPending}>
        {t("bank.reconcile")}
      </button>
      <ProblemMessage error={reconcile.error} />
      {r ? (
        <p
          className={r.reconciled ? "notice" : "notice warn"}
          role="status"
          data-testid="reconciliation"
        >
          {r.reconciled ? t("bank.reconciled") : t("bank.notReconciled")}{" "}
          {t("bank.statementBalance")}{" "}
          {formatAmount(r.statement_balance, locale)} ·{" "}
          {t("bank.ledgerBalance")} {formatAmount(r.ledger_balance, locale)} ·{" "}
          {t("bank.difference")} {formatAmount(r.difference, locale)} ·{" "}
          {r.unmatched_lines} {t("bank.unmatchedCount")}
        </p>
      ) : null}
    </form>
  );
}
