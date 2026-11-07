import { useState } from "react";
import {
  type CustomKpi,
  type CustomKpiIn,
  type KpiDisplay,
  type OperationalMetric,
  useCustomKpiMutations,
  useCustomKpis,
  useMetricMutations,
  useOperationalMetrics,
} from "../api/kpi";
import { Loading, Page, ProblemMessage } from "../components/common";
import { useI18n } from "../i18n/I18n";
import type { MessageKey } from "../i18n/messages";

const DISPLAYS: KpiDisplay[] = [
  "percent",
  "ratio",
  "times",
  "days",
  "months",
  "EUR",
];
const EMPTY: CustomKpiIn = {
  key: "",
  name: "",
  formula: "",
  display: "ratio",
  direction: "HIGHER_BETTER",
  convention: "",
};

function KpiForm({
  editing,
  onDone,
}: {
  editing: CustomKpi | null;
  onDone: () => void;
}) {
  const { t } = useI18n();
  const m = useCustomKpiMutations();
  const [form, setForm] = useState<CustomKpiIn>(
    editing
      ? {
          key: editing.key,
          name: editing.name,
          formula: editing.formula,
          display: editing.display,
          direction: editing.direction,
          convention: editing.convention,
        }
      : EMPTY,
  );
  const [scope, setScope] = useState<"PERSONAL" | "WORKSPACE">("PERSONAL");
  const set = (patch: Partial<CustomKpiIn>) => {
    setForm((f) => ({ ...f, ...patch }));
    m.check.reset();
  };
  const checked = m.check.data;
  const save = () => {
    const done = { onSuccess: onDone };
    if (editing) m.revise.mutate({ id: editing.id, body: form }, done);
    else m.create.mutate({ ...form, scope }, done);
  };
  return (
    <section className="card" aria-labelledby="ck-form">
      <h2 id="ck-form">
        {editing ? `${t("ck.revise")} ${editing.key}` : t("ck.new")}
      </h2>
      <p className="muted">{t("ck.formulaHelp")}</p>
      <div className="form">
        <label>
          {t("ck.key")}
          <input
            value={form.key}
            onChange={(e) => set({ key: e.target.value.toUpperCase() })}
            disabled={!!editing}
            maxLength={40}
            required
          />
        </label>
        <label>
          {t("ck.name")}
          <input
            value={form.name}
            onChange={(e) => set({ name: e.target.value })}
            maxLength={120}
          />
        </label>
        <label>
          {t("ck.formula")}
          <textarea
            value={form.formula}
            onChange={(e) => set({ formula: e.target.value })}
            rows={3}
            maxLength={2000}
            spellCheck={false}
          />
        </label>
        <label>
          {t("ck.display")}
          <select
            value={form.display}
            onChange={(e) => set({ display: e.target.value as KpiDisplay })}
          >
            {DISPLAYS.map((d) => (
              <option key={d} value={d}>
                {t(`ck.display.${d}` as MessageKey)}
              </option>
            ))}
          </select>
        </label>
        <label>
          {t("ck.direction")}
          <select
            value={form.direction}
            onChange={(e) =>
              set({ direction: e.target.value as CustomKpiIn["direction"] })
            }
          >
            <option value="HIGHER_BETTER">{t("kpi.higher")}</option>
            <option value="LOWER_BETTER">{t("kpi.lower")}</option>
          </select>
        </label>
        <label>
          {t("ck.convention")}
          <input
            value={form.convention}
            onChange={(e) => set({ convention: e.target.value })}
            maxLength={500}
          />
        </label>
        {editing ? null : (
          <fieldset>
            <legend>{t("ck.scope")}</legend>
            <label className="checkbox">
              <input
                type="radio"
                name="scope"
                checked={scope === "PERSONAL"}
                onChange={() => setScope("PERSONAL")}
              />{" "}
              {t("ck.scope.PERSONAL")}
            </label>
            <label className="checkbox">
              <input
                type="radio"
                name="scope"
                checked={scope === "WORKSPACE"}
                onChange={() => setScope("WORKSPACE")}
              />{" "}
              {t("ck.scope.WORKSPACE")}
            </label>
          </fieldset>
        )}
      </div>
      <div className="form inline">
        <button
          type="button"
          disabled={!form.formula.trim() || m.check.isPending}
          onClick={() =>
            m.check.mutate({ formula: form.formula, display: form.display })
          }
        >
          {t("ck.check")}
        </button>
        <button
          type="button"
          className="primary"
          disabled={!checked?.ok || m.create.isPending || m.revise.isPending}
          onClick={save}
        >
          {t("ck.save")}
        </button>
        <button type="button" onClick={onDone}>
          {t("ck.cancel")}
        </button>
      </div>
      {checked ? (
        <div role="status">
          {checked.ok ? (
            <p>
              {t("ck.ok")} {checked.dry_run_month?.slice(0, 7)}:{" "}
              {checked.dry_run_value ??
                `${t("kpi.nm")} (${checked.dry_run_reason})`}
              {checked.non_ledger ? ` · ${t("ck.nonLedger")}` : ""}
            </p>
          ) : (
            <ul className="error">
              {checked.problems.map((p) => (
                <li key={p}>{p}</li>
              ))}
            </ul>
          )}
        </div>
      ) : null}
      <ProblemMessage
        error={m.check.error ?? m.create.error ?? m.revise.error}
      />
    </section>
  );
}

function Decision({ kpi }: { kpi: CustomKpi }) {
  const { t } = useI18n();
  const { decide } = useCustomKpiMutations();
  const [comment, setComment] = useState("");
  return (
    <>
      <div className="inline-form">
        <label>
          <span className="visually-hidden">
            {t("ck.comment")} {kpi.key}
          </span>
          <input
            placeholder={t("ck.comment")}
            value={comment}
            onChange={(e) => setComment(e.target.value)}
            maxLength={500}
          />
        </label>
        <button
          type="button"
          onClick={() => decide.mutate({ id: kpi.id, approve: true, comment })}
          disabled={decide.isPending}
        >
          {t("ck.approve")}
          <span className="visually-hidden"> {kpi.key}</span>
        </button>
        <button
          type="button"
          onClick={() => decide.mutate({ id: kpi.id, approve: false, comment })}
          disabled={decide.isPending || !comment.trim()}
        >
          {t("ck.reject")}
          <span className="visually-hidden"> {kpi.key}</span>
        </button>
      </div>
      <ProblemMessage error={decide.error} />
    </>
  );
}

const lastMonths = (n: number): string[] => {
  const now = new Date();
  return Array.from({ length: n }, (_, i) => {
    const d = new Date(
      Date.UTC(now.getUTCFullYear(), now.getUTCMonth() - n + i, 1),
    );
    return d.toISOString().slice(0, 10);
  });
};

function MetricRow({
  metric,
  months,
}: {
  metric: OperationalMetric;
  months: string[];
}) {
  const { t } = useI18n();
  const { setValue } = useMetricMutations();
  const current = new Map(metric.values.map((v) => [v.month, v]));
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  return (
    <tr>
      <th scope="row">
        {metric.name} <span className="muted">({metric.key})</span>
        <br />
        <span className="muted">
          {t(`ck.agg.${metric.aggregation}`)} · {t("ck.nonLedger")}
        </span>
      </th>
      {months.map((month) => {
        const saved = current.get(month);
        const draft = drafts[month];
        const label = `${metric.name} ${month.slice(0, 7)}`;
        return (
          <td key={month}>
            <input
              className="num"
              inputMode="decimal"
              aria-label={label}
              value={draft ?? saved?.value ?? ""}
              size={7}
              onChange={(e) =>
                setDrafts({ ...drafts, [month]: e.target.value })
              }
              onBlur={() => {
                if (
                  draft === undefined ||
                  draft === (saved?.value ?? "") ||
                  !draft.trim()
                )
                  return;
                setValue.mutate(
                  { metricId: metric.id, month, value: draft.trim(), note: "" },
                  {
                    onSuccess: () =>
                      setDrafts((d) =>
                        Object.fromEntries(
                          Object.entries(d).filter(([m]) => m !== month),
                        ),
                      ),
                  },
                );
              }}
            />
            {saved && saved.version > 1 ? (
              <span className="muted" title={saved.entered_by}>
                {" "}
                v{saved.version}
              </span>
            ) : null}
          </td>
        );
      })}
      <td>
        <ProblemMessage error={setValue.error} />
      </td>
    </tr>
  );
}

function Metrics() {
  const { t } = useI18n();
  const metrics = useOperationalMetrics();
  const { create } = useMetricMutations();
  const [key, setKey] = useState("");
  const [name, setName] = useState("");
  const [unit, setUnit] = useState<"count" | "EUR">("count");
  const [aggregation, setAggregation] = useState<"LAST" | "SUM">("LAST");
  const months = lastMonths(6);
  return (
    <section aria-labelledby="ck-metrics">
      <h2 id="ck-metrics">{t("ck.metrics")}</h2>
      <p className="notice" role="note">
        {t("ck.metricsHelp")}
      </p>
      <form
        className="form inline"
        onSubmit={(e) => {
          e.preventDefault();
          create.mutate(
            { key, name, unit, aggregation },
            {
              onSuccess: () => {
                setKey("");
                setName("");
              },
            },
          );
        }}
      >
        <label>
          {t("ck.key")}
          <input
            value={key}
            onChange={(e) => setKey(e.target.value.toUpperCase())}
            maxLength={40}
            required
          />
        </label>
        <label>
          {t("ck.name")}
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            maxLength={120}
            required
          />
        </label>
        <label>
          {t("ck.unit")}
          <select
            value={unit}
            onChange={(e) => setUnit(e.target.value as "count" | "EUR")}
          >
            <option value="count">{t("ck.unit.count")}</option>
            <option value="EUR">EUR</option>
          </select>
        </label>
        <label>
          {t("ck.aggregation")}
          <select
            value={aggregation}
            onChange={(e) => setAggregation(e.target.value as "LAST" | "SUM")}
          >
            <option value="LAST">{t("ck.agg.LAST")}</option>
            <option value="SUM">{t("ck.agg.SUM")}</option>
          </select>
        </label>
        <button type="submit" disabled={create.isPending}>
          {t("ck.addMetric")}
        </button>
      </form>
      <ProblemMessage error={create.error ?? metrics.error} />
      {metrics.data?.length ? (
        <div className="table-scroll">
          <table className="grid">
            <caption>{t("ck.metricValues")}</caption>
            <thead>
              <tr>
                <th scope="col">{t("ck.metric")}</th>
                {months.map((m) => (
                  <th scope="col" key={m} className="num">
                    {m.slice(0, 7)}
                  </th>
                ))}
                <th scope="col">
                  <span className="visually-hidden">{t("ck.problems")}</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {metrics.data.map((metric) => (
                <MetricRow key={metric.id} metric={metric} months={months} />
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </section>
  );
}

/** Custom KPIs and operational metrics (M4-5). */
export function CustomKpisPage() {
  const { t } = useI18n();
  const kpis = useCustomKpis();
  const { retire } = useCustomKpiMutations();
  const [editing, setEditing] = useState<CustomKpi | "new" | null>(null);
  return (
    <Page title={t("ck.title")}>
      <p className="muted">{t("ck.help")}</p>
      {editing ? (
        <KpiForm
          key={editing === "new" ? "new" : editing.id}
          editing={editing === "new" ? null : editing}
          onDone={() => setEditing(null)}
        />
      ) : (
        <p>
          <button
            type="button"
            className="primary"
            onClick={() => setEditing("new")}
          >
            {t("ck.new")}
          </button>
        </p>
      )}
      {kpis.isPending ? <Loading /> : null}
      <ProblemMessage error={kpis.error ?? retire.error} />
      {kpis.data?.length ? (
        <div className="table-scroll">
          <table className="grid">
            <caption>{t("ck.list")}</caption>
            <thead>
              <tr>
                <th scope="col">{t("ck.key")}</th>
                <th scope="col">{t("ck.name")}</th>
                <th scope="col">{t("ck.scope")}</th>
                <th scope="col">{t("ck.status")}</th>
                <th scope="col">{t("ck.formula")}</th>
                <th scope="col">{t("ck.actions")}</th>
              </tr>
            </thead>
            <tbody>
              {kpis.data.map((k) => (
                <tr key={k.id}>
                  <th scope="row">
                    {k.key} v{k.version}
                  </th>
                  <td>
                    {k.name}
                    <br />
                    <span className="muted">{k.owner_name}</span>
                  </td>
                  <td>{t(`ck.scope.${k.scope}`)}</td>
                  <td>
                    {t(`ck.status.${k.status}`)}
                    {k.decided_by_name ? (
                      <span className="muted">
                        {" "}
                        · {k.decided_by_name}
                        {k.decision_comment ? `: “${k.decision_comment}”` : ""}
                      </span>
                    ) : null}
                  </td>
                  <td>
                    <code>{k.formula}</code>
                  </td>
                  <td>
                    {k.status === "SUBMITTED" ? <Decision kpi={k} /> : null}
                    {k.status === "ACTIVE" || k.status === "APPROVED" ? (
                      <>
                        <button type="button" onClick={() => setEditing(k)}>
                          {t("ck.revise")}
                          <span className="visually-hidden"> {k.key}</span>
                        </button>{" "}
                        <button
                          type="button"
                          onClick={() => retire.mutate(k.id)}
                          disabled={retire.isPending}
                        >
                          {t("ck.retire")}
                          <span className="visually-hidden"> {k.key}</span>
                        </button>
                      </>
                    ) : null}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
      <Metrics />
    </Page>
  );
}
