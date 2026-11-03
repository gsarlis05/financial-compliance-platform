import { type SyntheticEvent, useState } from "react";
import { useAccountMutations, useAccounts } from "../api/hooks";
import type { Account } from "../api/types";
import { FieldError, Loading, Page, ProblemMessage } from "../components/common";
import { useI18n } from "../i18n/I18n";

function depth(account: Account, byId: Map<string, Account>): number {
  let level = 0;
  let parent = account.parent_id ? byId.get(account.parent_id) : undefined;
  while (parent) {
    level += 1;
    parent = parent.parent_id ? byId.get(parent.parent_id) : undefined;
  }
  return level;
}

export function AccountsPage() {
  const { t, locale } = useI18n();
  const accounts = useAccounts();
  const { applyTemplate, create } = useAccountMutations();
  const [template, setTemplate] = useState("cy_business");
  const [form, setForm] = useState({ code: "", name: "", type: "EXPENSE", parent_code: "" });
  const byId = new Map((accounts.data ?? []).map((a) => [a.id, a]));

  function add(event: SyntheticEvent) {
    event.preventDefault();
    create.mutate(
      { code: form.code, name: form.name, type: form.type, ...(form.parent_code ? { parent_code: form.parent_code } : {}) },
      { onSuccess: () => setForm({ code: "", name: "", type: form.type, parent_code: form.parent_code }) },
    );
  }

  return (
    <Page title={t("acc.title")}>
      {accounts.isPending ? <Loading /> : null}
      <ProblemMessage error={accounts.error ?? applyTemplate.error} />
      {accounts.data?.length === 0 ? (
        <div className="panel">
          <p>{t("acc.empty")}</p>
          <label>
            <span className="visually-hidden">{t("acc.apply")}</span>
            <select value={template} onChange={(e) => setTemplate(e.target.value)}>
              <option value="cy_business">{t("acc.template.cy_business")}</option>
              <option value="personal">{t("acc.template.personal")}</option>
            </select>
          </label>{" "}
          <button onClick={() => applyTemplate.mutate(template)} disabled={applyTemplate.isPending}>
            {t("acc.apply")}
          </button>
        </div>
      ) : null}
      {accounts.data?.length ? (
        <table>
          <thead>
            <tr>
              <th scope="col">{t("acc.code")}</th>
              <th scope="col">{t("acc.name")}</th>
              <th scope="col">{t("acc.type")}</th>
              <th scope="col">{t("acc.side")}</th>
              <th scope="col">{t("acc.status")}</th>
            </tr>
          </thead>
          <tbody>
            {accounts.data.map((a) => (
              <tr key={a.id} className={a.is_postable ? "" : "heading-row"}>
                <td>{a.code}</td>
                <td style={{ paddingInlineStart: `${0.5 + depth(a, byId) * 1.25}rem` }}>
                  {locale === "el" && a.name_el ? a.name_el : a.name}
                  {a.is_postable ? null : <span className="muted"> · {t("acc.heading")}</span>}
                </td>
                <td>{a.type}</td>
                <td>{a.normal_side}</td>
                <td>{a.status}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : null}
      {accounts.data?.length ? (
        <form className="panel form inline" onSubmit={add}>
          <h2>{t("acc.add")}</h2>
          <label>
            {t("acc.code")}
            <input value={form.code} onChange={(e) => setForm({ ...form, code: e.target.value })} required />
            <FieldError error={create.error} field="code" />
          </label>
          <label>
            {t("acc.name")}
            <input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} required />
          </label>
          <label>
            {t("acc.type")}
            <select value={form.type} onChange={(e) => setForm({ ...form, type: e.target.value })}>
              {["ASSET", "LIABILITY", "EQUITY", "INCOME", "EXPENSE"].map((type) => (
                <option key={type}>{type}</option>
              ))}
            </select>
            <FieldError error={create.error} field="type" />
          </label>
          <label>
            {t("acc.parent")}
            <input value={form.parent_code} onChange={(e) => setForm({ ...form, parent_code: e.target.value })} />
            <FieldError error={create.error} field="parent_code" />
          </label>
          <ProblemMessage error={create.error} />
          <button type="submit" disabled={create.isPending}>
            {t("acc.add")}
          </button>
        </form>
      ) : null}
    </Page>
  );
}
