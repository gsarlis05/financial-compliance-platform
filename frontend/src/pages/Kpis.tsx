import Decimal from "decimal.js";
import { useMemo, useState } from "react";
import { useExplain } from "../api/forecast";
import { useAccounts, useGeneralLedger } from "../api/hooks";
import {
  type KpiSet,
  type KpiValue,
  useKpiDefinitions,
  useLatestKpis,
  usePersonalKpis,
  useRunKpis,
} from "../api/kpi";
import { Loading, Page, ProblemMessage } from "../components/common";
import { useI18n } from "../i18n/I18n";
import type { MessageKey } from "../i18n/messages";
import { formatAmount } from "../money";

type Preset = "MONTH" | "QUARTER" | "YTD" | "LTM";
const PRESETS: Preset[] = ["MONTH", "QUARTER", "YTD", "LTM"];

function lastDay(month: string): string {
  const [y, m] = month.split("-").map(Number) as [number, number];
  const d = new Date(Date.UTC(y, m, 0)).getUTCDate();
  return `${month}-${String(d).padStart(2, "0")}`;
}

function shift(month: string, by: number): string {
  const [y, m] = month.split("-").map(Number) as [number, number];
  const d = new Date(Date.UTC(y, m - 1 + by, 1));
  return `${String(d.getUTCFullYear())}-${String(d.getUTCMonth() + 1).padStart(2, "0")}`;
}

/** The whole-month period a preset covers, ending in ``month`` (YYYY-MM). Year to date assumes a
 * January fiscal year start. */
export function period(
  preset: Preset,
  month: string,
): { date_from: string; date_to: string } {
  const m = Number(month.slice(5, 7));
  const first =
    preset === "MONTH"
      ? month
      : preset === "QUARTER"
        ? shift(month, -((m - 1) % 3))
        : preset === "YTD"
          ? `${month.slice(0, 4)}-01`
          : shift(month, -11);
  return { date_from: `${first}-01`, date_to: lastDay(month) };
}

export function formatKpi(v: KpiValue, locale: string): string {
  if (v.value === null) return "";
  const n = new Decimal(v.value);
  // Ratios are stored unrounded and rounded only here, for display (doc 10 §2.4).
  return v.display === "percent"
    ? `${formatAmount(n.times(100).toFixed(2), locale)}%`
    : formatAmount(n.toFixed(2), locale);
}

function Entries({ accountId, kpis }: { accountId: string; kpis: KpiSet }) {
  const { t, locale } = useI18n();
  const ledger = useGeneralLedger(accountId, kpis.date_from, kpis.date_to);
  if (ledger.isPending) return <Loading />;
  if (!ledger.data) return <ProblemMessage error={ledger.error} />;
  return (
    <ul className="entries">
      {ledger.data.lines.map((l, i) => (
        // Lines of one entry can share every field; the list never reorders, so the position is a
        // stable key.
        <li key={`${String(i)}-${l.entry_id}`}>
          {l.accounting_date} · {l.entry_ref} · {l.description} ·{" "}
          {formatAmount(l.debit, locale)} / {formatAmount(l.credit, locale)}
        </li>
      ))}
      {ledger.data.lines.length ? null : <li>{t("kpi.noEntries")}</li>}
    </ul>
  );
}

const PART: Record<string, MessageKey> = {
  flow: "kpi.part.flow",
  prior_flow: "kpi.part.prior_flow",
  opening: "kpi.part.opening",
  closing: "kpi.part.closing",
  three_months: "kpi.part.three_months",
};

function Explain({ kpis, value }: { kpis: KpiSet; value: KpiValue }) {
  const { t, locale } = useI18n();
  const explain = useExplain(kpis.run_id, value.result_id);
  const definitions = useKpiDefinitions();
  const accounts = useAccounts();
  const [open, setOpen] = useState<string | null>(null);
  const names = new Map(
    (accounts.data ?? []).map((a) => [a.id, `${a.code} · ${a.name}`]),
  );
  const definition = definitions.data?.find(
    (d) => d.id === value.definition_id,
  );
  const parts = (explain.data?.lineage ?? []).filter((l) =>
    l.input_ref.startsWith("account:"),
  );
  return (
    <section className="card" aria-labelledby="kpi-explain">
      <h2 id="kpi-explain">
        {t("kpi.how")} {value.name}
      </h2>
      <p>{value.convention}</p>
      {definition ? (
        <>
          <p>
            <code>{definition.formula}</code>
          </p>
          <p className="muted">
            {definition.nm_note} {t("kpi.example")}: {definition.example}
          </p>
        </>
      ) : null}
      {explain.isPending ? <Loading /> : null}
      <div className="table-scroll">
        <table className="grid">
          <caption>{t("kpi.components")}</caption>
          <thead>
            <tr>
              <th scope="col">{t("kpi.account")}</th>
              <th scope="col">{t("kpi.part")}</th>
              <th scope="col" className="num">
                {t("kpi.amount")}
              </th>
              <th scope="col">
                <span className="visually-hidden">{t("kpi.entries")}</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {parts.map((l) => {
              const [, accountId = "", part = ""] = l.input_ref.split(":");
              const label = names.get(accountId) ?? accountId;
              return (
                <tr key={l.input_ref}>
                  <th scope="row">
                    {label}
                    {open === l.input_ref ? (
                      <Entries accountId={accountId} kpis={kpis} />
                    ) : null}
                  </th>
                  <td>{t(PART[part] ?? "kpi.part.flow")}</td>
                  <td className="num">
                    {l.amount ? formatAmount(l.amount, locale) : "—"}
                  </td>
                  <td>
                    <button
                      type="button"
                      aria-expanded={open === l.input_ref}
                      onClick={() =>
                        setOpen(open === l.input_ref ? null : l.input_ref)
                      }
                    >
                      {t("kpi.entries")}
                      <span className="visually-hidden"> {label}</span>
                    </button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function PersonalKpis({ runId }: { runId: string }) {
  const { t, locale } = useI18n();
  const personal = usePersonalKpis(runId);
  if (!personal.data?.length) return null;
  return (
    <section aria-labelledby="kpi-personal">
      <h2 id="kpi-personal">{t("kpi.personal")}</h2>
      <p className="muted">{t("kpi.personalHelp")}</p>
      <ul className="kpi-cards">
        {personal.data.map((v) => (
          <li key={v.key} className="kpi-card">
            <h3>{v.name}</h3>
            <p className="kpi-value">
              {v.value === null
                ? t("kpi.nm")
                : formatKpi(
                    {
                      ...v,
                      result_id: "",
                      category: "",
                      convention: "",
                      name_el: "",
                    },
                    locale,
                  )}
            </p>
            {v.value === null ? <p className="muted">{v.nm_reason}</p> : null}
            <p className="muted">
              {t("nature.ACTUAL")} · {t("ck.scope.PERSONAL")}
            </p>
            {v.non_ledger ? <p className="non-ledger">{t("ck.nonLedger")}</p> : null}
          </li>
        ))}
      </ul>
    </section>
  );
}

/** KPIs (M4-4): the core library for a whole-month period, each value explained. */
export function KpisPage() {
  const { t, locale } = useI18n();
  const today = new Date().toISOString().slice(0, 7);
  const [month, setMonth] = useState(shift(today, -1));
  const [preset, setPreset] = useState<Preset>("YTD");
  const range = useMemo(() => period(preset, month), [preset, month]);
  const latest = useLatestKpis(range.date_from, range.date_to);
  const runKpis = useRunKpis();
  const [chosen, setChosen] = useState<string | null>(null);
  const kpis = latest.data;
  const categories = kpis
    ? [...new Set(kpis.values.map((v) => v.category))]
    : [];
  const selected = kpis?.values.find((v) => v.key === chosen) ?? null;
  return (
    <Page title={t("kpi.title")}>
      <p className="muted">{t("kpi.help")}</p>
      <div className="form inline">
        <label>
          {t("kpi.month")}
          <input
            type="month"
            value={month}
            onChange={(e) => setMonth(e.target.value)}
          />
        </label>
        <label>
          {t("kpi.preset")}
          <select
            value={preset}
            onChange={(e) => setPreset(e.target.value as Preset)}
          >
            {PRESETS.map((p) => (
              <option key={p} value={p}>
                {t(`kpi.preset.${p}`)}
              </option>
            ))}
          </select>
        </label>
        <button
          type="button"
          className="primary"
          disabled={runKpis.isPending || !month}
          onClick={() => runKpis.mutate(range)}
        >
          {t("kpi.run")}
        </button>
      </div>
      <p className="muted">
        {range.date_from} – {range.date_to}
      </p>
      <ProblemMessage error={latest.error ?? runKpis.error} />
      {latest.isPending ? <Loading /> : null}
      {kpis === null ? <p>{t("kpi.none")}</p> : null}
      {kpis ? (
        <>
          <p className="muted">
            {t("kpi.basis")} {kpis.actuals_watermark} · {kpis.library} ·{" "}
            {kpis.created_at.slice(0, 16).replace("T", " ")}
          </p>
          {kpis.stale ? (
            <p className="notice warn" role="status">
              {t("kpi.stale")}
            </p>
          ) : null}
          {kpis.unmapped_accounts ? (
            <p className="notice warn" role="status">
              {t("kpi.unmapped")}: {kpis.unmapped_accounts}
            </p>
          ) : null}
          {categories.map((category) => (
            <section key={category} aria-labelledby={`kpi-${category}`}>
              <h2 id={`kpi-${category}`}>
                {t(`kpi.category.${category}` as MessageKey)}
              </h2>
              <ul className="kpi-cards">
                {kpis.values
                  .filter((v) => v.category === category)
                  .map((v) => (
                    <li key={v.key} className="kpi-card">
                      <h3>
                        {locale === "el" && v.name_el ? v.name_el : v.name}
                      </h3>
                      <p className="kpi-value">
                        {v.value === null ? t("kpi.nm") : formatKpi(v, locale)}
                        {v.value !== null &&
                        (v.display === "days" || v.display === "months")
                          ? ` ${t(`kpi.unit.${v.display}`)}`
                          : ""}
                        {v.value !== null && v.display === "times"
                          ? ` ${t("kpi.unit.times")}`
                          : ""}
                      </p>
                      {v.value === null ? (
                        <p className="muted">{v.nm_reason}</p>
                      ) : null}
                      <p className="muted">
                        {t("nature.ACTUAL")} ·{" "}
                        {v.direction === "HIGHER_BETTER"
                          ? t("kpi.higher")
                          : t("kpi.lower")}
                      </p>
                      {v.non_ledger ? (
                        <p className="non-ledger">{t("ck.nonLedger")}</p>
                      ) : null}
                      <button
                        type="button"
                        aria-pressed={chosen === v.key}
                        onClick={() => setChosen(v.key)}
                      >
                        {t("kpi.explain")}
                        <span className="visually-hidden"> {v.name}</span>
                      </button>
                    </li>
                  ))}
              </ul>
            </section>
          ))}
          <PersonalKpis runId={kpis.run_id} />
          {selected ? (
            <Explain key={selected.key} kpis={kpis} value={selected} />
          ) : null}
        </>
      ) : null}
    </Page>
  );
}
