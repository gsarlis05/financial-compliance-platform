import Decimal from "decimal.js";
import { useState } from "react";
import { Link } from "react-router";
import {
  type CashWeek,
  type DashboardQuery,
  type KpiCard,
  type LayoutItem,
  PRESETS,
  type Preset,
  type VarianceLine,
  type Widget,
  type WidgetType,
  WIDGET_TYPES,
  useDashboard,
  useDashboardMutations,
  useSavedViews,
} from "../api/dashboard";
import { useScenarios } from "../api/scenarios";
import { useScope } from "../api/hooks";
import { Loading, Page, ProblemMessage } from "../components/common";
import { useI18n } from "../i18n/I18n";
import type { MessageKey } from "../i18n/messages";
import { formatAmount } from "../money";
import { formatValue } from "./Goals";
import { EngineReviewNote } from "../components/ReviewNote";

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
    case "waterfall":
      return <Waterfall data={d} />;
    case "scenario":
      return <ScenarioSummary data={d} />;
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

const HEADLINE_KEYS = [
  "PL.REVENUE",
  "PL.EBITDA",
  "PL.NET_INCOME",
  "CF.NET_CHANGE",
  "BS.CASH",
  "BS.DEBT",
];

/** From the budgeted result to the actual result, one row per budget line (M8-4). The table is
 * the widget: every step is listed with its effect, and the steps add up to the difference. */
function Waterfall({ data }: { data: Widget["data"] }) {
  const { t, locale } = useI18n();
  const amount = (v: string | undefined) => (v ? formatAmount(v, locale) : "—");
  return (
    <div className="table-scroll">
      <table className="grid">
        <caption>
          {t("dash.wf.caption")} ({data.budget_name})
        </caption>
        <thead>
          <tr>
            <th scope="col">{t("dash.line")}</th>
            <th scope="col" className="num">
              {t("dash.wf.amount")}
            </th>
            <th scope="col">{t("dash.wf.nature")}</th>
          </tr>
        </thead>
        <tbody>
          <tr className="subtotal">
            <th scope="row">{t("dash.wf.start")}</th>
            <td className="num">{amount(data.start)}</td>
            <td>
              {t(`nature.${data.start_nature ?? "BUDGET"}` as MessageKey)}
            </td>
          </tr>
          {(data.steps ?? []).map((s) => (
            <tr key={s.line}>
              <th scope="row">{s.line}</th>
              <td className="num">
                {s.favourable === null ? "" : s.favourable ? "▲ " : "▼ "}
                {amount(s.value)}
              </td>
              <td>{t("dash.wf.variance")}</td>
            </tr>
          ))}
          <tr className="total">
            <th scope="row">{t("dash.wf.end")}</th>
            <td className="num">{amount(data.end)}</td>
            <td>{t(`nature.${data.end_nature ?? "ACTUAL"}` as MessageKey)}</td>
          </tr>
        </tbody>
      </table>
    </div>
  );
}

/** A shared scenario against its base (M8-4): hypothetical figures, named as such. */
function ScenarioSummary({ data }: { data: Widget["data"] }) {
  const { t, locale } = useI18n();
  const changes = data.changes ?? {};
  return (
    <>
      <p>
        <strong>{data.name}</strong>{" "}
        <span className="badge nature-hypothetical">
          {t("nature.HYPOTHETICAL")}
        </span>{" "}
        · {t("sc.base")}: {data.base_name} v{data.base_version}
      </p>
      <EngineReviewNote />
      <div className="table-scroll">
        <table className="grid">
          <caption>{t("dash.sc.caption")}</caption>
          <thead>
            <tr>
              <th scope="col">{t("dash.line")}</th>
              <th scope="col" className="num">
                {t("dash.sc.change")}
              </th>
            </tr>
          </thead>
          <tbody>
            {HEADLINE_KEYS.map((k) => (
              <tr key={k}>
                <th scope="row">{t(`sc.h.${k}` as MessageKey)}</th>
                <td className="num">
                  {changes[k] ? formatAmount(changes[k], locale) : "—"}
                </td>
              </tr>
            ))}
            <tr>
              <th scope="row">{t("dash.sc.lowestCash")}</th>
              <td className="num">
                {data.lowest_cash
                  ? `${formatAmount(data.lowest_cash.base, locale)} → ${formatAmount(data.lowest_cash.scenario, locale)}`
                  : "—"}
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </>
  );
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
    current.map((w) => ({ type: w.type, ...w.options })),
  );
  const shared = (useScenarios().data ?? []).filter(
    (s) => s.status === "SHARED",
  );
  const update = (type: WidgetType, change: Partial<LayoutItem>) =>
    setItems((list) =>
      list.map((i) => (i.type === type ? { ...i, ...change } : i)),
    );
  const setWidth = (type: WidgetType, half: boolean) =>
    setItems((list) =>
      list.map((i) => {
        if (i.type !== type) return i;
        const rest: LayoutItem = { ...i };
        delete rest.width;
        return half ? { ...rest, width: "half" as const } : rest;
      }),
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
  const widgets = (): LayoutItem[] =>
    items.map((i) => ({
      type: i.type,
      ...(i.type === "kpis"
        ? {
            kpis: kpiText
              .split(",")
              .map((k) => k.trim().toUpperCase())
              .filter(Boolean),
          }
        : {}),
      ...(i.type === "scenario" && i.scenario_id
        ? { scenario_id: i.scenario_id }
        : {}),
      ...(i.width === "half" ? { width: "half" as const } : {}),
    }));
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
            </button>{" "}
            <label>
              <span className="visually-hidden">
                {t("dash.width")} {t(`dash.w.${i.type}` as MessageKey)}
              </span>
              <select
                value={i.width ?? "full"}
                onChange={(e) => setWidth(i.type, e.target.value === "half")}
              >
                <option value="full">{t("dash.width.full")}</option>
                <option value="half">{t("dash.width.half")}</option>
              </select>
            </label>
            {i.type === "scenario" ? (
              <label>
                {" "}
                {t("dash.chooseScenario")}
                <select
                  value={i.scenario_id ?? ""}
                  onChange={(e) =>
                    update(i.type, { scenario_id: e.target.value })
                  }
                >
                  <option value="">—</option>
                  {shared.map((s) => (
                    <option key={s.id} value={s.id}>
                      {s.name}
                    </option>
                  ))}
                </select>
              </label>
            ) : null}
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

/** Your saved views: a name for a period preset and a comparison (M8-4). */
function SavedViews({
  q,
  onApply,
}: {
  q: DashboardQuery;
  onApply: (v: Pick<DashboardQuery, "preset" | "comparison">) => void;
}) {
  const { t } = useI18n();
  const views = useSavedViews();
  const [chosen, setChosen] = useState("");
  const [name, setName] = useState("");
  const list = views.list.data ?? [];
  return (
    <div className="form inline">
      <label>
        {t("dash.views")}
        <select
          value={chosen}
          onChange={(e) => {
            setChosen(e.target.value);
            const v = list.find((x) => x.id === e.target.value);
            if (v) onApply({ preset: v.preset, comparison: v.comparison });
          }}
        >
          <option value="">—</option>
          {list.map((v) => (
            <option key={v.id} value={v.id}>
              {v.name}
            </option>
          ))}
        </select>
      </label>
      {chosen ? (
        <button
          type="button"
          onClick={() =>
            views.remove.mutate(chosen, { onSuccess: () => setChosen("") })
          }
        >
          {t("dash.view.delete")}
        </button>
      ) : null}
      <label>
        {t("dash.view.name")}
        <input
          value={name}
          maxLength={60}
          onChange={(e) => setName(e.target.value)}
        />
      </label>
      <button
        type="button"
        disabled={!name.trim()}
        onClick={() =>
          views.save.mutate(
            { name: name.trim(), preset: q.preset, comparison: q.comparison },
            { onSuccess: () => setName("") },
          )
        }
      >
        {t("dash.view.save")}
      </button>
      <ProblemMessage error={views.save.error ?? views.remove.error} />
    </div>
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
            onChange={(e) => setQ({ ...q, preset: e.target.value as Preset })}
          >
            {PRESETS.map((x) => (
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
      <SavedViews q={q} onApply={(v) => setQ({ ...q, ...v })} />
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
            className={`card dash-widget${w.options.width === "half" ? " dash-half" : ""}`}
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
