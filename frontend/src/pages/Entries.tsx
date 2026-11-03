import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router";
import {
  type EntryAction,
  useAccounts,
  useCounterparties,
  useDimensions,
  useEntries,
  useEntry,
  useEntryMutations,
  useFiscalYears,
  useMe,
  useScope,
} from "../api/hooks";
import type { EntryInput, JournalEntry } from "../api/types";
import { Loading, Page, ProblemMessage, StatusBadge } from "../components/common";
import { useI18n } from "../i18n/I18n";
import { formatAmount } from "../money";
import { EntryForm } from "./EntryForm";

function EntryTable({ entries }: { entries: JournalEntry[] }) {
  const { t, locale } = useI18n();
  const { slug, entityId } = useScope();
  if (!entries.length) {
    return <p className="muted">{t("je.none")}</p>;
  }
  return (
    <table>
      <thead>
        <tr>
          <th scope="col">{t("je.date")}</th>
          <th scope="col">{t("je.number")}</th>
          <th scope="col">{t("je.description")}</th>
          <th scope="col" className="amount">
            {t("je.amount")}
          </th>
          <th scope="col">{t("je.status")}</th>
        </tr>
      </thead>
      <tbody>
        {entries.map((e) => (
          <tr key={e.id}>
            <td>{e.accounting_date}</td>
            <td>{e.entry_no ? `${e.journal}-${e.entry_no}` : "—"}</td>
            <td>
              <Link to={`/w/${slug}/e/${entityId}/entries/${e.id}`}>{e.description}</Link>
            </td>
            <td className="amount">{formatAmount(e.total_debit, locale)}</td>
            <td>
              <StatusBadge prefix="je.status" status={e.status} />
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export function EntriesPage() {
  const { t } = useI18n();
  const { slug, entityId } = useScope();
  const entries = useEntries();
  return (
    <Page
      title={t("je.title")}
      actions={
        <Link className="button primary" to={`/w/${slug}/e/${entityId}/entries/new`}>
          {t("je.new")}
        </Link>
      }
    >
      {entries.isPending ? <Loading /> : <EntryTable entries={entries.data ?? []} />}
      <ProblemMessage error={entries.error} />
    </Page>
  );
}

export function ApprovalsPage() {
  const { t } = useI18n();
  const submitted = useEntries("SUBMITTED");
  const approved = useEntries("APPROVED");
  return (
    <Page title={t("ap.title")}>
      <h2>{t("ap.toApprove")}</h2>
      {submitted.isPending ? <Loading /> : <EntryTable entries={submitted.data ?? []} />}
      <h2>{t("ap.toPost")}</h2>
      {approved.isPending ? <Loading /> : <EntryTable entries={approved.data ?? []} />}
      <ProblemMessage error={submitted.error ?? approved.error} />
    </Page>
  );
}

export function NewEntryPage() {
  const { t } = useI18n();
  const accounts = useAccounts();
  const dimensions = useDimensions();
  const counterparties = useCounterparties();
  const years = useFiscalYears();
  const { save, act } = useEntryMutations();
  const navigate = useNavigate();
  const { slug, entityId } = useScope();
  if (accounts.isPending || years.isPending) {
    return <Loading />;
  }
  function onSave(body: EntryInput, submit: boolean) {
    save.mutate(
      { body },
      {
        onSuccess: (entry) => {
          const go = () => void navigate(`/w/${slug}/e/${entityId}/entries/${entry.id}`);
          if (submit) {
            act.mutate({ id: entry.id, action: "submit" }, { onSettled: go });
          } else {
            go();
          }
        },
      },
    );
  }
  return (
    <Page title={t("je.new")}>
      <EntryForm
        accounts={accounts.data ?? []}
        dimensions={dimensions.data ?? []}
        counterparties={counterparties.data ?? []}
        fiscalYears={years.data ?? []}
        saving={save.isPending || act.isPending}
        error={save.error}
        onSave={onSave}
      />
    </Page>
  );
}

/** Read-only view with the workflow actions allowed for the entry's status. A posted entry is
 * never editable; its only action is "Reverse" (AC-F2). */
export function EntryActions({ entry, myId, onAct }: {
  entry: JournalEntry;
  myId: string | undefined;
  onAct: (action: EntryAction, reason?: string) => void;
}) {
  const { t } = useI18n();
  const [reason, setReason] = useState("");
  const withReason = (action: EntryAction) => (reason.trim().length >= 5 ? onAct(action, reason) : undefined);
  switch (entry.status) {
    case "DRAFT":
    case "REJECTED":
      return (
        <div className="actions">
          <button className="primary" onClick={() => onAct("submit")}>
            {t("je.submit")}
          </button>
          <button onClick={() => onAct("void")}>{t("je.void")}</button>
        </div>
      );
    case "SUBMITTED":
      return (
        <div className="actions">
          <button className="primary" disabled={myId === entry.prepared_by_id} onClick={() => onAct("approve")}>
            {t("je.approve")}
          </button>
          {/* Without an approval policy (e.g. personal books) a submitted entry can be posted;
              otherwise the server explains that approval is required. */}
          <button onClick={() => onAct("post")}>{t("je.post")}</button>
          <label>
            <span className="visually-hidden">{t("je.rejectReason")}</span>
            <input placeholder={t("je.rejectReason")} value={reason} onChange={(e) => setReason(e.target.value)} />
          </label>
          <button onClick={() => withReason("reject")}>{t("je.reject")}</button>
        </div>
      );
    case "APPROVED":
      return (
        <div className="actions">
          <button className="primary" onClick={() => onAct("post")}>
            {t("je.post")}
          </button>
        </div>
      );
    case "POSTED":
      return (
        <div className="actions">
          <p className="notice">{t("je.postedReadOnly")}</p>
          {entry.reversed_by_entry_id || entry.entry_type === "REVERSAL" ? null : (
            <>
              <label>
                <span className="visually-hidden">{t("je.reverseReason")}</span>
                <input placeholder={t("je.reverseReason")} value={reason} onChange={(e) => setReason(e.target.value)} />
              </label>
              <button onClick={() => withReason("reverse")}>{t("je.reverse")}</button>
            </>
          )}
        </div>
      );
    default:
      return null;
  }
}

export function EntryDetailPage() {
  const { t, locale } = useI18n();
  const { entryId = "" } = useParams();
  const { slug, entityId } = useScope();
  const entry = useEntry(entryId);
  const me = useMe();
  const accounts = useAccounts();
  const dimensions = useDimensions();
  const counterparties = useCounterparties();
  const years = useFiscalYears();
  const { save, act } = useEntryMutations();
  const navigate = useNavigate();
  const [editing, setEditing] = useState(false);
  if (entry.isPending) {
    return <Loading />;
  }
  if (!entry.data) {
    return <ProblemMessage error={entry.error} />;
  }
  const e = entry.data;
  const editable = e.status === "DRAFT" || e.status === "REJECTED";
  const names = new Map((accounts.data ?? []).map((a) => [a.id, locale === "el" && a.name_el ? a.name_el : a.name]));
  const onAct = (action: EntryAction, reason?: string) =>
    act.mutate(
      { id: e.id, action, ...(reason ? { reason } : {}) },
      {
        onSuccess: (result) => {
          if (action === "reverse") {
            void navigate(`/w/${slug}/e/${entityId}/entries/${result.id}`);
          }
        },
      },
    );
  return (
    <Page
      title={e.description}
      actions={editable && !editing ? <button onClick={() => setEditing(true)}>{t("je.edit")}</button> : null}
    >
      <p>
        <StatusBadge prefix="je.status" status={e.status} /> {e.accounting_date}
        {e.entry_no ? ` · ${e.journal}-${e.entry_no}` : ""}
        {e.unlock_request_id ? <span className="badge badge-warn"> {t("je.restated")}</span> : null}
      </p>
      {e.rejection_reason ? <p className="notice warn">{e.rejection_reason}</p> : null}
      {e.reverses_entry_id ? (
        <p>
          {t("je.reverses")}: <Link to={`/w/${slug}/e/${entityId}/entries/${e.reverses_entry_id}`}>↗</Link>
        </p>
      ) : null}
      {e.reversed_by_entry_id ? (
        <p>
          {t("je.reversedBy")}: <Link to={`/w/${slug}/e/${entityId}/entries/${e.reversed_by_entry_id}`}>↗</Link>
        </p>
      ) : null}
      {editing ? (
        <EntryForm
          accounts={accounts.data ?? []}
          dimensions={dimensions.data ?? []}
          counterparties={counterparties.data ?? []}
          fiscalYears={years.data ?? []}
          initial={e}
          saving={save.isPending}
          error={save.error}
          onSave={(body, submit) =>
            save.mutate(
              { id: e.id, body },
              {
                onSuccess: () => {
                  setEditing(false);
                  if (submit) {
                    onAct("submit");
                  }
                },
              },
            )
          }
        />
      ) : (
        <>
          <table>
            <thead>
              <tr>
                <th scope="col">{t("je.account")}</th>
                <th scope="col" className="amount">
                  {t("je.debit")}
                </th>
                <th scope="col" className="amount">
                  {t("je.credit")}
                </th>
                <th scope="col">{t("je.memo")}</th>
              </tr>
            </thead>
            <tbody>
              {e.lines.map((l) => (
                <tr key={l.line_no}>
                  <td>
                    {l.account_code} · {names.get(l.account_id) ?? ""}
                  </td>
                  <td className="amount">{l.debit === "0.00" ? "" : formatAmount(l.debit, locale)}</td>
                  <td className="amount">{l.credit === "0.00" ? "" : formatAmount(l.credit, locale)}</td>
                  <td>
                    {l.memo}
                    {l.counterparty_code ? (
                      <span className="tag">
                        {l.counterparty_code}
                        {l.reference ? ` · ${l.reference}` : ""}
                      </span>
                    ) : null}
                    {l.dimensions.length ? (
                      <span className="tags">
                        {l.dimensions.map((d) => (
                          <span key={d.dimension_id} className="tag" title={d.value_name}>
                            {d.dimension_code}: {d.value_code}
                          </span>
                        ))}
                      </span>
                    ) : null}
                  </td>
                </tr>
              ))}
            </tbody>
            <tfoot>
              <tr>
                <th scope="row">{t("je.totals")}</th>
                <td className="amount">{formatAmount(e.total_debit, locale)}</td>
                <td className="amount">{formatAmount(e.total_credit, locale)}</td>
                <td />
              </tr>
            </tfoot>
          </table>
          <EntryActions entry={e} myId={me.data?.id} onAct={onAct} />
        </>
      )}
      <ProblemMessage error={act.error} />
    </Page>
  );
}
