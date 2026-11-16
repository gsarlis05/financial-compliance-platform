import Decimal from "decimal.js";
import { useState } from "react";
import { Link } from "react-router";
import {
  type CashWeek,
  type DashboardQuery,
  type KpiCard,
  type LayoutItem,
  type VarianceLine,
  type Widget,
  type WidgetType,
  WIDGET_TYPES,
  useDashboard,
  useDashboardMutations,
} from "../api/dashboard";
import { useScope } from "../api/hooks";
import { Loading, Page, ProblemMessage } from "../components/common";
import { useI18n } from "../i18n/I18n";
import type { MessageKey } from "../i18n/messages";
import { formatAmount } from "../money";
import { formatValue } from "./Goals";

/** The last complete month (YYYY-MM-01), the default period end. */
export function lastMonth(today = new Date()): string {
  const d = new Date(
    Date.UTC(today.getUTCFullYear(), today.getUTCMonth() - 1, 1),
  );
  return d.toISOString().slice(0, 10);
}

export function formatCard(
  value: string | null,
  display: string,
  locale: string,
): string {
  if (value === null) return "";
  const n = new Decimal(value);
  return display === "percent"
    ? `${formatAmount(n.times(100).toFixed(2), locale)}%`
    : formatAmount(n.toFixed(2), locale);
}

function Nature({ nature }: { nature: string }) {
  const { t } = useI18n();
  return (
    <span className={`badge nature-${nature.toLowerCase()}`}>
      {t(`nature.${nature}` as MessageKey)}
    </span>
  );
}

function KpiCards({
  cards,
  comparison,
}: {
  cards: KpiCard[];
  comparison: string;
}) {
  const { t, locale } = useI18n();
  const { slug, entityId } = useScope();
  return (
    <ul className="kpi-cards">
      {cards.map((c) => (
        <li key={c.key} className="kpi-card">
          <span className="kpi-name">
            {locale === "el" && c.name_el ? c.name_el : c.name}
          </span>
          <Nature nature={c.nature} />
          <strong className="kpi-value">
            {c.value === null
              ? t("kpi.nm")
              : formatCard(c.value, c.display, locale)}
          </strong>
          {c.value === null ? (
            <span className="muted">{c.nm_reason}</span>
          ) : null}
          {comparison === "PRIOR_YEAR" ? (
            <span className="muted">
              {t("dash.priorYear")}:{" "}
              {c.comparison_value === null
                ? "—"
                : formatCard(c.comparison_value, c.display, locale)}
            </span>
          ) : null}
          <Link to={`/w/${slug}/e/${entityId}/kpis`}>{t("dash.explain")}</Link>
        </li>
      ))}
    </ul>
  );
}

const W = 600;
const H = 200;
const PAD = { left: 64, right: 12, top: 12, bottom: 28 };

/** 13-week cash as SVG drawn in React (doc 10 §10.1 visual contract): the actual opening is a
 * solid point, the forecast closing a dashed line, the minimum a thin reference line; never colour
 * alone. A table with the same numbers follows the chart. */
export function CashChart({
  opening,
  weeks,
  asOf,
}: {
  opening: string;
  weeks: CashWeek[];
  asOf: string;
}) {
  const { t, locale } = useI18n();
  const values = [
    opening,
    ...weeks.map((w) => w.closing),
    ...weeks.map((w) => w.minimum),
  ].map((v) => new Decimal(v));
  const low = Decimal.min(...values, 0);
  const high = Decimal.max(...values, 1);
  const span = high.minus(low).isZero() ? new Decimal(1) : high.minus(low);
  const x = (i: number) =>
    PAD.left + (i * (W - PAD.left - PAD.right)) / Math.max(weeks.length, 1);
  const y = (v: string) =>
    PAD.top + high.minus(v).div(span).toNumber() * (H - PAD.top - PAD.bottom);
  const path = [opening, ...weeks.map((w) => w.closing)]
    .map(
      (v, i) => `${i === 0 ? "M" : "L"}${x(i).toFixed(1)},${y(v).toFixed(1)}`,
    )
    .join(" ");
  const minimum = weeks[0]?.minimum ?? "0";
  return (
    <figure className="chart">
      <svg
        viewBox={`0 0 ${String(W)} ${String(H)}`}
        role="img"
        aria-labelledby="dash-cash-desc"
      >
        <desc id="dash-cash-desc">
          {t("dash.cashDescription")
            .replace("{opening}", formatAmount(opening, locale))
            .replace(
              "{closing}",
              formatAmount(weeks[weeks.length - 1]?.closing ?? "0", locale),
            )}
        </desc>
        <line
          className="chart-grid"
          x1={PAD.left}
          x2={W - PAD.right}
          y1={y("0")}
          y2={y("0")}
        />
        <line
          className="chart-minimum"
          data-encoding="reference"
          x1={PAD.left}
          x2={W - PAD.right}
          y1={y(minimum)}
          y2={y(minimum)}
        />
        <line
          className="chart-today"
          data-encoding="cut-over"
          x1={x(0)}
          x2={x(0)}
          y1={PAD.top}
          y2={H - PAD.bottom}
        />
        <text x={x(0) + 4} y={H - PAD.bottom - 4} className="chart-axis">
          {t("dash.asOf")} {asOf}
        </text>
        <path className="chart-forecast" data-nature="FORECAST" d={path} />
        <circle
          className="chart-actual"
          data-nature="ACTUAL"
          cx={x(0)}
          cy={y(opening)}
          r={4}
        />
        <text className="chart-axis" x={4} y={y(high.toString()) + 4}>
          {formatAmount(high.toFixed(0), locale)}
        </text>
        <text className="chart-axis" x={4} y={y(low.toString())}>
          {formatAmount(low.toFixed(0), locale)}
        </text>
      </svg>
      <figcaption className="legend">
        <span>● {t("nature.ACTUAL")}</span>{" "}
        <span>- - {t("nature.FORECAST")}</span>{" "}
        <span>— {t("dash.minimum")}</span> <span>┆ {t("dash.asOf")}</span>
      </figcaption>
    </figure>
  );
}

function VarianceTable({
  rows,
  caption,
}: {
  rows: VarianceLine[];
  caption: string;
}) {
  const { t, locale } = useI18n();
  return (
    <div className="table-scroll">
      <table className="grid">
        <caption>{caption}</caption>
        <thead>
          <tr>
            <th scope="col">{t("dash.line")}</th>
            <th scope="col" className="num">
              {t("dash.actual")}
            </th>
            <th scope="col" className="num">
              {t("dash.comparison")}
            </th>
            <th scope="col" className="num">
              {t("dash.variance")}
            </th>
            <th scope="col" className="num">
              %
            </th>
            <th scope="col">{t("dash.effect")}</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            // A line can appear once per dimension value; the order never changes.
            <tr key={`${String(i)}-${r.line}`}>
              <td>{r.line}</td>
              <td className="num">{formatAmount(r.actual, locale)}</td>
              <td className="num">{formatAmount(r.comparison, locale)}</td>
              <td className="num">{formatAmount(r.variance, locale)}</td>
              <td className="num">
                {r.percent === null ? "—" : formatAmount(r.percent, locale)}
              </td>
              <td>
                {r.favourable === null
                  ? "—"
                  : r.favourable
                    ? `▲ ${t("dash.favourable")}`
                    : `▼ ${t("dash.unfavourable")}`}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function WidgetBody({
  widget,
  comparison,
}: {
  widget: Widget;
  comparison: string;
}) {
  const { t, locale } = useI18n();
  const { slug, entityId } = useScope();
  const base = `/w/${slug}/e/${entityId}`;
  if (widget.status === "denied")
    return <p className="muted">{t("dash.denied")}</p>;
  if (widget.status === "empty")
    return <p className="muted">{widget.reason}</p>;
  const d = widget.data;
  switch (widget.type) {
    case "kpis":
      return (
        <>
          {d.stale ? <p className="error">{t("dash.stale")}</p> : null}
          <KpiCards cards={d.cards ?? []} comparison={comparison} />
        </>
      );
    case "cash":
      return (
        <>
          {d.stale ? <p className="error">{t("dash.stale")}</p> : null}
          <p className="muted">
            {t("dash.asOf")} {d.as_of} ·{" "}
            {d.first_shortfall
              ? `${t("dash.shortfall")} ${d.first_shortfall}`
              : t("dash.noShortfall")}
          </p>
          <CashChart
            opening={d.opening ?? "0"}
            weeks={d.weeks ?? []}
            asOf={d.as_of ?? ""}
          />
          <details>
            <summary>{t("dash.table")}</summary>
            <div className="table-scroll">
              <table className="grid">
                <caption>{t("dash.cashTable")}</caption>
                <thead>
                  <tr>
                    <th scope="col">{t("dash.week")}</th>
                    <th scope="col">{t("goal.nature")}</th>
                    <th scope="col" className="num">
                      {t("dash.closing")}
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {(d.weeks ?? []).map((w) => (
                    <tr key={w.start}>
                      <td>{w.label}</td>
                      <td>
                        <Nature nature="FORECAST" />
                      </td>
                      <td className="num">{formatAmount(w.closing, locale)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </details>
          <Link to={`${base}/cash-forecast`}>{t("dash.open")}</Link>
        </>
      );
    case "budget":
    case "top_variances": {
      const rows = (widget.type === "budget" ? d.rows : d.top) ?? [];
      return (
        <>
          <p className="muted">
            {d.budget_name}
            {d.unposted
              ? ` · ${t("dash.unposted").replace("{n}", String(d.unposted))}`
              : ""}
          </p>
          {rows.length ? (
            <VarianceTable
              rows={rows}
              caption={t(`dash.w.${widget.type}` as MessageKey)}
            />
          ) : (
            <p className="muted">{t("dash.noVariances")}</p>
          )}
          <Link to={`${base}/budgets`}>{t("dash.open")}</Link>
        </>
      );
    }
    case "goals":
      return (
        <>
          <div className="table-scroll">
            <table className="grid">
              <caption>{t("dash.w.goals")}</caption>
              <thead>
                <tr>
                  <th scope="col">{t("goal.name")}</th>
                  <th scope="col" className="num">
                    {t("goal.target")}
                  </th>
                  <th scope="col" className="num">
                    {t("goal.projected")}
                  </th>
                  <th scope="col">{t("goal.statusCol")}</th>
                </tr>
              </thead>
              <tbody>
                {(d.goals ?? []).map((g) => (
                  <tr key={g.id}>
                    <td>{g.name}</td>
                    <td className="num">
                      {formatValue(g.target, g.unit, g.display, locale)}
                    </td>
                    <td className="num">
                      {formatValue(g.projected, g.unit, g.display, locale)}
                    </td>
                    <td>
                      {g.status
                        ? t(`goal.status.${g.status}` as MessageKey)
                        : t("goal.notEvaluatedShort")}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <Link to={`${base}/goals`}>{t("dash.open")}</Link>
        </>
      );
    case "alerts":
      return (
        <>
          <p>
            {t("alert.severity.CRITICAL")}: {d.critical ?? 0} ·{" "}
            {t("alert.severity.WARNING")}: {d.warning ?? 0}
          </p>
          <ul>
            {(d.latest ?? []).map((a) => (
              <li key={a.id}>
                {t(`alert.severity.${a.severity}` as MessageKey)}: {a.title}
              </li>
            ))}
          </ul>
          <Link to={`${base}/alerts`}>{t("dash.open")}</Link>
        </>
      );
  }
}

function Customise({
  current,
  onDone,
}: {
  current: Widget[];
  onDone: () => void;
}) {
  const { t } = useI18n();
  const m = useDashboardMutations();
  const [items, setItems] = useState<LayoutItem[]>(
    current.map((w) => ({
      type: w.type,
      ...(w.options.kpis ? { kpis: w.options.kpis } : {}),
    })),
  );
  const kpis = items.find((i) => i.type === "kpis")?.kpis ?? [];
  const [kpiText, setKpiText] = useState(kpis.join(", "));
  const toggle = (type: WidgetType) =>
    setItems((list) =>
      list.some((i) => i.type === type)
        ? list.filter((i) => i.type !== type)
        : [...list, { type }],
    );
  const move = (index: number, by: number) =>
    setItems((list) => {
      const next = [...list];
      const target = index + by;
      if (target < 0 || target >= next.length) return list;
      [next[index], next[target]] = [
        next[target] as LayoutItem,
        next[index] as LayoutItem,
      ];
      return next;
    });
  const widgets = () =>
    items.map((i) =>
      i.type === "kpis"
        ? {
            type: i.type,
            kpis: kpiText
              .split(",")
              .map((k) => k.trim().toUpperCase())
              .filter(Boolean),
          }
        : { type: i.type },
    );
  const save = (asDefault: boolean) =>
    m.save.mutate({ widgets: widgets(), asDefault }, { onSuccess: onDone });
  return (
    <section className="card" aria-labelledby="dash-customise">
      <h2 id="dash-customise">{t("dash.customise")}</h2>
      <fieldset>
        <legend>{t("dash.widgets")}</legend>
        {WIDGET_TYPES.map((type) => (
          <label key={type} className="checkbox">
            <input
              type="checkbox"
              checked={items.some((i) => i.type === type)}
              onChange={() => toggle(type)}
            />{" "}
            {t(`dash.w.${type}` as MessageKey)}
          </label>
        ))}
      </fieldset>
      <ol>
        {items.map((i, index) => (
          <li key={i.type}>
            {t(`dash.w.${i.type}` as MessageKey)}{" "}
            <button
              type="button"
              onClick={() => move(index, -1)}
              aria-label={`${t("dash.up")} ${t(`dash.w.${i.type}` as MessageKey)}`}
            >
              ↑
            </button>{" "}
            <button
              type="button"
              onClick={() => move(index, 1)}
              aria-label={`${t("dash.down")} ${t(`dash.w.${i.type}` as MessageKey)}`}
            >
              ↓
            </button>
          </li>
        ))}
      </ol>
      <label>
        {t("dash.kpiKeys")}
        <input value={kpiText} onChange={(e) => setKpiText(e.target.value)} />
      </label>
      <div className="form inline">
        <button
          type="button"
          className="primary"
          disabled={!items.length}
          onClick={() => save(false)}
        >
          {t("dash.saveMine")}
        </button>
        <button
          type="button"
          disabled={!items.length}
          onClick={() => save(true)}
        >
          {t("dash.saveDefault")}
        </button>
        <button
          type="button"
          onClick={() => m.reset.mutate(undefined, { onSuccess: onDone })}
        >
          {t("dash.reset")}
        </button>
        <button type="button" onClick={onDone}>
          {t("ck.cancel")}
        </button>
      </div>
      <ProblemMessage error={m.save.error ?? m.reset.error} />
    </section>
  );
}

export function DashboardPage() {
  const { t } = useI18n();
  const [q, setQ] = useState<DashboardQuery>({
    preset: "YTD",
    month: lastMonth(),
    comparison: "BUDGET",
  });
  const [customising, setCustomising] = useState(false);
  const board = useDashboard(q);
  const m = useDashboardMutations();
  const p = board.data?.period;
  return (
    <Page
      title={t("dash.title")}
      actions={
        <button type="button" onClick={() => setCustomising(true)}>
          {t("dash.customise")}
        </button>
      }
    >
      <div className="form inline">
        <label>
          {t("dash.period")}
          <select
            value={q.preset}
            onChange={(e) =>
              setQ({ ...q, preset: e.target.value as DashboardQuery["preset"] })
            }
          >
            {(["MONTH", "QTD", "YTD"] as const).map((x) => (
              <option key={x} value={x}>
                {t(`dash.preset.${x}` as MessageKey)}
              </option>
            ))}
          </select>
        </label>
        <label>
          {t("dash.month")}
          <input
            type="month"
            value={q.month.slice(0, 7)}
            onChange={(e) =>
              e.target.value && setQ({ ...q, month: `${e.target.value}-01` })
            }
          />
        </label>
        <label>
          {t("dash.compareWith")}
          <select
            value={q.comparison}
            onChange={(e) =>
              setQ({
                ...q,
                comparison: e.target.value as DashboardQuery["comparison"],
              })
            }
          >
            <option value="BUDGET">{t("dash.cmp.BUDGET")}</option>
            <option value="PRIOR_YEAR">{t("dash.cmp.PRIOR_YEAR")}</option>
          </select>
        </label>
        <button
          type="button"
          disabled={m.refresh.isPending}
          onClick={() => m.refresh.mutate(q)}
        >
          {t("dash.refresh")}
        </button>
      </div>
      {p ? (
        <p className="muted" role="status">
          {p.date_from} – {p.date_to} ·{" "}
          {t(`dash.cmp.${p.comparison}` as MessageKey)}
        </p>
      ) : null}
      <ProblemMessage error={board.error ?? m.refresh.error} />
      {customising && board.data ? (
        <Customise
          current={board.data.widgets}
          onDone={() => setCustomising(false)}
        />
      ) : null}
      {board.isPending ? <Loading /> : null}
      <div className="dash-grid">
        {(board.data?.widgets ?? []).map((w) => (
          <section
            key={w.type}
            className="card dash-widget"
            aria-labelledby={`dash-${w.type}`}
          >
            <h2 id={`dash-${w.type}`}>{t(`dash.w.${w.type}` as MessageKey)}</h2>
            <WidgetBody widget={w} comparison={q.comparison} />
          </section>
        ))}
      </div>
    </Page>
  );
}
