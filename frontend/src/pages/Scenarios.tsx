// Scenarios (M7-7 for M7-1 and M7-2): a base (an approved assumption set) and typed changes in
// order; the comparison with the base (statements, cash, what changed and why, liquidity, KPIs).
// Every scenario figure is hypothetical: dotted lines, the scenario's name, and the word itself.
import Decimal from "decimal.js";
import { type SyntheticEvent, useState } from "react";
import { apiUrl } from "../api/client";
import { useScope } from "../api/hooks";
import { useAssumptionSets } from "../api/projections";
import {
  type Comparison,
  type Granularity,
  OVERRIDE_TYPES,
  type OverrideType,
  type Params,
  type ScenarioDetail,
  useComparison,
  useProjectedKpis,
  useScenario,
  useScenarioMutations,
  useScenarios,
} from "../api/scenarios";
import { Loading, Page, ProblemMessage } from "../components/common";
import { useI18n } from "../i18n/I18n";
import type { MessageKey } from "../i18n/messages";
import { formatAmount } from "../money";
import { formatKpi } from "./Kpis";
import { OPEX, REVENUE } from "./Projections";
import { EngineReviewNote } from "../components/ReviewNote";

type Field = {
  name: string;
  kind: "select" | "number" | "integer" | "month" | "text";
  options?: (v: Record<string, string>) => string[];
  when?: (v: Record<string, string>) => boolean;
  optional?: boolean;
};

const lines = (v: Record<string, string>) =>
  v.driver === "opex" ? OPEX : REVENUE;
const period: Field[] = [
  { name: "start_month", kind: "month", optional: true },
  { name: "end_month", kind: "month", optional: true },
];

export const FIELDS: Record<OverrideType, Field[]> = {
  PCT_CHANGE: [
    { name: "driver", kind: "select", options: () => ["revenue", "opex"] },
    { name: "percent", kind: "number" },
    ...period,
  ],
  ABS_CHANGE: [
    { name: "driver", kind: "select", options: () => ["revenue", "opex"] },
    { name: "line", kind: "select", options: lines },
    { name: "amount", kind: "number" },
    ...period,
  ],
  TIMING_SHIFT: [
    { name: "mode", kind: "select", options: () => ["DAYS", "MONTHS"] },
    {
      name: "driver",
      kind: "select",
      options: (v) =>
        v.mode === "MONTHS" ? ["revenue", "opex"] : ["dso", "dio", "dpo"],
    },
    { name: "days", kind: "integer", when: (v) => v.mode !== "MONTHS" },
    {
      name: "line",
      kind: "select",
      options: lines,
      when: (v) => v.mode === "MONTHS",
    },
    { name: "months", kind: "integer", when: (v) => v.mode === "MONTHS" },
    ...period,
  ],
  NEW_DEBT: [
    { name: "code", kind: "text" },
    { name: "amount", kind: "number" },
    { name: "drawdown_month", kind: "month" },
    { name: "term_months", kind: "integer" },
    { name: "annual_rate", kind: "number" },
    {
      name: "structure",
      kind: "select",
      options: () => ["ANNUITY", "EQUAL_PRINCIPAL", "BULLET"],
    },
    { name: "interest_only_months", kind: "integer", optional: true },
  ],
  NEW_HIRE: [
    { name: "role", kind: "text" },
    { name: "department", kind: "text", optional: true },
    { name: "headcount", kind: "integer" },
    { name: "gross_monthly_salary", kind: "number" },
    { name: "employer_cost_percent", kind: "number", optional: true },
    { name: "employer_cost_source", kind: "text", optional: true },
    ...period,
  ],
  CAPEX: [
    { name: "amount", kind: "number" },
    { name: "month", kind: "month" },
    { name: "useful_life_months", kind: "integer" },
    { name: "funding", kind: "select", options: () => ["CASH", "LOAN"] },
    { name: "term_months", kind: "integer", when: (v) => v.funding === "LOAN" },
    { name: "annual_rate", kind: "number", when: (v) => v.funding === "LOAN" },
    {
      name: "structure",
      kind: "select",
      options: () => ["ANNUITY", "EQUAL_PRINCIPAL", "BULLET"],
      when: (v) => v.funding === "LOAN",
    },
  ],
  ONE_OFF: [
    { name: "amount", kind: "number" },
    { name: "month", kind: "month" },
    {
      name: "treatment",
      kind: "select",
      options: () => ["EXPENSE", "LIABILITY_SETTLEMENT"],
    },
    {
      name: "line",
      kind: "select",
      options: () => OPEX,
      when: (v) => v.treatment !== "LIABILITY_SETTLEMENT",
    },
    {
      name: "liability",
      kind: "select",
      options: () => ["BS.OTHER_PAY", "BS.TAX_PAY"],
      when: (v) => v.treatment === "LIABILITY_SETTLEMENT",
    },
  ],
  RATE_CHANGE: [
    {
      name: "target",
      kind: "select",
      options: () => ["ALL", "FACILITY", "OTHER_DEBT", "LOANS"],
    },
    { name: "loans", kind: "text", when: (v) => v.target === "LOANS" },
    { name: "points", kind: "number" },
    { name: "from_month", kind: "month", optional: true },
  ],
};

/** The visible fields' values as the API's parameters (whole numbers as numbers). */
export function toParams(
  kind: OverrideType,
  values: Record<string, string>,
): Params {
  const out: Params = {};
  for (const f of FIELDS[kind]) {
    if (f.when && !f.when(values)) continue;
    const raw = (values[f.name] ?? f.options?.(values)[0] ?? "").trim();
    if (raw === "" && f.optional) continue;
    if (f.name === "loans") {
      out.loans = raw
        .split(",")
        .map((x) => x.trim())
        .filter(Boolean);
    } else {
      out[f.name] =
        f.kind === "integer" && /^-?\d+$/.test(raw) ? Number(raw) : raw;
    }
  }
  return out;
}

function OverrideForm({ detail }: { detail: ScenarioDetail }) {
  const { t } = useI18n();
  const m = useScenarioMutations(detail.scenario.id);
  const [kind, setKind] = useState<OverrideType>("PCT_CHANGE");
  const [values, setValues] = useState<Record<string, string>>({});
  const [rationale, setRationale] = useState("");
  const submit = (e: SyntheticEvent) => {
    e.preventDefault();
    m.addOverride.mutate(
      { type: kind, params: toParams(kind, values), rationale },
      {
        onSuccess: () => {
          setValues({});
          setRationale("");
        },
      },
    );
  };
  return (
    <form className="form" onSubmit={submit} aria-labelledby="sc-add">
      <h3 id="sc-add">{t("sc.addChange")}</h3>
      <label>
        {t("sc.type")}
        <select
          value={kind}
          onChange={(e) => {
            setKind(e.target.value as OverrideType);
            setValues({});
          }}
        >
          {OVERRIDE_TYPES.map((x) => (
            <option key={x} value={x}>
              {t(`sc.t.${x}` as MessageKey)}
            </option>
          ))}
        </select>
      </label>
      {FIELDS[kind]
        .filter((f) => !f.when || f.when(values))
        .map((f) => (
          <label key={f.name}>
            {t(`sc.f.${f.name}` as MessageKey)}
            {f.optional ? ` (${t("sc.optional")})` : ""}
            {f.kind === "select" ? (
              <select
                value={values[f.name] ?? f.options?.(values)[0] ?? ""}
                onChange={(e) =>
                  setValues({ ...values, [f.name]: e.target.value })
                }
              >
                {f.options?.(values).map((o) => (
                  <option key={o} value={o}>
                    {o}
                  </option>
                ))}
              </select>
            ) : (
              <input
                type={f.kind === "month" ? "month" : "text"}
                inputMode={
                  f.kind === "number" || f.kind === "integer"
                    ? "decimal"
                    : undefined
                }
                value={values[f.name] ?? ""}
                onChange={(e) =>
                  setValues({ ...values, [f.name]: e.target.value })
                }
              />
            )}
          </label>
        ))}
      {kind === "NEW_HIRE" ? <p className="hint">{t("sc.hireNote")}</p> : null}
      <label>
        {t("sc.rationale")} ({t("sc.optional")})
        <input
          value={rationale}
          onChange={(e) => setRationale(e.target.value)}
        />
      </label>
      <button type="submit" disabled={m.addOverride.isPending}>
        {t("sc.add")}
      </button>
      {m.addOverride.error ? (
        <ProblemMessage error={m.addOverride.error} />
      ) : null}
    </form>
  );
}

function describe(params: Params): string {
  return Object.entries(params)
    .filter(([, v]) => !(Array.isArray(v) && v.length === 0))
    .map(([k, v]) => `${k}: ${Array.isArray(v) ? v.join(", ") : v}`)
    .join(" · ");
}

function Builder({ detail }: { detail: ScenarioDetail }) {
  const { t } = useI18n();
  const s = detail.scenario;
  const m = useScenarioMutations(s.id);
  const draft = s.status === "DRAFT";
  return (
    <section className="card" aria-labelledby="sc-builder">
      <h2 id="sc-builder">
        {s.name}{" "}
        <span className="badge nature-hypothetical">
          {t("nature.HYPOTHETICAL")}
        </span>{" "}
        <span className="badge">{t(`sc.s.${s.status}` as MessageKey)}</span>
      </h2>
      <p>
        {t("sc.base")}: {detail.base.name} v{detail.base.version} (
        {detail.base.first_month.slice(0, 7)} –{" "}
        {detail.base.last_month.slice(0, 7)})
      </p>
      {detail.base.newer_version_approved ? (
        <p className="notice" role="note">
          {t("sc.newerBase")}
        </p>
      ) : null}
      <div className="table-scroll">
        <table>
          <caption>{t("sc.changes")}</caption>
          <thead>
            <tr>
              <th scope="col">#</th>
              <th scope="col">{t("sc.type")}</th>
              <th scope="col">{t("sc.params")}</th>
              <th scope="col">{t("sc.rationale")}</th>
              {draft ? <th scope="col">{t("sc.remove")}</th> : null}
            </tr>
          </thead>
          <tbody>
            {detail.overrides.length === 0 ? (
              <tr>
                <td colSpan={draft ? 5 : 4}>{t("sc.noChanges")}</td>
              </tr>
            ) : null}
            {detail.overrides.map((o) => (
              <tr key={o.id}>
                <td>{o.seq}</td>
                <td>{t(`sc.t.${o.type}` as MessageKey)}</td>
                <td>{describe(o.params)}</td>
                <td>{o.rationale}</td>
                {draft ? (
                  <td>
                    <button
                      type="button"
                      onClick={() => m.removeOverride.mutate(o.id)}
                      aria-label={`${t("sc.remove")} ${o.seq}`}
                    >
                      {t("sc.remove")}
                    </button>
                  </td>
                ) : null}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {draft ? <OverrideForm detail={detail} /> : null}
      <div className="actions">
        {draft ? (
          <button type="button" onClick={() => m.action.mutate("share")}>
            {t("sc.share")}
          </button>
        ) : null}
        <button type="button" onClick={() => m.copy.mutate({})}>
          {t("sc.copy")}
        </button>
        {s.status !== "ARCHIVED" ? (
          <button type="button" onClick={() => m.action.mutate("archive")}>
            {t("sc.archive")}
          </button>
        ) : null}
      </div>
      {m.action.error ? <ProblemMessage error={m.action.error} /> : null}
      {m.copy.error ? <ProblemMessage error={m.copy.error} /> : null}
    </section>
  );
}

const SHOWN = [
  "PL.REVENUE",
  "PL.EBITDA",
  "PL.NET_INCOME",
  "CF.NET_CHANGE",
  "BS.CASH",
  "BS.DEBT.CURRENT",
  "BS.DEBT.NONCURRENT",
];
const HEADLINES = [
  "PL.REVENUE",
  "PL.EBITDA",
  "PL.NET_INCOME",
  "CF.NET_CHANGE",
  "BS.CASH",
  "BS.DEBT",
];
const W = 720;
const H = 240;
const PAD = { left: 70, right: 16, top: 16, bottom: 30 };

/** Cash, base (dashed, forecast) against scenario (dotted, hypothetical, named in the legend). The
 * comparison table is the table alternative. */
export function ComparisonChart({ c }: { c: Comparison }) {
  const { t, locale } = useI18n();
  const row = c.rows.find((r) => r.key === "BS.CASH");
  if (!row) return null;
  const points = c.columns.flatMap((_, i) => {
    const b = row.base[i];
    const sc = row.scenario[i];
    return b && sc ? [{ b, s: sc }] : [];
  });
  const last = points[points.length - 1];
  if (points.length < 2 || !last) return null;
  const all = points.flatMap((p) => [new Decimal(p.b), new Decimal(p.s)]);
  const low = Decimal.min(...all, 0);
  const high = Decimal.max(...all, 1);
  const span = high.minus(low).isZero() ? new Decimal(1) : high.minus(low);
  const x = (k: number) =>
    PAD.left + (k * (W - PAD.left - PAD.right)) / (points.length - 1);
  const y = (v: string | Decimal) =>
    PAD.top + high.minus(v).div(span).toNumber() * (H - PAD.top - PAD.bottom);
  const path = (pick: (p: { b: string; s: string }) => string) =>
    points
      .map(
        (p, k) =>
          `${k === 0 ? "M" : "L"}${x(k).toFixed(1)},${y(pick(p)).toFixed(1)}`,
      )
      .join(" ");
  const desc = t("sc.chartDescription")
    .replace("{base}", formatAmount(last.b, locale))
    .replace("{scenario}", formatAmount(last.s, locale))
    .replace("{name}", c.scenario.name);
  return (
    <figure className="chart">
      <svg
        viewBox={`0 0 ${W} ${H}`}
        role="img"
        aria-labelledby="sc-chart-t"
        aria-describedby="sc-chart-d"
      >
        <title id="sc-chart-t">{t("sc.chartTitle")}</title>
        <desc id="sc-chart-d">{desc}</desc>
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
        <path d={path((p) => p.b)} className="chart-forecast" />
        <path d={path((p) => p.s)} className="chart-hypothetical" />
      </svg>
      <figcaption className="chart-legend">
        <span>
          <svg width="28" height="10" aria-hidden="true">
            <line x1="0" x2="28" y1="5" y2="5" className="chart-forecast" />
          </svg>
          {t("sc.legendBase")}
        </span>
        <span>
          <svg width="28" height="10" aria-hidden="true">
            <line x1="0" x2="28" y1="5" y2="5" className="chart-hypothetical" />
          </svg>
          {c.scenario.name} ({t("nature.HYPOTHETICAL")})
        </span>
      </figcaption>
    </figure>
  );
}

function columnLabel(
  start: string,
  nature: string,
  g: Granularity,
  t: (k: MessageKey) => string,
) {
  if (nature === "ACTUAL") return t("pj.opening");
  return g === "YEAR" ? start.slice(0, 4) : start.slice(0, 7);
}

function ComparisonPanel({ detail }: { detail: ScenarioDetail }) {
  const { t, locale } = useI18n();
  const { base } = useScope();
  const id = detail.scenario.id;
  const [granularity, setGranularity] = useState<Granularity>("YEAR");
  const [on, setOn] = useState(false);
  const cmp = useComparison(id, granularity, on);
  const m = useScenarioMutations(id);
  const shared = detail.scenario.status === "SHARED";
  const year = Number(detail.base.first_month.slice(0, 4));
  const kpis = useProjectedKpis(
    on && shared ? { scenario_id: id } : null,
    year,
  );
  const [draftName, setDraftName] = useState("");
  const c = cmp.data;
  const amount = (v: string | null | undefined) =>
    v == null ? "–" : formatAmount(v, locale);
  return (
    <section className="card" aria-labelledby="sc-compare">
      <h2 id="sc-compare">{t("sc.compare")}</h2>
      <EngineReviewNote />
      <div className="form inline">
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
        <button type="button" onClick={() => setOn(true)}>
          {t("sc.run")}
        </button>
      </div>
      {cmp.isLoading ? <Loading /> : null}
      {cmp.error ? <ProblemMessage error={cmp.error} /> : null}
      {c ? (
        <>
          <p role="status">
            {c.valid
              ? t("sc.valid")
              : `${t("sc.invalid")} ${c.failures.join(", ")}`}
          </p>
          {c.notes.map((n) => (
            <p key={n} className="hint">
              {n}
            </p>
          ))}
          <ComparisonChart c={c} />
          <div className="table-scroll">
            <table className="statement">
              <caption>{t("sc.tableCaption")}</caption>
              <thead>
                <tr>
                  <th scope="col">{t("pj.line")}</th>
                  <th scope="col">{t("sc.of")}</th>
                  {c.columns.map((col) => (
                    <th scope="col" key={col.start}>
                      {columnLabel(col.start, col.nature, granularity, t)}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {SHOWN.flatMap((key) =>
                  c.rows.filter((r) => r.key === key),
                ).flatMap((r) => [
                  <tr key={`${r.key}b`}>
                    <th scope="row" rowSpan={3}>
                      {t(`pj.k.${r.key}` as MessageKey)}
                    </th>
                    <td>{t("sc.legendBase")}</td>
                    {r.base.map((v, i) => (
                      <td key={i} className="amount">
                        {amount(v)}
                      </td>
                    ))}
                  </tr>,
                  <tr key={`${r.key}s`}>
                    <td>
                      {c.scenario.name} ({t("nature.HYPOTHETICAL")})
                    </td>
                    {r.scenario.map((v, i) => (
                      <td key={i} className="amount">
                        {amount(v)}
                      </td>
                    ))}
                  </tr>,
                  <tr key={`${r.key}d`} className="subtotal">
                    <td>{t("sc.difference")}</td>
                    {r.difference.map((v, i) => (
                      <td key={i} className="amount">
                        {amount(v)}
                      </td>
                    ))}
                  </tr>,
                ])}
              </tbody>
            </table>
          </div>
          <div className="table-scroll">
            <table>
              <caption>{t("sc.whatChanged")}</caption>
              <thead>
                <tr>
                  <th scope="col">{t("sc.change")}</th>
                  {HEADLINES.map((h) => (
                    <th scope="col" key={h}>
                      {t(`sc.h.${h}` as MessageKey)}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {c.effects.map((e) => (
                  <tr
                    key={e.override_id ?? "total"}
                    className={e.override_id ? "" : "total"}
                  >
                    <th scope="row">
                      {e.override_id
                        ? `${e.seq}. ${t(`sc.t.${e.type}` as MessageKey)}`
                        : t("sc.total")}
                    </th>
                    {HEADLINES.map((h) => (
                      <td key={h} className="amount">
                        {amount(e.changes[h])}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="table-scroll">
            <table>
              <caption>{t("sc.liquidity")}</caption>
              <thead>
                <tr>
                  <th scope="col">{t("sc.measure")}</th>
                  <th scope="col">{t("sc.legendBase")}</th>
                  <th scope="col">{c.scenario.name}</th>
                </tr>
              </thead>
              <tbody>
                {(
                  [
                    [
                      "lowest_cash",
                      (l: Comparison["liquidity"]["base"]) =>
                        `${amount(l.lowest_cash)} (${l.lowest_cash_month?.slice(0, 7) ?? "–"})`,
                    ],
                    [
                      "first_negative_month",
                      (l: Comparison["liquidity"]["base"]) =>
                        l.first_negative_month?.slice(0, 7) ?? t("sc.never"),
                    ],
                    [
                      "months_below_minimum",
                      (l: Comparison["liquidity"]["base"]) =>
                        String(l.months_below_minimum),
                    ],
                    [
                      "peak_facility",
                      (l: Comparison["liquidity"]["base"]) =>
                        amount(l.peak_facility),
                    ],
                    [
                      "closing_debt",
                      (l: Comparison["liquidity"]["base"]) =>
                        amount(l.closing_debt),
                    ],
                  ] as const
                ).map(([k, f]) => (
                  <tr key={k}>
                    <th scope="row">{t(`sc.l.${k}` as MessageKey)}</th>
                    <td>{f(c.liquidity.base)}</td>
                    <td>{f(c.liquidity.scenario)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {shared ? (
            kpis.data ? (
              <div className="table-scroll">
                <table>
                  <caption>
                    {t("sc.kpis")} {kpis.data.year} ({kpis.data.library})
                  </caption>
                  <thead>
                    <tr>
                      <th scope="col">KPI</th>
                      <th scope="col">{t("sc.legendBase")}</th>
                      <th scope="col">{c.scenario.name}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {kpis.data.kpis.map((k) => (
                      <tr key={k.key}>
                        <th scope="row">{k.name}</th>
                        <td className="num">
                          {formatKpi(
                            { value: k.base_value, display: k.display },
                            locale,
                          ) || "–"}
                        </td>
                        <td className="num">
                          {formatKpi(k, locale) || k.nm_reason}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : null
          ) : (
            <p className="hint">{t("sc.shareForKpis")}</p>
          )}
          <div className="actions">
            <a
              className="button"
              href={apiUrl(`${base}/scenarios/${id}/comparison/export`, {
                granularity,
                lang: locale,
              })}
            >
              {t("sc.export")}
            </a>
            <button type="button" onClick={() => m.saveRun.mutate()}>
              {t("sc.save")}
            </button>
            <label>
              {t("sc.draftName")} ({t("sc.optional")})
              <input
                value={draftName}
                onChange={(e) => setDraftName(e.target.value)}
              />
            </label>
            <button type="button" onClick={() => m.promote.mutate(draftName)}>
              {t("sc.promote")}
            </button>
          </div>
          {m.saveRun.data ? (
            <p role="status">
              {t("sc.saved")} {m.saveRun.data.status}
            </p>
          ) : null}
          {m.promote.data ? (
            <p role="status">
              {t("sc.promoted")} {m.promote.data.name}
            </p>
          ) : null}
          {m.saveRun.error ? <ProblemMessage error={m.saveRun.error} /> : null}
          {m.promote.error ? <ProblemMessage error={m.promote.error} /> : null}
        </>
      ) : null}
    </section>
  );
}

function NewScenario({ onMade }: { onMade: (id: string) => void }) {
  const { t } = useI18n();
  const sets = useAssumptionSets();
  const approved = (sets.data ?? []).filter((s) => s.status === "APPROVED");
  const m = useScenarioMutations(null);
  const [name, setName] = useState("");
  const [setId, setSetId] = useState("");
  const submit = (e: SyntheticEvent) => {
    e.preventDefault();
    m.create.mutate(
      { name, base_set_id: setId || approved[0]?.id || "", description: "" },
      { onSuccess: (s) => onMade(s.id) },
    );
  };
  return (
    <form className="form inline" onSubmit={submit} aria-labelledby="sc-new">
      <h2 id="sc-new">{t("sc.new")}</h2>
      <label>
        {t("sc.name")}
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          required
        />
      </label>
      <label>
        {t("sc.base")}
        <select value={setId} onChange={(e) => setSetId(e.target.value)}>
          {approved.map((s) => (
            <option key={s.id} value={s.id}>
              {s.name} v{s.version}
            </option>
          ))}
        </select>
      </label>
      <button type="submit" disabled={!approved.length || m.create.isPending}>
        {t("sc.create")}
      </button>
      {!sets.isLoading && !approved.length ? (
        <p className="hint">{t("sc.noBase")}</p>
      ) : null}
      {m.create.error ? <ProblemMessage error={m.create.error} /> : null}
    </form>
  );
}

export function ScenariosPage() {
  const { t } = useI18n();
  const list = useScenarios();
  const [id, setId] = useState<string | null>(null);
  const detail = useScenario(id);
  return (
    <Page title={t("nav.scenarios")}>
      <p>{t("sc.intro")}</p>
      <NewScenario onMade={setId} />
      <section className="card" aria-labelledby="sc-list">
        <h2 id="sc-list">{t("sc.list")}</h2>
        {list.isLoading ? <Loading /> : null}
        {list.error ? <ProblemMessage error={list.error} /> : null}
        <ul>
          {(list.data ?? []).map((s) => (
            <li key={s.id}>
              <button
                type="button"
                aria-pressed={id === s.id}
                onClick={() => setId(s.id)}
              >
                {s.name}
              </button>{" "}
              <span className="badge">
                {t(`sc.s.${s.status}` as MessageKey)}
              </span>
            </li>
          ))}
        </ul>
        {list.data && list.data.length === 0 ? <p>{t("sc.none")}</p> : null}
      </section>
      {detail.data ? (
        <>
          <Builder detail={detail.data} />
          <ComparisonPanel key={detail.data.scenario.id} detail={detail.data} />
        </>
      ) : null}
    </Page>
  );
}
