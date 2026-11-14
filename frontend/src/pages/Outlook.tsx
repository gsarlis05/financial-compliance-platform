// The full-year outlook (M6-6 for M6-5): actual months from the books, then forecast months from
// the latest published projection, each column with its nature in words, a divider at the
// cut-over, and quarters and the year as exact sums of their months.
import { useState } from "react";
import { useOutlook } from "../api/projections";
import { Loading, Page, ProblemMessage } from "../components/common";
import { useI18n } from "../i18n/I18n";
import type { MessageKey } from "../i18n/messages";
import { formatAmount } from "../money";
import { STATEMENTS } from "./Projections";

const OUTLOOK_ROWS = [
  ...(STATEMENTS[0]?.rows ?? []),
  ["BS.CASH", "total"] as [string, "total"],
];

export function OutlookPage() {
  const { t, locale } = useI18n();
  const [year, setYear] = useState(() => new Date().getFullYear());
  const outlook = useOutlook(`${year}-06-30`);
  const o = outlook.data;
  const natureText = (n: string) =>
    n === ""
      ? t("ol.notShown")
      : n
          .split("+")
          .map((x) => t(`nature.${x}` as MessageKey))
          .join(" + ");
  const dividerAfter = (start: string, granularity: string) =>
    !!o?.cutover &&
    granularity === "MONTH" &&
    start.slice(0, 7) === o.cutover.slice(0, 7);
  return (
    <Page title={t("nav.outlook")}>
      <p>{t("ol.intro")}</p>
      <div className="form inline">
        <label>
          {t("ol.year")}
          <input
            type="number"
            min={2000}
            max={2100}
            value={year}
            onChange={(e) => setYear(Number(e.target.value) || year)}
          />
        </label>
      </div>
      {outlook.isLoading ? <Loading /> : null}
      {outlook.error ? <ProblemMessage error={outlook.error} /> : null}
      {o ? (
        <>
          <p role="status">{o.note}</p>
          {o.cutover ? (
            <p>
              {t("ol.divider")} {o.cutover}
            </p>
          ) : null}
          <div className="table-scroll">
            <table className="statement">
              <caption>
                {t("ol.caption")} {o.year_start.slice(0, 4)}
              </caption>
              <thead>
                <tr>
                  <th scope="col">{t("pj.line")}</th>
                  {o.columns.map((c, i) => (
                    <th
                      scope="col"
                      key={i}
                      className={
                        dividerAfter(c.start, c.granularity)
                          ? "divider-after"
                          : ""
                      }
                    >
                      {c.granularity === "MONTH"
                        ? c.start.slice(0, 7)
                        : c.granularity === "QUARTER"
                          ? `${t("ol.q")}${Math.floor(i - 12) + 1}`
                          : t("ol.yearTotal")}
                    </th>
                  ))}
                </tr>
                <tr>
                  <th scope="row">{t("pj.nature")}</th>
                  {o.columns.map((c, i) => (
                    <td
                      key={i}
                      className={
                        dividerAfter(c.start, c.granularity)
                          ? "divider-after"
                          : ""
                      }
                    >
                      <span
                        className={`badge nature-${(c.nature.split("+").length > 1 ? "blended" : c.nature || "none").toLowerCase()}`}
                      >
                        {natureText(c.nature)}
                      </span>
                    </td>
                  ))}
                </tr>
              </thead>
              <tbody>
                {OUTLOOK_ROWS.map(([key, kind]) => (
                  <tr key={key} className={kind}>
                    <th scope="row">{t(`pj.k.${key}` as MessageKey)}</th>
                    {o.columns.map((c, i) => {
                      const value = o.rows[key]?.[i] ?? null;
                      return (
                        <td
                          key={i}
                          className={`amount${dividerAfter(c.start, c.granularity) ? " divider-after" : ""}`}
                        >
                          {value === null ? "–" : formatAmount(value, locale)}
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p>{t("ol.sums")}</p>
        </>
      ) : null}
    </Page>
  );
}
