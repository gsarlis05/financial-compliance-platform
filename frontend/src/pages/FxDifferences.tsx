// Exchange differences (V1-2h2, #230): the foreign-currency positions on a date, revalued at the
// closing rate (unrealised) or cleared once settled (realised), and one draft entry for them.
// The draft follows the normal approval and posting: nothing is posted here.
import { useState } from "react";
import { Link } from "react-router";
import { type FxPosition, useFxPositions } from "../api/currency";
import { useCounterparties, useScope } from "../api/hooks";
import { Loading, Page, ProblemMessage } from "../components/common";
import { useI18n } from "../i18n/I18n";
import type { MessageKey } from "../i18n/messages";
import { formatAmount } from "../money";

function lastDayOfLastMonth(): string {
  const now = new Date();
  const last = new Date(Date.UTC(now.getFullYear(), now.getMonth(), 0));
  return last.toISOString().slice(0, 10);
}

export function FxDifferencesPage() {
  const { t, locale } = useI18n();
  const { slug, entityId } = useScope();
  const [on, setOn] = useState(lastDayOfLastMonth);
  const { list, prepare } = useFxPositions(on);
  const parties = useCounterparties();
  const partyName = (id: string | null) =>
    id ? (parties.data?.find((c) => c.id === id)?.name ?? "") : "";
  const money = (value: string | null) =>
    value === null ? "—" : formatAmount(value, locale);
  const entryLink = (id: string) => `/w/${slug}/e/${entityId}/entries/${id}`;
  const data = list.data;
  const due = data?.positions.some(
    (p) => p.kind === "UNREALISED" || p.kind === "REALISED",
  );
  const kindLabel = (p: FxPosition) =>
    p.kind ? t(`fxd.kind.${p.kind}` as MessageKey) : t("fxd.kind.none");

  return (
    <Page title={t("fxd.title")}>
      <p className="muted">{t("fxd.help")}</p>
      <label>
        {t("fxd.on")}
        <input
          type="date"
          value={on}
          onChange={(e) => setOn(e.target.value)}
          required
        />
      </label>
      {list.isPending ? <Loading /> : null}
      <ProblemMessage error={list.error} />
      {data ? (
        <>
          {data.fx_account_id === null ? (
            <p className="notice warn">{t("fxd.noAccount")}</p>
          ) : null}
          {data.missing_rates.length ? (
            <p className="notice warn">
              {t("fxd.missingRates").replace(
                "{currencies}",
                data.missing_rates.join(", "),
              )}
            </p>
          ) : null}
          {data.waiting_entry_id ? (
            <p className="notice" role="status">
              {t("fxd.waiting")}{" "}
              <Link to={entryLink(data.waiting_entry_id)}>
                {t("fxd.openEntry")}
              </Link>
            </p>
          ) : null}
          {data.positions.length === 0 ? (
            <p className="muted">{t("fxd.none")}</p>
          ) : (
            <div className="table-scroll">
              <table aria-label={t("fxd.title")}>
                <thead>
                  <tr>
                    <th scope="col">{t("fxd.account")}</th>
                    <th scope="col">{t("fxd.party")}</th>
                    <th scope="col">{t("fxd.currency")}</th>
                    <th scope="col" className="amount">
                      {t("fxd.foreign")}
                    </th>
                    <th scope="col" className="amount">
                      {t("fxd.euros")}
                    </th>
                    <th scope="col" className="amount">
                      {t("fxd.rate")}
                    </th>
                    <th scope="col" className="amount">
                      {t("fxd.revalued")}
                    </th>
                    <th scope="col" className="amount">
                      {t("fxd.difference")}
                    </th>
                    <th scope="col">{t("fxd.kind")}</th>
                  </tr>
                </thead>
                <tbody>
                  {data.positions.map((p) => (
                    <tr
                      key={`${p.account_id}-${p.counterparty_id ?? ""}-${p.currency}`}
                    >
                      <td>
                        {p.account_code} · {p.account_name}
                      </td>
                      <td>{partyName(p.counterparty_id)}</td>
                      <td>{p.currency}</td>
                      <td className="amount">{money(p.foreign)}</td>
                      <td className="amount">{money(p.euros)}</td>
                      <td className="amount" title={p.rate_source || undefined}>
                        {p.rate ?? "—"}
                      </td>
                      <td className="amount">{money(p.revalued)}</td>
                      <td className="amount">{money(p.difference)}</td>
                      <td>{kindLabel(p)}</td>
                    </tr>
                  ))}
                </tbody>
                <tfoot>
                  <tr>
                    <th scope="row" colSpan={7}>
                      {t("fxd.totals")}
                    </th>
                    <td className="amount" colSpan={2}>
                      {t("fxd.unrealisedTotal")} {money(data.unrealised)} ·{" "}
                      {t("fxd.realisedTotal")} {money(data.realised)}
                    </td>
                  </tr>
                </tfoot>
              </table>
            </div>
          )}
          <p className="muted">{t("fxd.sign")}</p>
          <div className="actions">
            <button
              type="button"
              className="primary"
              disabled={
                !due ||
                !!data.waiting_entry_id ||
                data.fx_account_id === null ||
                prepare.isPending
              }
              onClick={() => prepare.mutate()}
            >
              {t("fxd.prepare")}
            </button>
          </div>
          {prepare.data ? (
            <p role="status">
              {t("fxd.prepared")}{" "}
              <Link to={entryLink(prepare.data.id)}>{t("fxd.openEntry")}</Link>
            </p>
          ) : null}
          <ProblemMessage error={prepare.error} />
        </>
      ) : null}
    </Page>
  );
}
