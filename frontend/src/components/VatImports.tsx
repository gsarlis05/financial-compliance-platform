// Imports for a VAT period (V1-2f): the customs declaration behind each import VAT claim. The
// declaration itself is a document attached to the import entry (Entries).
import { type SyntheticEvent, useState } from "react";
import { useDocuments } from "../api/hooks";
import { useVatImports } from "../api/vat";
import { ProblemMessage } from "./common";
import { useI18n } from "../i18n/I18n";
import { formatAmount } from "../money";

function DocumentChoice({
  entryId,
  value,
  onChange,
}: {
  entryId: string;
  value: string;
  onChange: (id: string) => void;
}) {
  const { t } = useI18n();
  const { list } = useDocuments(entryId);
  const documents = list.data ?? [];
  return (
    <label>
      {t("vat.imp.document")}
      <select value={value} required onChange={(e) => onChange(e.target.value)}>
        <option value="">—</option>
        {documents.map((d) => (
          <option key={d.id} value={d.id}>
            {d.filename}
          </option>
        ))}
      </select>
      {list.data && documents.length === 0 ? (
        <small>{t("vat.imp.noDocument")}</small>
      ) : null}
    </label>
  );
}

export function VatImports({
  periodStart,
  periodEnd,
  editable,
}: {
  periodStart: string;
  periodEnd: string;
  editable: boolean;
}) {
  const { t, locale } = useI18n();
  const { list, record, voidRecord } = useVatImports(periodStart, periodEnd);
  const [entryId, setEntryId] = useState("");
  const [reference, setReference] = useState("");
  const [date, setDate] = useState("");
  const [value, setValue] = useState("");
  const [vat, setVat] = useState("");
  const [documentId, setDocumentId] = useState("");
  const [reason, setReason] = useState("");
  const data = list.data;
  if (!data || (data.records.length === 0 && data.missing.length === 0)) {
    return null;
  }
  const decimal = (v: string) => v.trim().replace(",", ".");
  function save(event: SyntheticEvent) {
    event.preventDefault();
    record.mutate(
      {
        entry_id: entryId,
        customs_reference: reference,
        customs_date: date,
        customs_value: decimal(value),
        import_vat: decimal(vat),
        document_id: documentId,
      },
      {
        onSuccess: () => {
          setEntryId("");
          setReference("");
          setValue("");
          setVat("");
          setDocumentId("");
        },
      },
    );
  }
  return (
    <section aria-labelledby="vat-imports">
      <h3 id="vat-imports">{t("vat.imp.title")}</h3>
      <p className="muted">{t("vat.imp.help")}</p>
      {data.missing.length ? (
        <ul>
          {data.missing.map((m) => (
            <li key={m.entry_id} className="warn">
              {t("vat.imp.missing")} {m.entry_ref} ({m.date}):{" "}
              {formatAmount(m.claimed_vat, locale)}
            </li>
          ))}
        </ul>
      ) : null}
      {data.records.length ? (
        <ul>
          {data.records.map((r) => (
            <li key={r.id} className={r.voided ? "muted" : undefined}>
              {r.entry_ref} · {r.customs_reference} · {r.customs_date} ·{" "}
              {t("vat.imp.value")} {formatAmount(r.customs_value, locale)} ·{" "}
              {t("vat.imp.vat")} {formatAmount(r.import_vat, locale)} ·{" "}
              {r.document_name}
              {r.voided ? ` · ${t("vat.imp.voided")}: ${r.void_reason}` : ""}
              {editable && !r.voided ? (
                <>
                  {" "}
                  <input
                    aria-label={`${t("vat.imp.voidReason")} ${r.customs_reference}`}
                    placeholder={t("vat.imp.voidReason")}
                    value={reason}
                    maxLength={500}
                    onChange={(e) => setReason(e.target.value)}
                  />
                  <button
                    type="button"
                    className="link-button"
                    disabled={!reason.trim() || voidRecord.isPending}
                    onClick={() => voidRecord.mutate({ id: r.id, reason })}
                  >
                    {t("vat.imp.void")}
                  </button>
                </>
              ) : null}
            </li>
          ))}
        </ul>
      ) : null}
      {editable && data.missing.length ? (
        <form className="form inline" onSubmit={save}>
          <label>
            {t("vat.entry")}
            <select
              value={entryId}
              required
              onChange={(e) => {
                setEntryId(e.target.value);
                setDocumentId("");
              }}
            >
              <option value="">—</option>
              {data.missing.map((m) => (
                <option key={m.entry_id} value={m.entry_id}>
                  {m.entry_ref} · {m.description}
                </option>
              ))}
            </select>
          </label>
          <label>
            {t("vat.imp.reference")}
            <input
              required
              maxLength={50}
              value={reference}
              onChange={(e) => setReference(e.target.value)}
            />
          </label>
          <label>
            {t("vat.imp.date")}
            <input
              type="date"
              required
              value={date}
              onChange={(e) => setDate(e.target.value)}
            />
          </label>
          <label>
            {t("vat.imp.value")}
            <input
              inputMode="decimal"
              required
              value={value}
              onChange={(e) => setValue(e.target.value)}
            />
          </label>
          <label>
            {t("vat.imp.vat")}
            <input
              inputMode="decimal"
              required
              value={vat}
              onChange={(e) => setVat(e.target.value)}
            />
          </label>
          {entryId ? (
            <DocumentChoice
              entryId={entryId}
              value={documentId}
              onChange={setDocumentId}
            />
          ) : null}
          <button type="submit" disabled={record.isPending || !documentId}>
            {t("vat.imp.record")}
          </button>
        </form>
      ) : null}
      <ProblemMessage error={record.error ?? voidRecord.error} />
    </section>
  );
}
