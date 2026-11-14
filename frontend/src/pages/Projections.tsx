// Projections (M6-6): run a three-statement projection from approved assumptions, read it with a
// nature on every column, see its six checks, explain a line, chart cash (with a table
// alternative), export to Excel, and keep a rolling forecast with its accuracy.
import Decimal from "decimal.js";
import { useState } from "react";
import { apiUrl } from "../api/client";
import { useExplain } from "../api/forecast";
import { useScope } from "../api/hooks";
import {
  type Granularity,
  type ProjectionRun,
  type ProjectionStatements,
  useAssumptionSets,
  useProjection,
  useProjectionMutations,
  useProjections,
  useRolling,
  useRollingAccuracy,
  useRollingMutations,
} from "../api/projections";
import { Loading, Page, ProblemMessage } from "../components/common";
import { useI18n } from "../i18n/I18n";
import type { MessageKey } from "../i18n/messages";
import { formatAmount } from "../money";
import { NatureTag } from "./CashForecast";

type Kind = "line" | "subtotal" | "total";
const REVENUE = ["REV.SALES", "REV.SERVICES", "REV.OTHER"];
const OPEX = [
  "OPEX.PAYROLL",
  "OPEX.RENT",
  "OPEX.UTILITIES",
  "OPEX.PROFESSIONAL",
  "OPEX.MARKETING",
  "OPEX.TRAVEL",
  "OPEX.INSURANCE",
  "OPEX.OTHER",
];
const line = (k: string): [string, Kind] => [k, "line"];
export const STATEMENTS: {
  code: "IS" | "BS" | "CF";
  rows: [string, Kind][];
}[] = [
  {
    code: "IS",
    rows: [
      ...REVENUE.map((c) => line(`PL.${c}`)),
      ["PL.REVENUE", "subtotal"],
      line("PL.COGS"),
      ["PL.GROSS_PROFIT", "subtotal"],
      ...OPEX.map((c) => line(`PL.${c}`)),
      ["PL.OPEX", "subtotal"],
      ["PL.EBITDA", "subtotal"],
      line("PL.DA"),
      ["PL.EBIT", "subtotal"],
      line("PL.INTEREST"),
      ["PL.PBT", "subtotal"],
      line("PL.TAX"),
      ["PL.NET_INCOME", "total"],
    ],
  },
  {
    code: "BS",
    rows: [
      ...[
        "BS.PPE.GROSS",
        "BS.PPE.ACCDEP",
        "BS.INTANGIBLES",
        "BS.INVESTMENTS",
        "BS.INVENTORY",
        "BS.AR",
        "BS.OTHER_REC",
        "BS.TAX_REC",
        "BS.CASH",
      ].map(line),
      ["BS.TOTAL_ASSETS", "total"],
      ...[
        "BS.DEBT.NONCURRENT",
        "BS.DEBT.CURRENT",
        "BS.AP",
        "BS.OTHER_PAY",
        "BS.TAX_PAY",
      ].map(line),
      ["BS.TOTAL_LIABILITIES", "subtotal"],
      ...[
        "BS.EQUITY.SHARE_CAPITAL",
        "BS.EQUITY.SHARE_PREMIUM",
        "BS.EQUITY.RETAINED",
      ].map(line),
      ["BS.TOTAL_EQUITY", "subtotal"],
      ["BS.TOTAL_LIABILITIES_EQUITY", "total"],
    ],
  },
  {
    code: "CF",
    rows: [
      ...[
        "CF.NET_INCOME",
        "CF.DA",
        "CF.WC.AR",
        "CF.WC.INVENTORY",
        "CF.WC.AP",
        "CF.WC.TAX",
      ].map(line),
      ["CF.OPERATING", "subtotal"],
      line("CF.CAPEX"),
      ["CF.INVESTING", "subtotal"],
      ...[
        "CF.BORROWING",
        "CF.REPAYMENT",
        "CF.SHARE_CAPITAL",
        "CF.DIVIDENDS",
        "CF.REVOLVER",
      ].map(line),
      ["CF.FINANCING", "subtotal"],
      ["CF.NET_CHANGE", "subtotal"],
      line("CF.OPENING_CASH"),
      ["CF.CLOSING_CASH", "total"],
    ],
  },
];
const INVARIANTS = [
  "balance_sheet_balances",
  "cash_ties",
  "retained_earnings_roll",
  "opening_equals_previous_closing",
  "roll_forwards_tie",
  "aggregation_consistent",
];

export function columnLabel(
  c: { start: string; end: string },
  granularity: Granularity,
): string {
  if (granularity === "MONTH") return c.start.slice(0, 7);
  if (granularity === "YEAR")
    return `${c.start.slice(0, 7)} – ${c.end.slice(0, 7)}`;
  return `${c.start.slice(0, 7)} – ${c.end.slice(0, 7)}`;
}

function Checks({ run, failures }: { run: ProjectionRun; failures: string[] }) {
  const { t } = useI18n();
  return (
    <section className="card" aria-labelledby="pj-checks">
      <h2 id="pj-checks">{t("pj.checks")}</h2>
      <ul className="checklist">
        {INVARIANTS.map((name) => {
          const ok = run.invariants[name] === true;
          return (
            <li key={name}>
              <span className={ok ? "badge badge-posted" : "badge badge-warn"}>
                {ok ? `✓ ${t("pj.holds")}` : `✗ ${t("pj.fails")}`}
              </span>{" "}
              {t(`pj.inv.${name}` as MessageKey)}
            </li>
          );
        })}
      </ul>
      {failures.length ? (
        <p role="alert">
          {t("pj.failedAt")}{" "}
          {failures
            .map((f) => {
              const [name, where] = f.split("@");
              return `${t(`pj.inv.${name}` as MessageKey)} (${where})`;
            })
            .join("; ")}
        </p>
      ) : null}
    </section>
  );
}

function Explain({
  runId,
  resultId,
  label,
  onClose,
}: {
  runId: string;
  resultId: string;
  label: string;
  onClose: () => void;
}) {
  const { t, locale } = useI18n();
  const explained = useExplain(runId, resultId);
  return (
    <section className="panel" aria-labelledby="pj-explain" aria-live="polite">
      <h3 id="pj-explain">
        {t("pj.explainTitle")}: {label}
      </h3>
      {explained.isLoading ? <Loading /> : null}
      {explained.error ? <ProblemMessage error={explained.error} /> : null}
      <ul>
        {explained.data?.lineage.map((x) => (
          <li key={`${x.input_kind}-${x.input_ref}`}>
            <strong>{t(`pj.src.${x.input_kind}` as MessageKey)}</strong>:{" "}
            {x.note || x.input_ref}
            {x.amount !== null ? ` (${formatAmount(x.amount, locale)})` : ""}
          </li>
        ))}
      </ul>
      <button type="button" onClick={onClose}>
        {t("pj.close")}
      </button>
    </section>
  );
}

function Statement({
  data,
  code,
  rows,
  granularity,
  onExplain,
}: {
  data: ProjectionStatements;
  code: "IS" | "BS" | "CF";
  rows: [string, Kind][];
  granularity: Granularity;
  onExplain: (key: string, index: number) => void;
}) {
  const { t, locale } = useI18n();
  const columns = data.columns
    .map((c, i) => ({ ...c, i }))
    .filter((c) => code === "BS" || c.nature !== "ACTUAL");
  return (
    <div className="table-scroll">
      <table className="statement">
        <caption>{t(`pj.st.${code}` as MessageKey)}</caption>
        <thead>
          <tr>
            <th scope="col">{t("pj.line")}</th>
            {columns.map((c) => (
              <th
                scope="col"
                key={c.i}
                className={c.nature === "ACTUAL" ? "divider-after" : ""}
              >
                {c.nature === "ACTUAL"
                  ? t("pj.opening")
                  : columnLabel(c, granularity)}
              </th>
            ))}
          </tr>
          <tr>
            <th scope="row">{t("pj.nature")}</th>
            {columns.map((c) => (
              <td key={c.i}>
                <NatureTag nature={c.nature} />
              </td>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map(([key, kind]) => (
            <tr key={key} className={kind}>
              <th scope="row">{t(`pj.k.${key}` as MessageKey)}</th>
              {columns.map((c) => {
                const value = data.rows[key]?.[c.i] ?? null;
                const id = data.result_ids[key]?.[c.i] ?? null;
                return (
                  <td key={c.i} className="amount">
                    {value === null ? (
                      ""
                    ) : id ? (
                      <button
                        type="button"
                        className="link"
                        onClick={() => onExplain(key, c.i)}
                        aria-label={`${t("pj.explain")} ${t(`pj.k.${key}` as MessageKey)} ${c.nature === "ACTUAL" ? t("pj.opening") : columnLabel(c, granularity)}`}
                      >
                        {formatAmount(value, locale)}
                      </button>
                    ) : (
                      formatAmount(value, locale)
                    )}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

const W = 720;
const H = 220;
const PAD = { left: 76, right: 16, top: 16, bottom: 32 };

/** Closing cash as SVG: the actual opening is a solid point, forecast months a dashed line. The
 * statement table above is the table alternative; the figures here only place pixels. */
export function CashChart({
  data,
  granularity,
}: {
  data: ProjectionStatements;
  granularity: Granularity;
}) {
  const { t, locale } = useI18n();
  const cash = data.rows["BS.CASH"] ?? [];
  const points = data.columns
    .map((c, i) => ({ c, v: cash[i] ?? null }))
    .filter(
      (p): p is { c: (typeof data.columns)[number]; v: string } => p.v !== null,
    );
  if (points.length < 2) return null;
  const values = points.map((p) => new Decimal(p.v));
  const low = Decimal.min(...values, 0);
  const high = Decimal.max(...values, 1);
  const span = high.minus(low).isZero() ? new Decimal(1) : high.minus(low);
  const x = (i: number) =>
    PAD.left + (i * (W - PAD.left - PAD.right)) / (points.length - 1);
  const y = (v: string | Decimal) =>
    PAD.top + high.minus(v).div(span).toNumber() * (H - PAD.top - PAD.bottom);
  const path = points
    .map(
      (p, i) => `${i === 0 ? "M" : "L"}${x(i).toFixed(1)},${y(p.v).toFixed(1)}`,
    )
    .join(" ");
  const first = points[0];
  const last = points[points.length - 1];
  const description = t("pj.chartDescription")
    .replace("{opening}", formatAmount(first?.v ?? "0", locale))
    .replace("{closing}", formatAmount(last?.v ?? "0", locale))
    .replace("{end}", last?.c.end ?? "");
  return (
    <figure className="chart">
      <svg
        viewBox={`0 0 ${W} ${H}`}
        role="img"
        aria-labelledby="pj-chart-title"
        aria-describedby="pj-chart-desc"
      >
        <title id="pj-chart-title">{t("pj.chartTitle")}</title>
        <desc id="pj-chart-desc">{description}</desc>
        {[high, low].map((v) => (
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
        <path d={path} className="chart-forecast" />
        {points.map((p, i) =>
          p.c.nature === "ACTUAL" ? (
            <circle
              key={i}
              cx={x(i)}
              cy={y(p.v)}
              r={5}
              className="chart-actual"
            />
          ) : (
            <circle
              key={i}
              cx={x(i)}
              cy={y(p.v)}
              r={3}
              className="chart-point"
            />
          ),
        )}
        {points.map((p, i) =>
          i % Math.max(1, Math.ceil(points.length / 8)) === 0 ? (
            <text
              key={`l${i}`}
              x={x(i)}
              y={H - PAD.bottom + 16}
              textAnchor="middle"
              className="chart-axis"
            >
              {p.c.nature === "ACTUAL"
                ? t("pj.opening")
                : columnLabel(p.c, granularity).slice(0, 7)}
            </text>
          ) : null,
        )}
      </svg>
      <figcaption className="chart-legend">
        <span>
          <svg width="28" height="10" aria-hidden="true">
            <circle cx="14" cy="5" r="4" className="chart-actual" />
          </svg>
          {t("pj.legendActual")}
        </span>
        <span>
          <svg width="28" height="10" aria-hidden="true">
            <line x1="0" x2="28" y1="5" y2="5" className="chart-forecast" />
          </svg>
          {t("pj.legendForecast")}
        </span>
      </figcaption>
    </figure>
  );
}

function RunPanel({ onRun }: { onRun: (id: string) => void }) {
  const { t } = useI18n();
  const sets = useAssumptionSets();
  const m = useProjectionMutations();
  const approved = (sets.data ?? []).filter((s) => s.status === "APPROVED");
  const [setId, setSetId] = useState("");
  const chosen = setId || approved[0]?.id || "";
  return (
    <section className="card" aria-labelledby="pj-run">
      <h2 id="pj-run">{t("pj.run")}</h2>
      {approved.length === 0 ? (
        <p>{t("pj.noApproved")}</p>
      ) : (
        <div className="form inline">
          <label>
            {t("pj.set")}
            <select value={chosen} onChange={(e) => setSetId(e.target.value)}>
              {approved.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name} (v{s.version}, {s.cutover})
                </option>
              ))}
            </select>
          </label>
          <button
            type="button"
            disabled={!chosen || m.run.isPending}
            onClick={() =>
              m.run.mutate(chosen, { onSuccess: (run) => onRun(run.id) })
            }
          >
            {t("pj.runButton")}
          </button>
        </div>
      )}
      {m.run.error ? <ProblemMessage error={m.run.error} /> : null}
    </section>
  );
}

function RollingSection() {
  const { t, locale } = useI18n();
  const rolling = useRolling();
  const sets = useAssumptionSets();
  const m = useRollingMutations();
  const accuracy = useRollingAccuracy(!!rolling.data?.configured);
  const approved = (sets.data ?? []).filter((s) => s.status === "APPROVED");
  const [form, setForm] = useState<{ set: string; horizon: number } | null>(
    null,
  );
  const current = rolling.data;
  const setId =
    form?.set ?? current?.assumption_set_id ?? approved[0]?.id ?? "";
  const horizon = form?.horizon ?? current?.horizon ?? 12;
  const withComparisons = (accuracy.data ?? []).filter((a) =>
    Object.values(a.comparisons).some((c) => c.length > 0),
  );
  return (
    <section className="card" aria-labelledby="pj-rolling">
      <h2 id="pj-rolling">{t("pj.rolling")}</h2>
      <p>{t("pj.rollingIntro")}</p>
      {rolling.isLoading ? <Loading /> : null}
      {current?.configured ? (
        <p>
          <span
            className={
              current.stale ? "badge badge-warn" : "badge badge-posted"
            }
          >
            {current.stale ? t("pj.stale") : t("pj.current")}
          </span>{" "}
          {current.stale ? current.stale_reasons.join("; ") : null}
          {current.latest
            ? ` ${t("pj.latestTo")} ${current.latest.as_of_date} (${current.latest.status})`
            : null}
        </p>
      ) : null}
      {approved.length ? (
        <div className="form inline">
          <label>
            {t("pj.set")}
            <select
              value={setId}
              onChange={(e) => setForm({ set: e.target.value, horizon })}
            >
              {approved.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name} (v{s.version})
                </option>
              ))}
            </select>
          </label>
          <label>
            {t("as.horizon")}
            <select
              value={horizon}
              onChange={(e) =>
                setForm({ set: setId, horizon: Number(e.target.value) })
              }
            >
              {[12, 24].map((n) => (
                <option key={n} value={n}>
                  {n} {t("fa.months")}
                </option>
              ))}
            </select>
          </label>
          <button
            type="button"
            disabled={!setId || m.configure.isPending}
            onClick={() =>
              m.configure.mutate({
                assumption_set_id: setId,
                horizon,
                active: true,
              })
            }
          >
            {t("pj.saveRolling")}
          </button>
          {current?.configured ? (
            <button
              type="button"
              disabled={m.refresh.isPending}
              onClick={() => m.refresh.mutate()}
            >
              {t("pj.refresh")}
            </button>
          ) : null}
        </div>
      ) : (
        <p>{t("pj.noApproved")}</p>
      )}
      {m.configure.error ? <ProblemMessage error={m.configure.error} /> : null}
      {m.refresh.error ? <ProblemMessage error={m.refresh.error} /> : null}
      {current?.configured ? (
        <>
          <h3>{t("pj.accuracy")}</h3>
          {withComparisons.length === 0 ? (
            <p>{t("pj.noAccuracy")}</p>
          ) : (
            <div className="table-scroll">
              <table>
                <caption>{t("pj.accuracyCaption")}</caption>
                <thead>
                  <tr>
                    <th scope="col">{t("pj.month")}</th>
                    <th scope="col">{t("pj.measure")}</th>
                    <th scope="col">{t("pj.actual")}</th>
                    <th scope="col">{t("pj.monthsBefore")}</th>
                    <th scope="col">{t("pj.forecast")}</th>
                    <th scope="col">{t("pj.error")}</th>
                    <th scope="col">{t("pj.errorPct")}</th>
                  </tr>
                </thead>
                <tbody>
                  {withComparisons.flatMap((a) =>
                    Object.entries(a.comparisons).flatMap(([measure, cs]) =>
                      cs.map((c) => (
                        <tr key={`${a.month}-${measure}-${c.months_before}`}>
                          <td>{a.month.slice(0, 7)}</td>
                          <td>{t(`pj.k.${measure}` as MessageKey)}</td>
                          <td className="amount">
                            {formatAmount(a.actual[measure] ?? "0", locale)}
                          </td>
                          <td className="amount">{c.months_before}</td>
                          <td className="amount">
                            {formatAmount(c.forecast, locale)}
                          </td>
                          <td className="amount">
                            {formatAmount(c.error, locale)}
                          </td>
                          <td className="amount">
                            {c.error_pct === null
                              ? t("pj.nm")
                              : `${c.error_pct}%`}
                          </td>
                        </tr>
                      )),
                    ),
                  )}
                </tbody>
              </table>
            </div>
          )}
        </>
      ) : null}
    </section>
  );
}

export function ProjectionsPage() {
  const { t } = useI18n();
  const { base } = useScope();
  const list = useProjections();
  const m = useProjectionMutations();
  const [selected, setSelected] = useState<string | null>(null);
  const [granularity, setGranularity] = useState<Granularity>("MONTH");
  const [explain, setExplain] = useState<{ key: string; index: number } | null>(
    null,
  );
  const runId = selected ?? list.data?.[0]?.id ?? null;
  const shown = useProjection(runId, granularity);
  const data = shown.data;
  const explainId =
    explain && data
      ? (data.result_ids[explain.key]?.[explain.index] ?? null)
      : null;
  return (
    <Page title={t("nav.projections")}>
      <p>{t("pj.intro")}</p>
      <RunPanel onRun={(id) => setSelected(id)} />
      <section className="card" aria-labelledby="pj-list">
        <h2 id="pj-list">{t("pj.list")}</h2>
        {list.isLoading ? <Loading /> : null}
        {list.data && list.data.length === 0 ? <p>{t("pj.none")}</p> : null}
        {list.data?.length ? (
          <label>
            {t("pj.choose")}
            <select
              value={runId ?? ""}
              onChange={(e) => {
                setSelected(e.target.value);
                setExplain(null);
              }}
            >
              {list.data.map((r) => (
                <option key={r.id} value={r.id}>
                  {r.created_at.slice(0, 16).replace("T", " ")} · {t("pj.to")}{" "}
                  {r.as_of_date} · {t(`pj.status.${r.status}` as MessageKey)}
                  {r.is_published ? ` · ${t("pj.published")}` : ""}
                  {r.stale ? ` · ${t("pj.stale")}` : ""}
                </option>
              ))}
            </select>
          </label>
        ) : null}
      </section>
      {shown.error ? <ProblemMessage error={shown.error} /> : null}
      {data ? (
        <>
          <section className="card" aria-labelledby="pj-shown">
            <h2 id="pj-shown">
              {t("pj.shown")} {data.projection.as_of_date}
            </h2>
            <p>{t("pj.forecastNote")}</p>
            <div className="actions">
              <span role="group" aria-label={t("pj.granularity")}>
                {(["MONTH", "QUARTER", "YEAR"] as Granularity[]).map((g) => (
                  <button
                    key={g}
                    type="button"
                    aria-pressed={granularity === g}
                    onClick={() => setGranularity(g)}
                  >
                    {t(`pj.g.${g}` as MessageKey)}
                  </button>
                ))}
              </span>
              <a
                className="button"
                href={apiUrl(
                  `${base}/projections/${data.projection.id}/export`,
                  {
                    granularity,
                  },
                )}
              >
                {t("pj.export")}
              </a>
              {data.projection.status === "VALID" &&
              !data.projection.is_published ? (
                <button
                  type="button"
                  disabled={m.publish.isPending}
                  onClick={() => m.publish.mutate(data.projection.id)}
                >
                  {t("pj.publish")}
                </button>
              ) : null}
              {data.projection.is_published ? (
                <span className="badge badge-posted">{t("pj.published")}</span>
              ) : null}
            </div>
            {m.publish.error ? (
              <ProblemMessage error={m.publish.error} />
            ) : null}
          </section>
          <Checks run={data.projection} failures={data.failures} />
          <CashChart data={data} granularity={granularity} />
          {explain && explainId ? (
            <Explain
              runId={data.projection.id}
              resultId={explainId}
              label={t(`pj.k.${explain.key}` as MessageKey)}
              onClose={() => setExplain(null)}
            />
          ) : null}
          {STATEMENTS.map((s) => (
            <Statement
              key={s.code}
              data={data}
              code={s.code}
              rows={s.rows}
              granularity={granularity}
              onExplain={(key, index) => setExplain({ key, index })}
            />
          ))}
        </>
      ) : null}
      <RollingSection />
    </Page>
  );
}
