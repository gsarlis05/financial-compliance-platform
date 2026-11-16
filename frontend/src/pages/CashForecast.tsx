import Decimal from "decimal.js";
import { type SyntheticEvent, useMemo, useState } from "react";
import {
  type CashForecast,
  type ForecastWeek,
  type Nature,
  type Override,
  type WhatIfResult,
  useExplain,
  useForecastAccuracy,
  useForecastHistory,
  useForecastMutations,
  useForecastSettings,
  useLatestForecast,
  useRunResults,
} from "../api/forecast";
import { Loading, Page, ProblemMessage } from "../components/common";
import { useI18n } from "../i18n/I18n";
import type { MessageKey } from "../i18n/messages";
import { formatAmount } from "../money";

const today = () => new Date().toISOString().slice(0, 10);

/** Nature as text plus a border style (doc 10 §10.1: never colour alone). */
export function NatureTag({ nature }: { nature: Nature }) {
  const { t } = useI18n();
  return (
    <span className={`badge nature-${nature.toLowerCase()}`}>
      {t(`nature.${nature}` as MessageKey)}
    </span>
  );
}

// --- chart ------------------------------------------------------------------------------------

const W = 720;
const H = 260;
const PAD = { left: 70, right: 16, top: 16, bottom: 36 };

/**
 * The 13-week cash chart as SVG. Numbers here only place pixels; amounts are shown from the
 * server's decimal strings. Encoding: the actual opening is a solid point; the forecast closing
 * is a dashed line; a what-if is a dotted line; the minimum cash is a thin reference line; the
 * as-of date has a vertical marker; shortfall weeks are marked with "!" (and listed in the table).
 */
export function ForecastChart({
  forecast,
  whatIf,
}: {
  forecast: CashForecast;
  whatIf: WhatIfResult | null;
}) {
  const { t, locale } = useI18n();
  const weeks = forecast.weeks;
  const values = [
    new Decimal(forecast.opening_cash),
    ...weeks.map((w) => new Decimal(w.closing)),
    ...weeks.map((w) => new Decimal(w.minimum)),
    ...(whatIf?.weeks.map((w) => new Decimal(w.what_if_closing)) ?? []),
  ];
  const low = Decimal.min(...values, 0);
  const high = Decimal.max(...values, 1);
  const span = high.minus(low).isZero() ? new Decimal(1) : high.minus(low);
  const x = (i: number) =>
    PAD.left + (i * (W - PAD.left - PAD.right)) / weeks.length;
  const y = (v: string | Decimal) =>
    PAD.top +
    new Decimal(high).minus(v).div(span).toNumber() *
      (H - PAD.top - PAD.bottom);
  const line = (points: string[]) =>
    points
      .map(
        (v, i) => `${i === 0 ? "M" : "L"}${x(i).toFixed(1)},${y(v).toFixed(1)}`,
      )
      .join(" ");
  const closing = line([forecast.opening_cash, ...weeks.map((w) => w.closing)]);
  const scenario = whatIf
    ? line([
        forecast.opening_cash,
        ...whatIf.weeks.map((w) => w.what_if_closing),
      ])
    : null;
  const minimum = weeks[0]?.minimum ?? "0";
  const lastWeek = weeks[weeks.length - 1];
  const description = t("cf.chartDescription")
    .replace("{opening}", formatAmount(forecast.opening_cash, locale))
    .replace("{closing}", formatAmount(lastWeek?.closing ?? "0", locale))
    .replace("{minimum}", formatAmount(minimum, locale));
  return (
    <figure className="chart">
      <svg
        viewBox={`0 0 ${W} ${H}`}
        role="img"
        aria-labelledby="cf-chart-title"
        aria-describedby="cf-chart-desc"
      >
        <title id="cf-chart-title">{t("cf.chartTitle")}</title>
        <desc id="cf-chart-desc">{description}</desc>
        {[high, low.plus(span.div(2)), low].map((v) => (
          <g key={v.toString()}>
            <line
              x1={PAD.left}
              x2={W - PAD.right}
              y1={y(v)}
              y2={y(v)}
              className="chart-grid"
            />
            <text
              x={PAD.left - 6}
              y={y(v) + 4}
              className="chart-axis"
              textAnchor="end"
            >
              {formatAmount(v.toFixed(0), locale).replace(/\.00$/, "")}
            </text>
          </g>
        ))}
        <line
          x1={PAD.left}
          x2={W - PAD.right}
          y1={y(minimum)}
          y2={y(minimum)}
          className="chart-minimum"
        />
        <line
          x1={x(0)}
          x2={x(0)}
          y1={PAD.top}
          y2={H - PAD.bottom}
          className="chart-today"
        />
        <text x={x(0) + 4} y={PAD.top + 10} className="chart-axis">
          {t("cf.asOf")} {forecast.as_of}
        </text>
        <path d={closing} className="chart-forecast" />
        {scenario ? <path d={scenario} className="chart-whatif" /> : null}
        {whatIf?.weeks.map((w, i) =>
          w.what_if_shortfall ? (
            <text
              key={`wi-${w.label}`}
              x={x(i + 1)}
              y={y(w.what_if_closing) + 16}
              textAnchor="middle"
              className="chart-short-text"
            >
              !
            </text>
          ) : null,
        )}
        <circle
          cx={x(0)}
          cy={y(forecast.opening_cash)}
          r={5}
          className="chart-actual"
        />
        {weeks.map((w, i) => (
          <g key={w.label}>
            <circle
              cx={x(i + 1)}
              cy={y(w.closing)}
              r={3}
              className={w.shortfall ? "chart-short" : "chart-point"}
            />
            {w.shortfall ? (
              <text
                x={x(i + 1)}
                y={y(w.closing) - 8}
                textAnchor="middle"
                className="chart-short-text"
              >
                !
              </text>
            ) : null}
            {i % 2 === 0 ? (
              <text
                x={x(i + 1)}
                y={H - PAD.bottom + 16}
                textAnchor="middle"
                className="chart-axis"
              >
                {w.label.slice(5)}
              </text>
            ) : null}
          </g>
        ))}
      </svg>
      <figcaption className="chart-legend">
        <span>
          <svg width="28" height="10" aria-hidden="true">
            <circle cx="14" cy="5" r="4" className="chart-actual" />
          </svg>
          {t("cf.legendActual")}
        </span>
        <span>
          <svg width="28" height="10" aria-hidden="true">
            <line x1="0" x2="28" y1="5" y2="5" className="chart-forecast" />
          </svg>
          {t("cf.legendForecast")}
        </span>
        {whatIf ? (
          <span>
            <svg width="28" height="10" aria-hidden="true">
              <line x1="0" x2="28" y1="5" y2="5" className="chart-whatif" />
            </svg>
            {t("cf.legendWhatIf")}
          </span>
        ) : null}
        <span>
          <svg width="28" height="10" aria-hidden="true">
            <line x1="0" x2="28" y1="5" y2="5" className="chart-minimum" />
          </svg>
          {t("cf.legendMinimum")}
        </span>
        <span>! {t("cf.legendShortfall")}</span>
      </figcaption>
    </figure>
  );
}

const CATEGORIES = new Set([
  "CUSTOMERS",
  "SUPPLIERS",
  "RENT",
  "PAYROLL",
  "SOCIAL_INSURANCE",
  "SUBSCRIPTION",
  "LEASE",
  "INSURANCE",
  "UTILITIES",
  "INCOME",
  "OTHER",
  "DEBT_PRINCIPAL",
  "DEBT_INTEREST",
  "TAX",
  "FINANCING",
  "CAPEX",
  "GRANT",
]);

/** Known categories are translated; one typed into a what-if is shown as typed. */
function categoryLabel(
  t: (key: MessageKey) => string,
  category: string,
): string {
  return CATEGORIES.has(category)
    ? t(`cf.cat.${category}` as MessageKey)
    : category;
}

// --- drill-down -------------------------------------------------------------------------------

function FlowItems({
  runId,
  week,
  direction,
  category,
  nature,
}: {
  runId: string;
  week: ForecastWeek;
  direction: string;
  category: string;
  nature: Nature;
}) {
  const { t, locale } = useI18n();
  const results = useRunResults(runId);
  const result = results.data?.results.find(
    (r) =>
      r.series_key === "cash.flow" &&
      r.period_start === week.start &&
      r.nature === nature &&
      r.dimensions[0] === direction &&
      r.dimensions[1] === category,
  );
  const explain = useExplain(runId, result?.id ?? null);
  if (results.isPending || explain.isPending) {
    return <Loading />;
  }
  return (
    <ul className="plain-list small">
      {explain.data?.lineage.map((x, i) => (
        <li key={`${x.input_ref}-${i}`}>
          {t(`cf.source.${x.input_kind}` as MessageKey)} ·{" "}
          {x.amount ? formatAmount(x.amount, locale) : ""}
          {x.note === "overdue" ? ` · ${t("cf.overdue")}` : ""}
          <span className="muted"> {x.input_ref.split(":")[0]}</span>
        </li>
      ))}
    </ul>
  );
}

function WeekDetail({ runId, week }: { runId: string; week: ForecastWeek }) {
  const { t, locale } = useI18n();
  const [open, setOpen] = useState<string | null>(null);
  return (
    <section className="panel" aria-labelledby="cf-week-heading">
      <h2 id="cf-week-heading">
        {t("cf.weekDetail")} {week.label} ({week.start} – {week.end})
      </h2>
      {week.flows.length === 0 ? <p>{t("cf.noFlows")}</p> : null}
      <ul className="plain-list">
        {week.flows.map((f) => {
          const key = `${f.direction}-${f.category}-${f.nature}`;
          return (
            <li key={key}>
              <button
                type="button"
                aria-expanded={open === key}
                onClick={() => setOpen(open === key ? null : key)}
              >
                {f.direction === "IN" ? t("cf.in") : t("cf.out")} ·{" "}
                {categoryLabel(t, f.category)} ·{" "}
                {formatAmount(
                  f.direction === "IN" ? f.amount : `-${f.amount}`,
                  locale,
                )}
              </button>{" "}
              <NatureTag nature={f.nature} />
              {open === key ? (
                <FlowItems
                  runId={runId}
                  week={week}
                  direction={f.direction}
                  category={f.category}
                  nature={f.nature}
                />
              ) : null}
            </li>
          );
        })}
      </ul>
    </section>
  );
}

// --- what-if ----------------------------------------------------------------------------------

/** Only the fields an override of its type uses; the others get neutral values. */
export function payload(o: Override): Override {
  return {
    type: o.type,
    party: o.type === "ONE_OFF" ? "" : o.party.trim(),
    category: o.category.trim(),
    days: o.type === "TIMING_SHIFT" ? o.days : 0,
    percent: o.type === "PCT_CHANGE" ? o.percent.trim() : "0",
    day: o.type === "ONE_OFF" ? o.day : null,
    amount: o.type === "ONE_OFF" ? o.amount.trim() : "0",
    reason: o.type === "ONE_OFF" ? o.reason.trim() : "",
  };
}

const EMPTY_OVERRIDE: Override = {
  type: "TIMING_SHIFT",
  party: "",
  category: "",
  days: 30,
  percent: "10",
  day: null,
  amount: "",
  reason: "",
};

function WhatIfPanel({
  forecast,
  onResult,
}: {
  forecast: CashForecast;
  onResult: (r: WhatIfResult | null) => void;
}) {
  const { t } = useI18n();
  const { whatIf } = useForecastMutations();
  const [items, setItems] = useState<Override[]>([]);
  const [form, setForm] = useState<Override>(EMPTY_OVERRIDE);
  const set = (changes: Partial<Override>) => setForm({ ...form, ...changes });

  function add(event: SyntheticEvent) {
    event.preventDefault();
    setItems([...items, form]);
    setForm(EMPTY_OVERRIDE);
  }

  function compare() {
    whatIf.mutate(
      { runId: forecast.run_id, overrides: items.map(payload) },
      { onSuccess: (r) => onResult(r) },
    );
  }

  const describe = (o: Override) =>
    o.type === "TIMING_SHIFT"
      ? t("cf.describeShift")
          .replace("{who}", o.party || o.category)
          .replace("{days}", String(o.days))
      : o.type === "PCT_CHANGE"
        ? t("cf.describePct")
            .replace("{who}", o.party || o.category)
            .replace("{percent}", o.percent)
        : t("cf.describeOneOff")
            .replace("{amount}", o.amount)
            .replace("{day}", o.day ?? "")
            .replace("{reason}", o.reason);

  return (
    <section aria-labelledby="cf-whatif-heading">
      <h2 id="cf-whatif-heading">{t("cf.whatIf")}</h2>
      <p className="muted">{t("cf.whatIfHelp")}</p>
      {items.length ? (
        <ol>
          {items.map((o, i) => (
            <li key={`${o.type}-${i}`}>
              {describe(o)}
              {whatIf.data ? (
                <span className="muted">
                  {" "}
                  · {t("cf.matched")} {whatIf.data.matched[i]}
                </span>
              ) : null}{" "}
              <button
                type="button"
                onClick={() => setItems(items.filter((_, j) => j !== i))}
              >
                {t("cf.remove")}
              </button>
            </li>
          ))}
        </ol>
      ) : null}
      <form className="panel form inline" onSubmit={add}>
        <label>
          {t("cf.overrideType")}
          <select
            value={form.type}
            onChange={(e) => set({ type: e.target.value as Override["type"] })}
          >
            <option value="TIMING_SHIFT">{t("cf.type.TIMING_SHIFT")}</option>
            <option value="PCT_CHANGE">{t("cf.type.PCT_CHANGE")}</option>
            <option value="ONE_OFF">{t("cf.type.ONE_OFF")}</option>
          </select>
        </label>
        {form.type !== "ONE_OFF" ? (
          <>
            <label>
              {t("cf.party")}
              <input
                value={form.party}
                onChange={(e) => set({ party: e.target.value.toUpperCase() })}
                maxLength={30}
                placeholder="C001"
              />
            </label>
            <label>
              {t("cf.category")}
              <input
                value={form.category}
                onChange={(e) =>
                  set({ category: e.target.value.toUpperCase() })
                }
                maxLength={20}
                placeholder="SUPPLIERS"
              />
            </label>
          </>
        ) : null}
        {form.type === "TIMING_SHIFT" ? (
          <label>
            {t("cf.days")}
            <input
              type="number"
              min={-365}
              max={365}
              value={form.days}
              onChange={(e) => set({ days: Number(e.target.value) })}
            />
          </label>
        ) : null}
        {form.type === "PCT_CHANGE" ? (
          <label>
            {t("cf.percent")}
            <input
              inputMode="decimal"
              value={form.percent}
              onChange={(e) => set({ percent: e.target.value })}
            />
          </label>
        ) : null}
        {form.type === "ONE_OFF" ? (
          <>
            <label>
              {t("cf.day")}
              <input
                type="date"
                value={form.day ?? ""}
                onChange={(e) => set({ day: e.target.value || null })}
                required
              />
            </label>
            <label>
              {t("cf.amount")}
              <input
                inputMode="decimal"
                value={form.amount}
                onChange={(e) => set({ amount: e.target.value })}
                placeholder="-5000.00"
                required
              />
            </label>
            <label>
              {t("cf.category")}
              <input
                value={form.category}
                onChange={(e) =>
                  set({ category: e.target.value.toUpperCase() })
                }
                maxLength={20}
                placeholder="CAPEX"
                required
              />
            </label>
            <label>
              {t("cf.reason")}
              <input
                value={form.reason}
                onChange={(e) => set({ reason: e.target.value })}
                maxLength={200}
                required
              />
            </label>
          </>
        ) : null}
        <button type="submit">{t("cf.addOverride")}</button>
      </form>
      <div className="actions">
        <button
          type="button"
          className="primary"
          disabled={!items.length || whatIf.isPending}
          onClick={compare}
        >
          {t("cf.compare")}
        </button>
        {whatIf.data ? (
          <button
            type="button"
            onClick={() => {
              whatIf.reset();
              onResult(null);
            }}
          >
            {t("cf.clearWhatIf")}
          </button>
        ) : null}
      </div>
      <ProblemMessage error={whatIf.error} />
      {whatIf.data ? (
        <p role="status">
          <NatureTag nature="HYPOTHETICAL" /> {t("cf.notSaved")}{" "}
          {whatIf.data.what_if_first_shortfall
            ? t("cf.whatIfShortfall").replace(
                "{date}",
                whatIf.data.what_if_first_shortfall.date,
              )
            : t("cf.whatIfNoShortfall")}
        </p>
      ) : null}
    </section>
  );
}

// --- history, accuracy, settings --------------------------------------------------------------

function HistorySection() {
  const { t, locale } = useI18n();
  const history = useForecastHistory();
  return (
    <section aria-labelledby="cf-history-heading">
      <h2 id="cf-history-heading">{t("cf.history")}</h2>
      <ProblemMessage error={history.error} />
      {history.data?.length ? (
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th scope="col">{t("cf.asOf")}</th>
                <th scope="col">{t("cf.made")}</th>
                <th scope="col">{t("cf.trigger")}</th>
                <th scope="col" className="amount">
                  {t("cf.opening")}
                </th>
                <th scope="col" className="amount">
                  {t("cf.closing13")}
                </th>
                <th scope="col">{t("cf.firstShortfall")}</th>
                <th scope="col">{t("cf.state")}</th>
              </tr>
            </thead>
            <tbody>
              {history.data.map((h) => (
                <tr key={h.run_id}>
                  <td>{h.as_of}</td>
                  <td>{h.created_at.slice(0, 16).replace("T", " ")}</td>
                  <td>{t(`cf.trigger.${h.trigger}` as MessageKey)}</td>
                  <td className="amount">
                    {formatAmount(h.opening_cash, locale)}
                  </td>
                  <td className="amount">
                    {formatAmount(h.closing_week_13, locale)}
                  </td>
                  <td>{h.first_shortfall ?? "—"}</td>
                  <td>{h.stale ? t("cf.stale") : t("cf.current")}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </section>
  );
}

function AccuracySection() {
  const { t, locale } = useI18n();
  const accuracy = useForecastAccuracy(today());
  const cell = (
    week: {
      comparisons: {
        horizon_weeks: number;
        forecast: string;
        ape_percent: string | null;
      }[];
    },
    h: number,
  ) => {
    const c = week.comparisons.find((x) => x.horizon_weeks === h);
    if (!c) {
      return "—";
    }
    return `${formatAmount(c.forecast, locale)} (${c.ape_percent === null ? t("cf.notMeaningful") : `${c.ape_percent}%`})`;
  };
  return (
    <section aria-labelledby="cf-accuracy-heading">
      <h2 id="cf-accuracy-heading">{t("cf.accuracy")}</h2>
      <p className="muted">{t("cf.accuracyHelp")}</p>
      <ProblemMessage error={accuracy.error} />
      {accuracy.data ? (
        <>
          <p className="tags">
            {[1, 4, 13].map((h) => (
              <span key={h} className="tag">
                {t("cf.mape").replace("{h}", String(h))}:{" "}
                {accuracy.data.mape_percent[String(h)]
                  ? `${accuracy.data.mape_percent[String(h)]}%`
                  : t("cf.noData")}
              </span>
            ))}
          </p>
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th scope="col">{t("cf.week")}</th>
                  <th scope="col" className="amount">
                    {t("cf.actualNet")}
                  </th>
                  {[1, 4, 13].map((h) => (
                    <th scope="col" className="amount" key={h}>
                      {t("cf.forecastAhead").replace("{h}", String(h))}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {accuracy.data.weeks.map((w) => (
                  <tr key={w.label}>
                    <td>{w.label}</td>
                    <td className="amount">{formatAmount(w.actual, locale)}</td>
                    {[1, 4, 13].map((h) => (
                      <td className="amount" key={h}>
                        {cell(w, h)}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      ) : null}
    </section>
  );
}

function SettingsPanel() {
  const { t } = useI18n();
  const settings = useForecastSettings();
  const { saveSettings } = useForecastMutations();
  const [minimum, setMinimum] = useState<string | null>(null);
  if (!settings.data) {
    return <ProblemMessage error={settings.error} />;
  }
  const current = settings.data;
  const value = minimum ?? current.minimum_cash;
  return (
    <form
      className="inline-form"
      onSubmit={(e) => {
        e.preventDefault();
        saveSettings.mutate(
          { ...current, minimum_cash: value },
          { onSuccess: () => setMinimum(null) },
        );
      }}
    >
      <label>
        {t("cf.minimumCash")}
        <input
          inputMode="decimal"
          className="narrow"
          value={value}
          onChange={(e) => setMinimum(e.target.value)}
        />
      </label>
      <button type="submit" disabled={saveSettings.isPending}>
        {t("cf.save")}
      </button>
      <ProblemMessage error={saveSettings.error} />
    </form>
  );
}

// --- page -------------------------------------------------------------------------------------

export function CashForecastPage() {
  const { t, locale } = useI18n();
  const latest = useLatestForecast();
  const { run, refreshNow } = useForecastMutations();
  const [selected, setSelected] = useState<string | null>(null);
  const [whatIf, setWhatIf] = useState<WhatIfResult | null>(null);
  const forecast = latest.data ?? null;
  const week = useMemo(
    () => forecast?.weeks.find((w) => w.label === selected) ?? null,
    [forecast, selected],
  );
  const deltas = new Map(whatIf?.weeks.map((w) => [w.label, w]) ?? []);

  return (
    <Page
      title={t("cf.title")}
      actions={
        <button
          type="button"
          className="primary"
          disabled={run.isPending}
          onClick={() =>
            run.mutate(undefined, { onSuccess: () => setWhatIf(null) })
          }
        >
          {t("cf.run")}
        </button>
      }
    >
      <SettingsPanel />
      {latest.isPending ? <Loading /> : null}
      <ProblemMessage error={latest.error ?? run.error ?? refreshNow.error} />
      {latest.data === null ? <p>{t("cf.none")}</p> : null}
      {forecast ? (
        <>
          {forecast.stale ? (
            <div className="panel warn" role="status">
              <strong>{t("cf.staleTitle")}</strong>
              <ul>
                {forecast.stale_reasons.map((r) => (
                  <li key={r}>{r}</li>
                ))}
              </ul>
              <button
                type="button"
                onClick={() => refreshNow.mutate()}
                disabled={refreshNow.isPending}
              >
                {t("cf.refresh")}
              </button>
            </div>
          ) : null}
          {forecast.warnings.length ? (
            <div className="panel warn">
              <strong>{t("cf.dataQuality")}</strong>
              <ul>
                {forecast.warnings.map((w) => (
                  <li key={`${w.code}-${w.message}`}>{w.message}</li>
                ))}
              </ul>
            </div>
          ) : null}
          <p>
            {t("cf.summary")
              .replace("{asOf}", forecast.as_of)
              .replace("{opening}", formatAmount(forecast.opening_cash, locale))
              .replace(
                "{closing}",
                formatAmount(
                  forecast.weeks[forecast.weeks.length - 1]?.closing ?? "0",
                  locale,
                ),
              )}{" "}
            {forecast.first_shortfall
              ? t("cf.shortfallOn")
                  .replace("{date}", forecast.first_shortfall.date)
                  .replace(
                    "{balance}",
                    formatAmount(forecast.first_shortfall.balance, locale),
                  )
              : t("cf.noShortfall")}
          </p>
          <ForecastChart forecast={forecast} whatIf={whatIf} />
          <div className="table-scroll">
            <table>
              <caption>{t("cf.weeks")}</caption>
              <thead>
                <tr>
                  <th scope="col">{t("cf.week")}</th>
                  <th scope="col" className="amount">
                    {t("cf.opening")}
                  </th>
                  <th scope="col" className="amount">
                    {t("cf.inflows")}
                  </th>
                  <th scope="col" className="amount">
                    {t("cf.outflows")}
                  </th>
                  <th scope="col" className="amount">
                    {t("cf.closing")}
                  </th>
                  <th scope="col" className="amount">
                    {t("cf.headroom")}
                  </th>
                  <th scope="col" className="amount">
                    {t("cf.liquidity")}
                  </th>
                  {whatIf ? (
                    <th scope="col" className="amount">
                      {t("cf.whatIfDelta")}
                    </th>
                  ) : null}
                  <th scope="col">{t("cf.nature")}</th>
                </tr>
              </thead>
              <tbody>
                {forecast.weeks.map((w) => (
                  <tr key={w.label} className={w.shortfall ? "shortfall" : ""}>
                    <th scope="row">
                      <button
                        type="button"
                        className="link"
                        aria-pressed={selected === w.label}
                        onClick={() =>
                          setSelected(selected === w.label ? null : w.label)
                        }
                      >
                        {w.label}
                      </button>
                      {w.shortfall ? (
                        <span className="badge badge-warn">
                          {" "}
                          ! {t("cf.shortfall")}
                        </span>
                      ) : null}
                    </th>
                    <td className="amount">
                      {formatAmount(w.opening, locale)}
                      {w.index === 1 ? (
                        <>
                          {" "}
                          <NatureTag nature="ACTUAL" />
                        </>
                      ) : null}
                    </td>
                    <td className="amount">
                      {formatAmount(w.inflows, locale)}
                    </td>
                    <td className="amount">
                      {formatAmount(`-${w.outflows}`, locale)}
                    </td>
                    <td className="amount">
                      {formatAmount(w.closing, locale)}
                    </td>
                    <td className="amount">
                      {formatAmount(w.headroom, locale)}
                    </td>
                    <td className="amount">
                      {formatAmount(w.liquidity, locale)}
                    </td>
                    {whatIf ? (
                      <td className="amount">
                        {formatAmount(
                          deltas.get(w.label)?.delta ?? "0.00",
                          locale,
                        )}
                      </td>
                    ) : null}
                    <td>
                      <NatureTag nature="FORECAST" />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {week ? (
            <WeekDetail runId={forecast.run_id} week={week} />
          ) : (
            <p className="muted">{t("cf.pickWeek")}</p>
          )}
          <WhatIfPanel forecast={forecast} onResult={setWhatIf} />
          <HistorySection />
          <AccuracySection />
        </>
      ) : null}
    </Page>
  );
}
