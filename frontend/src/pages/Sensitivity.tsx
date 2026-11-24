// Sensitivity and tornado (M7-7 for M7-3): which assumptions matter most. One assumption over a
// range, or every assumption down and up by the same %, ranked by how much the result moves. The
// results are hypothetical and are not saved; each chart has a table with the same figures.
import { type SyntheticEvent, useState } from "react";
import { useAssumptionSets } from "../api/projections";
import {
  type Analysis,
  type AnalysisBase,
  type SensitivityOutput,
  useScenarios,
  useSensitivity,
} from "../api/scenarios";
import { Page, ProblemMessage } from "../components/common";
import { useI18n } from "../i18n/I18n";
import type { MessageKey } from "../i18n/messages";
import { formatAmount } from "../money";

const OUTPUTS: SensitivityOutput[] = [
  "MIN_CASH",
  "CLOSING_CASH",
  "FIRST_SHORTFALL",
  "EBITDA",
  "NET_INCOME",
];
const DRIVERS = [
  "revenue",
  "gross_margin",
  "opex",
  "dso",
  "dio",
  "dpo",
  "interest_rate",
  "capex",
];

/** The base picker: an approved assumption set, or a shared scenario. */
export function BasePicker({
  value,
  onChange,
}: {
  value: string;
  onChange: (v: string) => void;
}) {
  const { t } = useI18n();
  const sets = (useAssumptionSets().data ?? []).filter(
    (s) => s.status === "APPROVED",
  );
  const shared = (useScenarios().data ?? []).filter(
    (s) => s.status === "SHARED",
  );
  return (
    <label>
      {t("se.base")}
      <select value={value} onChange={(e) => onChange(e.target.value)}>
        <option value="">{t("se.choose")}</option>
        <optgroup label={t("se.sets")}>
          {sets.map((s) => (
            <option key={s.id} value={`set:${s.id}`}>
              {s.name} v{s.version}
            </option>
          ))}
        </optgroup>
        <optgroup label={t("se.scenarios")}>
          {shared.map((s) => (
            <option key={s.id} value={`scenario:${s.id}`}>
              {s.name}
            </option>
          ))}
        </optgroup>
      </select>
    </label>
  );
}

export function baseOf(choice: string): {
  base_set_id?: string;
  scenario_id?: string;
} {
  const [kind, id] = choice.split(":");
  if (!id) return {};
  return kind === "set" ? { base_set_id: id } : { scenario_id: id };
}

const W = 720;
const ROW = 26;
const LEFT = 190;

export function TornadoChart({ a }: { a: Analysis }) {
  const { t, locale } = useI18n();
  if (!a.bars.length) return null;
  const base = Number(a.base.value);
  const values = a.bars.flatMap((b) => [
    Number(b.low.value),
    Number(b.high.value),
  ]);
  const lo = Math.min(base, ...values);
  const hi = Math.max(base, ...values);
  const span = hi - lo || 1;
  const x = (v: number) => LEFT + ((v - lo) / span) * (W - LEFT - 20);
  const h = ROW * a.bars.length + 40;
  const top = a.bars[0];
  return (
    <figure className="chart">
      <svg
        viewBox={`0 0 ${W} ${h}`}
        role="img"
        aria-labelledby="se-tornado-t"
        aria-describedby="se-tornado-d"
      >
        <title id="se-tornado-t">{t("se.tornadoTitle")}</title>
        <desc id="se-tornado-d">
          {t("se.tornadoDescription")
            .replace("{driver}", top?.label ?? "")
            .replace("{swing}", formatAmount(top?.swing ?? "0", locale))}
        </desc>
        <line
          x1={x(base)}
          x2={x(base)}
          y1={10}
          y2={h - 20}
          className="chart-grid"
        />
        {a.bars.map((b, i) => {
          const y = 14 + i * ROW;
          const l = x(Number(b.low.value));
          const r = x(Number(b.high.value));
          return (
            <g key={b.driver}>
              <text
                x={LEFT - 8}
                y={y + 13}
                textAnchor="end"
                className="chart-axis"
              >
                {b.label}
              </text>
              <rect
                x={Math.min(l, x(base))}
                y={y}
                width={Math.abs(x(base) - l)}
                height={ROW - 8}
                className="chart-bar-low"
              />
              <rect
                x={Math.min(r, x(base))}
                y={y}
                width={Math.abs(r - x(base))}
                height={ROW - 8}
                className="chart-bar-high"
              />
            </g>
          );
        })}
      </svg>
      <figcaption className="chart-legend">
        <span>{t("se.legendLow")}</span>
        <span>{t("se.legendHigh")}</span>
        <span>
          {t("se.baseValue")}: {formatAmount(a.base.value, locale)}
        </span>
      </figcaption>
    </figure>
  );
}

function Result({ a }: { a: Analysis }) {
  const { t, locale } = useI18n();
  const shown = (v: string) =>
    a.output === "FIRST_SHORTFALL"
      ? `${v} ${t("se.months")}`
      : formatAmount(v, locale);
  return (
    <>
      <p role="status">
        {a.base_label} · {t(`se.o.${a.output}` as MessageKey)}
        {a.year ? ` ${a.year}` : ""} · {t("nature.HYPOTHETICAL")}
        {a.cached ? ` · ${t("se.cached")}` : ""}
      </p>
      {a.kind === "TORNADO" ? (
        <>
          <TornadoChart a={a} />
          <div className="table-scroll">
            <table>
              <caption>{t("se.tornadoTable")}</caption>
              <thead>
                <tr>
                  <th scope="col">{t("se.driver")}</th>
                  <th scope="col">{t("se.low")}</th>
                  <th scope="col">{t("se.high")}</th>
                  <th scope="col">{t("se.swing")}</th>
                </tr>
              </thead>
              <tbody>
                {a.bars.map((b) => (
                  <tr key={b.driver}>
                    <th scope="row">{b.label}</th>
                    <td className="amount">{shown(b.low.value)}</td>
                    <td className="amount">{shown(b.high.value)}</td>
                    <td className="amount">{shown(b.swing)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      ) : (
        <div className="table-scroll">
          <table>
            <caption>{t("se.oneTable")}</caption>
            <thead>
              <tr>
                <th scope="col">{t("se.shock")}</th>
                <th scope="col">{t("se.result")}</th>
                <th scope="col">{t("se.change")}</th>
              </tr>
            </thead>
            <tbody>
              {a.points.map((p) => (
                <tr key={p.shock}>
                  <th scope="row">{p.shock}</th>
                  <td className="amount">{shown(p.result.value)}</td>
                  <td className="amount">{shown(p.change)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}

export function SensitivityPage() {
  const { t } = useI18n();
  const s = useSensitivity();
  const [choice, setChoice] = useState("");
  const [output, setOutput] = useState<SensitivityOutput>("MIN_CASH");
  const [year, setYear] = useState(() => new Date().getFullYear() + 1);
  const [mode, setMode] = useState<"TORNADO" | "ONE">("TORNADO");
  const [percent, setPercent] = useState("10");
  const [driver, setDriver] = useState("revenue");
  const [unit, setUnit] = useState<"PERCENT" | "DAYS">("PERCENT");
  const [low, setLow] = useState("-20");
  const [high, setHigh] = useState("20");
  const [steps, setSteps] = useState(5);
  const needsYear = output === "EBITDA" || output === "NET_INCOME";
  const request: AnalysisBase = {
    ...baseOf(choice),
    output,
    year: needsYear ? year : null,
  };
  const submit = (e: SyntheticEvent) => {
    e.preventDefault();
    if (mode === "TORNADO")
      s.tornado.mutate({ ...request, drivers: [], percent });
    else s.oneVariable.mutate({ ...request, driver, unit, low, high, steps });
  };
  const result = mode === "TORNADO" ? s.tornado : s.oneVariable;
  return (
    <Page title={t("nav.sensitivity")}>
      <p>{t("se.intro")}</p>
      <p className="notice" role="note">
        {t("pj.pendingReview")}
      </p>
      <form className="form" onSubmit={submit}>
        <BasePicker value={choice} onChange={setChoice} />
        <label>
          {t("se.output")}
          <select
            value={output}
            onChange={(e) => setOutput(e.target.value as SensitivityOutput)}
          >
            {OUTPUTS.map((o) => (
              <option key={o} value={o}>
                {t(`se.o.${o}` as MessageKey)}
              </option>
            ))}
          </select>
        </label>
        {needsYear ? (
          <label>
            {t("ol.year")}
            <input
              type="number"
              value={year}
              onChange={(e) => setYear(Number(e.target.value) || year)}
            />
          </label>
        ) : null}
        <span role="group" aria-label={t("se.mode")}>
          <button
            type="button"
            aria-pressed={mode === "TORNADO"}
            onClick={() => setMode("TORNADO")}
          >
            {t("se.tornado")}
          </button>
          <button
            type="button"
            aria-pressed={mode === "ONE"}
            onClick={() => setMode("ONE")}
          >
            {t("se.one")}
          </button>
        </span>
        {mode === "TORNADO" ? (
          <label>
            {t("se.percent")}
            <input
              inputMode="decimal"
              value={percent}
              onChange={(e) => setPercent(e.target.value)}
            />
          </label>
        ) : (
          <>
            <label>
              {t("se.driver")}
              <select
                value={driver}
                onChange={(e) => setDriver(e.target.value)}
              >
                {DRIVERS.map((d) => (
                  <option key={d} value={d}>
                    {t(`se.d.${d}` as MessageKey)}
                  </option>
                ))}
              </select>
            </label>
            <label>
              {t("se.unit")}
              <select
                value={unit}
                onChange={(e) => setUnit(e.target.value as "PERCENT" | "DAYS")}
              >
                <option value="PERCENT">%</option>
                <option value="DAYS">{t("se.days")}</option>
              </select>
            </label>
            <label>
              {t("se.low")}
              <input
                inputMode="decimal"
                value={low}
                onChange={(e) => setLow(e.target.value)}
              />
            </label>
            <label>
              {t("se.high")}
              <input
                inputMode="decimal"
                value={high}
                onChange={(e) => setHigh(e.target.value)}
              />
            </label>
            <label>
              {t("se.steps")}
              <input
                type="number"
                min={2}
                max={11}
                value={steps}
                onChange={(e) => setSteps(Number(e.target.value) || 5)}
              />
            </label>
          </>
        )}
        <button type="submit" disabled={!choice || result.isPending}>
          {t("se.analyse")}
        </button>
      </form>
      {result.error ? <ProblemMessage error={result.error} /> : null}
      {result.data ? <Result a={result.data} /> : null}
    </Page>
  );
}
