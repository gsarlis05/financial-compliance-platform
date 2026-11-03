import { type SyntheticEvent, useState } from "react";
import { useCounterparties, useCounterpartyMutations } from "../api/hooks";
import type { CounterpartyKind } from "../api/types";
import { FieldError, Loading, Page, ProblemMessage } from "../components/common";
import { useI18n } from "../i18n/I18n";
import type { MessageKey } from "../i18n/messages";

const KINDS: CounterpartyKind[] = ["CUSTOMER", "SUPPLIER", "BOTH", "EMPLOYEE", "TAX_AUTHORITY", "LENDER"];
const EMPTY = { code: "", name: "", kind: "CUSTOMER" as CounterpartyKind, vat_no: "", email: "", payment_terms_days: 30 };

export function CounterpartiesPage() {
  const { t } = useI18n();
  const list = useCounterparties();
  const { create } = useCounterpartyMutations();
  const [form, setForm] = useState(EMPTY);

  function add(event: SyntheticEvent) {
    event.preventDefault();
    create.mutate(form, { onSuccess: () => setForm({ ...EMPTY, kind: form.kind }) });
  }

  return (
    <Page title={t("cp.title")}>
      {list.isPending ? <Loading /> : null}
      <ProblemMessage error={list.error} />
      {list.data?.length === 0 ? <p>{t("cp.none")}</p> : null}
      {list.data?.length ? (
        <table>
          <thead>
            <tr>
              <th scope="col">{t("cp.code")}</th>
              <th scope="col">{t("cp.name")}</th>
              <th scope="col">{t("cp.kind")}</th>
              <th scope="col">{t("cp.vat")}</th>
              <th scope="col" className="amount">
                {t("cp.terms")}
              </th>
            </tr>
          </thead>
          <tbody>
            {list.data.map((c) => (
              <tr key={c.id} className={c.status === "ACTIVE" ? "" : "muted"}>
                <td>{c.code}</td>
                <td>{c.name}</td>
                <td>{t(`cp.kind.${c.kind}` as MessageKey)}</td>
                <td>{c.vat_no}</td>
                <td className="amount">{c.payment_terms_days}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : null}
      <form className="panel form inline" onSubmit={add}>
        <h2>{t("cp.add")}</h2>
        <label>
          {t("cp.code")}
          <input value={form.code} onChange={(e) => setForm({ ...form, code: e.target.value })} required maxLength={30} />
          <FieldError error={create.error} field="code" />
        </label>
        <label>
          {t("cp.name")}
          <input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} required maxLength={200} />
        </label>
        <label>
          {t("cp.kind")}
          <select value={form.kind} onChange={(e) => setForm({ ...form, kind: e.target.value as CounterpartyKind })}>
            {KINDS.map((k) => (
              <option key={k} value={k}>
                {t(`cp.kind.${k}`)}
              </option>
            ))}
          </select>
        </label>
        <label>
          {t("cp.vat")}
          <input value={form.vat_no} onChange={(e) => setForm({ ...form, vat_no: e.target.value })} maxLength={30} />
        </label>
        <label>
          {t("cp.email")}
          <input type="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} />
        </label>
        <label>
          {t("cp.terms")}
          <input
            type="number"
            min={0}
            max={365}
            value={form.payment_terms_days}
            onChange={(e) => setForm({ ...form, payment_terms_days: Number(e.target.value) })}
          />
        </label>
        <ProblemMessage error={create.error} />
        <button type="submit" disabled={create.isPending}>
          {t("cp.add")}
        </button>
      </form>
    </Page>
  );
}
