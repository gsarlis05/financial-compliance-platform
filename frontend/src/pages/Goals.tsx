import Decimal from "decimal.js";
import { useState } from "react";
import {
  type Goal,
  type GoalEvaluation,
  type GoalFigure,
  type GoalIn,
  type TargetType,
  useGoalMetrics,
  useGoalMutations,
  useGoals,
  useLatestEvaluation,
} from "../api/goals";
import { Loading, Page, ProblemMessage } from "../components/common";
import { useI18n } from "../i18n/I18n";
import type { MessageKey } from "../i18n/messages";
import { formatAmount } from "../money";

const TYPES: TargetType[] = [
  "ABSOLUTE",
  "CHANGE_PCT",
  "MAINTAIN_MIN",
  "MAINTAIN_MAX",
];

/** Percentages are entered as percent and sent as fractions (20 -> 0.2). */
function asPercent(display: string, type: TargetType): boolean {
  return type === "CHANGE_PCT" || display === "percent";
}

export function toFraction(text: string, percent: boolean): string {
  try {
    const n = new Decimal(text.trim().replace(",", "."));
    return (percent ? n.dividedBy(100) : n).toString();
  } catch {
    return text;
  }
}

/** A goal value for display: ratios shown as % when the metric is a percentage (rounded only
 * here). */
export function formatValue(
  value: string | null,
  unit: string,
  display: string,
  locale: string,
): string {
  if (value === null) return "";
  const n = new Decimal(value);
  if (unit === "ratio" && display === "percent")
    return `${formatAmount(n.times(100).toFixed(2), locale)}%`;
  return formatAmount(n.toFixed(2), locale);
}

function figure(
  ev: GoalEvaluation,
  key: string,
  dim?: string,
): GoalFigure | undefined {
  return ev.figures.find(
    (f) => f.key === key && (dim === undefined || f.dimensions[0] === dim),
  );
}

function StatusBadge({ status }: { status: string }) {
  const { t } = useI18n();
  const warn = status === "AT_RISK" || status === "OFF_TRACK";
  return (
    <span className={`badge ${warn ? "badge-warn" : "badge-open"}`}>
      {t(`goal.status.${status}` as MessageKey)}
    </span>
  );
}

function NewGoal({ onDone }: { onDone: () => void }) {
  const { t, locale } = useI18n();
  const metrics = useGoalMetrics();
  const m = useGoalMutations();
  const year = new Date().getFullYear();
  const [form, setForm] = useState<GoalIn>({
    name: "",
    metric: "REVENUE",
    period_start: `${String(year)}-01-01`,
    period_end: `${String(year)}-12-31`,
    target_type: "ABSOLUTE",
    target: "",
    materiality: "5",
    driver: "",
  });
  const set = (patch: Partial<GoalIn>) => setForm((f) => ({ ...f, ...patch }));
  const chosen = metrics.data?.find((x) => x.key === form.metric);
  const percent = asPercent(chosen?.display ?? "", form.target_type);
  const save = () =>
    m.create.mutate(
      {
        ...form,
        target: toFraction(form.target, percent),
        materiality: toFraction(form.materiality, true),
      },
      { onSuccess: onDone },
    );
  return (
    <section className="card" aria-labelledby="goal-new">
      <h2 id="goal-new">{t("goal.new")}</h2>
      <div className="form">
        <label>
          {t("goal.name")}
          <input
            value={form.name}
            maxLength={120}
            onChange={(e) => set({ name: e.target.value })}
          />
        </label>
        <label>
          {t("goal.metric")}
          <select
            value={form.metric}
            onChange={(e) => set({ metric: e.target.value })}
          >
            {(metrics.data ?? []).map((x) => (
              <option key={x.key} value={x.key}>
                {locale === "el" && x.name_el ? x.name_el : x.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          {t("goal.from")}
          <input
            type="date"
            value={form.period_start}
            onChange={(e) => set({ period_start: e.target.value })}
          />
        </label>
        <label>
          {t("goal.to")}
          <input
            type="date"
            value={form.period_end}
            onChange={(e) => set({ period_end: e.target.value })}
          />
        </label>
        <label>
          {t("goal.targetType")}
          <select
            value={form.target_type}
            onChange={(e) => set({ target_type: e.target.value as TargetType })}
          >
            {TYPES.map((x) => (
              <option key={x} value={x}>
                {t(`goal.type.${x}` as MessageKey)}
              </option>
            ))}
          </select>
        </label>
        <label>
          {t("goal.target")}
          {percent ? " (%)" : ""}
          <input
            inputMode="decimal"
            value={form.target}
            onChange={(e) => set({ target: e.target.value })}
          />
        </label>
        <label>
          {t("goal.materiality")} (%)
          <input
            inputMode="decimal"
            value={form.materiality}
            onChange={(e) => set({ materiality: e.target.value })}
          />
        </label>
        <label>
          {t("goal.driver")}
          <input
            value={form.driver}
            maxLength={40}
            placeholder="REVENUE"
            onChange={(e) => set({ driver: e.target.value.toUpperCase() })}
          />
        </label>
      </div>
      {chosen ? <p className="muted">{chosen.convention}</p> : null}
      <div className="form inline">
        <button
          type="button"
          className="primary"
          disabled={
            !form.name.trim() || !form.target.trim() || m.create.isPending
          }
          onClick={save}
        >
          {t("goal.create")}
        </button>
        <button type="button" onClick={onDone}>
          {t("ck.cancel")}
        </button>
      </div>
      <p className="muted">{t("goal.baselineNote")}</p>
      <ProblemMessage error={m.create.error} />
    </section>
  );
}

function Revise({ goal, onDone }: { goal: Goal; onDone: () => void }) {
  const { t } = useI18n();
  const m = useGoalMutations();
  const v = goal.current;
  const [type, setType] = useState<TargetType>(v.target_type);
  const percent = asPercent(goal.display, type);
  const [target, setTarget] = useState("");
  const [reason, setReason] = useState("");
  return (
    <section className="card" aria-labelledby="goal-revise">
      <h2 id="goal-revise">{t("goal.revise")}</h2>
      <div className="form">
        <label>
          {t("goal.targetType")}
          <select
            value={type}
            onChange={(e) => setType(e.target.value as TargetType)}
          >
            {TYPES.map((x) => (
              <option key={x} value={x}>
                {t(`goal.type.${x}` as MessageKey)}
              </option>
            ))}
          </select>
        </label>
        <label>
          {t("goal.target")}
          {percent ? " (%)" : ""}
          <input
            inputMode="decimal"
            value={target}
            onChange={(e) => setTarget(e.target.value)}
          />
        </label>
        <label>
          {t("goal.reason")}
          <input
            value={reason}
            maxLength={500}
            onChange={(e) => setReason(e.target.value)}
          />
        </label>
      </div>
      <div className="form inline">
        <button
          type="button"
          className="primary"
          disabled={!target.trim() || !reason.trim() || m.revise.isPending}
          onClick={() =>
            m.revise.mutate(
              {
                id: goal.id,
                body: {
                  target_type: type,
                  target: toFraction(target, percent),
                  reason,
                  materiality: v.materiality,
                  driver: v.driver,
                },
              },
              { onSuccess: onDone },
            )
          }
        >
          {t("goal.saveVersion")}
        </button>
        <button type="button" onClick={onDone}>
          {t("ck.cancel")}
        </button>
      </div>
      <ProblemMessage error={m.revise.error} />
    </section>
  );
}

const REQUIRED: [string, MessageKey][] = [
  ["goal.required.remaining", "goal.req.remaining"],
  ["goal.required.run_rate", "goal.req.runRate"],
  ["goal.projected_run_rate", "goal.req.projectedRunRate"],
  ["goal.historical_run_rate", "goal.req.historicalRunRate"],
  ["goal.required.numerator", "goal.req.numerator"],
  ["goal.required.denominator", "goal.req.denominator"],
  ["goal.required.inflow", "goal.req.inflow"],
  ["goal.required.reduction", "goal.req.reduction"],
];

function Evaluation({ goal, ev }: { goal: Goal; ev: GoalEvaluation }) {
  const { t, locale } = useI18n();
  const show = (f: GoalFigure | undefined) =>
    !f
      ? "—"
      : f.value === null
        ? `${t("kpi.nm")} (${f.nm_reason})`
        : formatValue(f.value, f.unit, goal.display, locale);
  const projected = figure(ev, "goal.projected");
  const seek = figure(ev, "goal.required.driver_change");
  const breach = figure(ev, "goal.required.breach");
  const contributions = ev.figures.filter((f) => f.key === "goal.contribution");
  const residual = figure(ev, "goal.contribution.residual");
  const total = figure(ev, "goal.contribution.total");
  const comparison = figure(ev, "goal.comparison");
  const trend = ev.figures.filter((f) => f.key === "goal.trend");
  return (
    <section className="card" aria-labelledby="goal-eval">
      <h2 id="goal-eval">
        {t("goal.evaluation")} {ev.as_of} <StatusBadge status={ev.status} />
      </h2>
      {ev.out_of_date ? (
        <p className="error" role="status">
          {t("goal.outOfDate")}
        </p>
      ) : null}
      <p className="muted">{ev.method_note}</p>
      <dl className="facts">
        <dt>{t("goal.target")}</dt>
        <dd>{show(figure(ev, "goal.target"))}</dd>
        <dt>{t("goal.baseline")}</dt>
        <dd>{show(figure(ev, "goal.baseline"))}</dd>
        <dt>{t("goal.actual")}</dt>
        <dd>{show(figure(ev, "goal.actual"))}</dd>
        <dt>{t("goal.projected")}</dt>
        <dd>
          {show(projected)}{" "}
          {projected ? (
            <span className={`badge nature-${projected.nature.toLowerCase()}`}>
              {t(`nature.${projected.nature}` as MessageKey)}
            </span>
          ) : null}
        </dd>
        <dt>{t("goal.gapProjected")}</dt>
        <dd>{show(figure(ev, "goal.gap", "PROJECTED"))}</dd>
        <dt>{t("goal.gapActual")}</dt>
        <dd>{show(figure(ev, "goal.gap", "ACTUAL"))}</dd>
        {figure(ev, "goal.time_elapsed") ? (
          <>
            <dt>{t("goal.elapsed")}</dt>
            <dd>
              {formatValue(
                figure(ev, "goal.time_elapsed")?.value ?? null,
                "ratio",
                "percent",
                locale,
              )}
            </dd>
          </>
        ) : null}
      </dl>
      <h3>{t("goal.required")}</h3>
      <ul>
        {REQUIRED.map(([key, label]) => {
          const f = figure(ev, key);
          return f ? (
            <li key={key}>
              {t(label)}: {show(f)}
            </li>
          ) : null;
        })}
        {seek ? (
          <li>
            {t("goal.req.driver")} {seek.dimensions[0]}:{" "}
            {seek.value === null
              ? seek.nm_reason
              : `${formatAmount(new Decimal(seek.value).times(100).toFixed(2), locale)}%`}
          </li>
        ) : null}
        {breach ? (
          <li>
            {t("goal.req.breach")}: {breach.period_start} (
            {formatAmount(new Decimal(breach.value ?? "0").toFixed(2), locale)})
          </li>
        ) : null}
      </ul>
      <p className="muted">{t("goal.heldNote")}</p>
      {total && comparison ? (
        <div className="table-scroll">
          <table className="grid">
            <caption>
              {t("goal.contribution")}{" "}
              {t(`goal.basis.${comparison.dimensions[0] ?? ""}` as MessageKey)}{" "}
              ({show(comparison)})
            </caption>
            <thead>
              <tr>
                <th scope="col">{t("goal.line")}</th>
                <th scope="col" className="num">
                  {t("goal.effect")}
                </th>
              </tr>
            </thead>
            <tbody>
              {contributions.map((c) => (
                <tr key={c.dimensions[0]}>
                  <td>{c.dimensions[0]}</td>
                  <td className="num">{show(c)}</td>
                </tr>
              ))}
              <tr>
                <td>{t("goal.residual")}</td>
                <td className="num">{show(residual)}</td>
              </tr>
              <tr>
                <th scope="row">{t("goal.total")}</th>
                <td className="num">{show(total)}</td>
              </tr>
            </tbody>
          </table>
        </div>
      ) : null}
      <div className="table-scroll">
        <table className="grid">
          <caption>{t("goal.trend")}</caption>
          <thead>
            <tr>
              <th scope="col">{t("goal.period")}</th>
              <th scope="col">{t("goal.nature")}</th>
              <th scope="col" className="num">
                {t("goal.value")}
              </th>
            </tr>
          </thead>
          <tbody>
            {trend.map((p) => (
              <tr
                key={p.period_start}
                className={p.nature === "ACTUAL" ? "" : "muted"}
              >
                <td>{p.period_end}</td>
                <td>{t(`nature.${p.nature}` as MessageKey)}</td>
                <td className="num">{show(p)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {ev.history.length > 1 ? (
        <div className="table-scroll">
          <table className="grid">
            <caption>{t("goal.history")}</caption>
            <thead>
              <tr>
                <th scope="col">{t("goal.asOf")}</th>
                <th scope="col">{t("goal.statusCol")}</th>
                <th scope="col" className="num">
                  {t("goal.gapProjected")}
                </th>
              </tr>
            </thead>
            <tbody>
              {ev.history.map((h) => (
                <tr key={h.created_at}>
                  <td>{h.as_of}</td>
                  <td>{t(`goal.status.${h.status}` as MessageKey)}</td>
                  <td className="num">
                    {formatValue(h.gap, goal.unit, goal.display, locale)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </section>
  );
}

function Detail({ goal }: { goal: Goal }) {
  const { t, locale } = useI18n();
  const latest = useLatestEvaluation(goal.id);
  const m = useGoalMutations();
  const [asOf, setAsOf] = useState("");
  const [driver, setDriver] = useState("");
  const [revising, setRevising] = useState(false);
  const v = goal.current;
  const ev = latest.data;
  const active = goal.status === "ACTIVE";
  return (
    <>
      <section className="card" aria-labelledby="goal-detail">
        <h2 id="goal-detail">
          {goal.name} <span className="badge">v{v.number}</span>
        </h2>
        <p>
          {goal.metric_name} · {goal.period_start} – {goal.period_end} ·{" "}
          {t(`goal.type.${v.target_type}` as MessageKey)} ·{" "}
          {t(`goal.dir.${v.direction}` as MessageKey)}{" "}
          {formatValue(v.target_value, goal.unit, goal.display, locale)}
        </p>
        <p className="muted">
          {t("goal.baseline")} ({v.baseline_from} – {v.baseline_to}):{" "}
          {v.baseline_value === null
            ? `${t("kpi.nm")} (${v.baseline_nm_reason})`
            : formatValue(
                v.baseline_value,
                goal.unit,
                goal.display,
                locale,
              )}{" "}
          · {t("goal.frozen")} · {goal.metric_ref}
        </p>
        {active ? (
          <div className="form inline">
            <label>
              {t("goal.asOf")}
              <input
                type="date"
                value={asOf}
                onChange={(e) => setAsOf(e.target.value)}
              />
            </label>
            <label>
              {t("goal.driver")}
              <input
                value={driver}
                maxLength={40}
                placeholder={v.driver || "REVENUE"}
                onChange={(e) => setDriver(e.target.value.toUpperCase())}
              />
            </label>
            <button
              type="button"
              className="primary"
              disabled={m.evaluate.isPending}
              onClick={() =>
                m.evaluate.mutate({ id: goal.id, as_of: asOf, driver })
              }
            >
              {t("goal.evaluate")}
            </button>
            <button type="button" onClick={() => setRevising(true)}>
              {t("goal.revise")}
            </button>
            <button type="button" onClick={() => m.retire.mutate(goal.id)}>
              {t("goal.retire")}
            </button>
          </div>
        ) : null}
        <ProblemMessage error={m.evaluate.error ?? m.retire.error} />
        {goal.versions.length > 1 ? (
          <ul className="muted">
            {goal.versions.map((x) => (
              <li key={x.id}>
                v{x.number}:{" "}
                {formatValue(x.target_value, goal.unit, goal.display, locale)}
                {x.reason ? ` · ${x.reason}` : ""}
              </li>
            ))}
          </ul>
        ) : null}
      </section>
      {revising ? (
        <Revise goal={goal} onDone={() => setRevising(false)} />
      ) : null}
      {latest.isPending ? <Loading /> : null}
      {ev ? (
        <Evaluation goal={goal} ev={ev} />
      ) : latest.isSuccess ? (
        <p className="muted">{t("goal.notEvaluated")}</p>
      ) : null}
    </>
  );
}

export function GoalsPage() {
  const { t, locale } = useI18n();
  const [retired, setRetired] = useState(false);
  const goals = useGoals(retired);
  const [adding, setAdding] = useState(false);
  const [selected, setSelected] = useState<string | null>(null);
  const goal = goals.data?.find((g) => g.id === selected) ?? null;
  return (
    <Page
      title={t("goal.title")}
      actions={
        <button type="button" onClick={() => setAdding(true)}>
          {t("goal.new")}
        </button>
      }
    >
      <p className="muted">{t("goal.intro")}</p>
      {adding ? <NewGoal onDone={() => setAdding(false)} /> : null}
      <label className="checkbox">
        <input
          type="checkbox"
          checked={retired}
          onChange={(e) => setRetired(e.target.checked)}
        />{" "}
        {t("goal.showRetired")}
      </label>
      {goals.isPending ? <Loading /> : null}
      <ProblemMessage error={goals.error} />
      {goals.data ? (
        <div className="table-scroll">
          <table className="grid">
            <caption>{t("goal.list")}</caption>
            <thead>
              <tr>
                <th scope="col">{t("goal.name")}</th>
                <th scope="col">{t("goal.metric")}</th>
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
              {goals.data.map((g) => (
                <tr key={g.id}>
                  <td>
                    <button
                      type="button"
                      className="link"
                      aria-pressed={g.id === selected}
                      onClick={() => setSelected(g.id)}
                    >
                      {g.name}
                    </button>
                  </td>
                  <td>{g.metric_name}</td>
                  <td className="num">
                    {formatValue(
                      g.current.target_value,
                      g.unit,
                      g.display,
                      locale,
                    )}
                  </td>
                  <td className="num">
                    {g.latest
                      ? formatValue(
                          g.latest.projected,
                          g.unit,
                          g.display,
                          locale,
                        )
                      : ""}
                  </td>
                  <td>
                    {g.status === "RETIRED" ? (
                      t("goal.retired")
                    ) : g.latest ? (
                      <StatusBadge status={g.latest.status} />
                    ) : (
                      t("goal.notEvaluatedShort")
                    )}
                  </td>
                </tr>
              ))}
              {goals.data.length ? null : (
                <tr>
                  <td colSpan={5}>{t("goal.none")}</td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      ) : null}
      {goal ? <Detail key={goal.id} goal={goal} /> : null}
    </Page>
  );
}
