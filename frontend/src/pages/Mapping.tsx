import { useState } from "react";
import { useMapping, useMappingMutations, useTaxonomy } from "../api/hooks";
import { Loading, Page, ProblemMessage } from "../components/common";
import { useI18n } from "../i18n/I18n";
import { formatAmount } from "../money";

export function MappingPage() {
  const { t, locale } = useI18n();
  const [asOf, setAsOf] = useState(new Date().toISOString().slice(0, 10));
  const taxonomy = useTaxonomy();
  const { rows, completeness } = useMapping(asOf);
  const { set, applyDefaults } = useMappingMutations();
  const lines = taxonomy.data ?? [];
  const label = (code: string) => {
    const line = lines.find((l) => l.code === code);
    return line ? `${line.code} · ${locale === "el" && line.name_el ? line.name_el : line.name}` : code;
  };
  const c = completeness.data;
  return (
    <Page
      title={t("map.title")}
      actions={
        <button type="button" disabled={applyDefaults.isPending} onClick={() => applyDefaults.mutate()}>
          {t("map.applyDefaults")}
        </button>
      }
    >
      <p className="muted">{t("map.help")}</p>
      <label className="form inline">
        {t("tb.asOf")}
        <input type="date" value={asOf} onChange={(e) => setAsOf(e.target.value)} />
      </label>
      <ProblemMessage error={rows.error ?? completeness.error ?? set.error ?? applyDefaults.error} />
      {c ? (
        <p className={c.complete ? "notice" : "notice warn"} data-testid="mapping-status">
          {c.complete
            ? t("map.complete")
            : `${t("map.blocking")} ${c.unmapped_blocking.map((r) => r.account_code).join(", ")}`}
          {c.unmapped_warning.length
            ? ` ${t("map.warning")} ${c.unmapped_warning.map((r) => r.account_code).join(", ")}`
            : ""}
        </p>
      ) : null}
      {rows.isPending || taxonomy.isPending ? <Loading /> : null}
      {rows.data?.length ? (
        <table>
          <thead>
            <tr>
              <th scope="col">{t("acc.code")}</th>
              <th scope="col">{t("acc.name")}</th>
              <th scope="col" className="amount">
                {t("map.balance")}
              </th>
              <th scope="col">{t("map.line")}</th>
            </tr>
          </thead>
          <tbody>
            {rows.data.map((r) => (
              <tr key={r.account_id} className={r.line_code === null && r.balance !== "0.00" ? "warn" : ""}>
                <td>{r.account_code}</td>
                <td>{r.account_name}</td>
                <td className="amount">{r.has_activity ? formatAmount(r.balance, locale) : ""}</td>
                <td>
                  <select
                    aria-label={`${t("map.line")} ${r.account_code}`}
                    value={r.line_code ?? ""}
                    disabled={set.isPending}
                    onChange={(e) => set.mutate({ accountId: r.account_id, lineCode: e.target.value || null })}
                  >
                    <option value="">{t("map.unmapped")}</option>
                    {lines
                      .filter((l) => l.account_types.includes(r.account_type))
                      .map((l) => (
                        <option key={l.code} value={l.code}>
                          {label(l.code)}
                        </option>
                      ))}
                  </select>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : null}
    </Page>
  );
}
