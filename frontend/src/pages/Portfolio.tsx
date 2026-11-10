import { useState } from "react";
import { Link } from "react-router";
import {
  type PortfolioPart,
  type PortfolioRow,
  usePortfolio,
} from "../api/portfolio";
import { useScope } from "../api/hooks";
import { Loading, Page, ProblemMessage } from "../components/common";
import { useI18n } from "../i18n/I18n";
import { formatAmount } from "../money";
import { formatCard, lastMonth } from "./Dashboard";

function Missing({ part }: { part: PortfolioPart<unknown> }) {
  const { t } = useI18n();
  return (
    <span className="muted">
      {part.status === "denied" ? t("dash.denied") : part.reason}
    </span>
  );
}

const KPIS = ["GROSS_MARGIN", "CURRENT_RATIO", "DSO"];

function Row({ row }: { row: PortfolioRow }) {
  const { t, locale } = useI18n();
  const { slug } = useScope();
  const cards = new Map((row.kpis.data.cards ?? []).map((c) => [c.key, c]));
  const g = row.goals.data;
  return (
    <tr>
      <th scope="row">
        <Link to={`/w/${slug}/e/${row.entity_id}/dashboard`}>
          {row.legal_name}
        </Link>
      </th>
      <td className="num">
        {row.cash.status === "ok" ? (
          <>
            {formatAmount(row.cash.data.opening ?? "0", locale)}
            <br />
            <span className="muted">
              {row.cash.data.first_shortfall
                ? `${t("dash.shortfall")} ${row.cash.data.first_shortfall}`
                : t("dash.noShortfall")}
            </span>
          </>
        ) : (
          <Missing part={row.cash} />
        )}
      </td>
      {KPIS.map((key) => {
        const c = cards.get(key);
        return (
          <td key={key} className="num">
            {row.kpis.status !== "ok" ? (
              key === "GROSS_MARGIN" ? (
                <Missing part={row.kpis} />
              ) : null
            ) : c ? (
              c.value === null ? (
                <span title={c.nm_reason}>{t("kpi.nm")}</span>
              ) : (
                formatCard(c.value, c.display, locale)
              )
            ) : (
              "—"
            )}
          </td>
        );
      })}
      <td>
        {row.goals.status === "ok" ? (
          `${String(g.ON_TRACK ?? 0)} / ${String(g.AT_RISK ?? 0)} / ${String(g.OFF_TRACK ?? 0)}`
        ) : (
          <Missing part={row.goals} />
        )}
      </td>
      <td>
        {row.alerts.status === "ok" ? (
          `${String(row.alerts.data.critical ?? 0)} / ${String(row.alerts.data.warning ?? 0)}`
        ) : (
          <Missing part={row.alerts} />
        )}
      </td>
    </tr>
  );
}

export function PortfolioPage() {
  const { t } = useI18n();
  const [month, setMonth] = useState(lastMonth());
  const found = usePortfolio(month);
  return (
    <Page title={t("pf.title")}>
      <p className="muted">{t("pf.intro")}</p>
      <label>
        {t("pf.month")}
        <input
          type="month"
          value={month.slice(0, 7)}
          onChange={(e) => e.target.value && setMonth(`${e.target.value}-01`)}
        />
      </label>
      {found.isPending ? <Loading /> : null}
      <ProblemMessage error={found.error} />
      {found.data ? (
        <div className="table-scroll">
          <table className="grid">
            <caption>{t("pf.caption")}</caption>
            <thead>
              <tr>
                <th scope="col">{t("pf.client")}</th>
                <th scope="col" className="num">
                  {t("pf.cash")}
                </th>
                <th scope="col" className="num">
                  {t("pf.grossMargin")}
                </th>
                <th scope="col" className="num">
                  {t("pf.currentRatio")}
                </th>
                <th scope="col" className="num">
                  {t("pf.dso")}
                </th>
                <th scope="col">{t("pf.goals")}</th>
                <th scope="col">{t("pf.alerts")}</th>
              </tr>
            </thead>
            <tbody>
              {found.data.map((r) => (
                <Row key={r.entity_id} row={r} />
              ))}
              {found.data.length ? null : (
                <tr>
                  <td colSpan={7}>{t("pf.none")}</td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      ) : null}
    </Page>
  );
}
