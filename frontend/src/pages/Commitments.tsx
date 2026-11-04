import { type SyntheticEvent, useState } from "react";
import {
  useCommitmentFlows,
  useCommitmentMutations,
  useDebtSchedule,
  useDebts,
  useHolidays,
  useObligations,
} from "../api/hooks";
import type {
  Adjustment,
  CommitmentNature,
  Debt,
  DebtInput,
  DebtKind,
  Frequency,
  Obligation,
  ObligationCategory,
  ObligationInput,
  Repayment,
} from "../api/types";
import {
  FieldError,
  Loading,
  Page,
  ProblemMessage,
} from "../components/common";
import { useI18n } from "../i18n/I18n";
import type { MessageKey } from "../i18n/messages";
import { formatAmount } from "../money";

const CATEGORIES: ObligationCategory[] = [
  "RENT",
  "PAYROLL",
  "SOCIAL_INSURANCE",
  "SUBSCRIPTION",
  "LEASE",
  "INSURANCE",
  "UTILITIES",
  "INCOME",
  "OTHER",
];
const FREQUENCIES: Frequency[] = ["WEEKLY", "MONTHLY", "QUARTERLY", "YEARLY"];
const ADJUSTMENTS: Adjustment[] = [
  "NONE",
  "FOLLOWING",
  "MODIFIED_FOLLOWING",
  "PRECEDING",
];
const KINDS: DebtKind[] = [
  "TERM_LOAN",
  "LEASE",
  "DIRECTOR_LOAN",
  "OVERDRAFT",
  "REVOLVER",
];
const REPAYMENTS: Repayment[] = [
  "ANNUITY",
  "LINEAR",
  "BULLET",
  "IO_THEN_ANNUITY",
];
const FACILITIES: DebtKind[] = ["OVERDRAFT", "REVOLVER"];

const today = () => new Date().toISOString().slice(0, 10);
const addDays = (iso: string, days: number) => {
  const d = new Date(`${iso}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + days);
  return d.toISOString().slice(0, 10);
};

const EMPTY_OBLIGATION: ObligationInput = {
  name: "",
  category: "RENT",
  direction: "OUTFLOW",
  amount: "",
  frequency: "MONTHLY",
  interval: 1,
  day_of_month: 1,
  start_date: today(),
  end_date: null,
  adjust: "FOLLOWING",
  contractual: true,
  counterparty_id: null,
  note: "",
};
const EMPTY_DEBT: DebtInput = {
  name: "",
  kind: "TERM_LOAN",
  principal: "",
  facility_limit: null,
  start_date: today(),
  maturity_date: "",
  payment_frequency_months: 1,
  rate_type: "FIXED",
  fixed_rate: null,
  reference_rate_key: "",
  margin: null,
  assumed_reference_rate: null,
  day_count: "ACT_365",
  repayment_type: "ANNUITY",
  interest_only_periods: 0,
  adjust: "MODIFIED_FOLLOWING",
  lender_id: null,
  note: "",
};

/** "0.0425" (a fraction) as "4.25" (a percentage), by moving the decimal point: no floats. */
export function toPercent(fraction: string | null): string {
  const match = /^(\d+)\.?(\d*)$/.exec(fraction ?? "");
  if (!match) {
    return "";
  }
  const whole = match[1] ?? "";
  const part = match[2] ?? "";
  const shifted = `${whole}${part.padEnd(2, "0").slice(0, 2)}`.replace(
    /^0+(?=\d)/,
    "",
  );
  const rest = part.slice(2).replace(/0+$/, "");
  return rest ? `${shifted}.${rest}` : shifted;
}

/** "4.25" (a percentage) as "0.0425" (a fraction); other text is sent as typed (the server
 * says what is wrong with it); empty is null. */
export function fromPercent(percent: string): string | null {
  const text = percent.trim();
  if (!text) {
    return null;
  }
  const match = /^(\d+)(?:\.(\d*))?$/.exec(text);
  if (!match) {
    return text;
  }
  const whole = (match[1] ?? "").padStart(3, "0");
  const digits = `${whole}${match[2] ?? ""}`;
  const cut = whole.length - 2;
  return `${digits.slice(0, cut).replace(/^0+(?=\d)/, "")}.${digits.slice(cut)}`;
}

type Percents = { fixed: string; margin: string; assumed: string };
const NO_PERCENTS: Percents = { fixed: "", margin: "", assumed: "" };

function NatureBadge({ nature }: { nature: CommitmentNature }) {
  const { t } = useI18n();
  return (
    <span className={`badge badge-${nature.toLowerCase()}`}>
      {t(`nature.${nature}`)}
    </span>
  );
}

function ObligationsSection() {
  const { t, locale } = useI18n();
  const list = useObligations();
  const { saveObligation, retire } = useCommitmentMutations();
  const [form, setForm] = useState<ObligationInput>(EMPTY_OBLIGATION);
  const [editing, setEditing] = useState<string | null>(null);
  const set = (changes: Partial<ObligationInput>) =>
    setForm({ ...form, ...changes });

  function submit(event: SyntheticEvent) {
    event.preventDefault();
    saveObligation.mutate(
      { seriesId: editing, body: form },
      {
        onSuccess: () => {
          setForm(EMPTY_OBLIGATION);
          setEditing(null);
        },
      },
    );
  }

  function edit(o: Obligation) {
    setForm({
      name: o.name,
      category: o.category,
      direction: o.direction,
      amount: o.amount,
      frequency: o.frequency,
      interval: o.interval,
      day_of_month: o.day_of_month,
      start_date: o.start_date,
      end_date: o.end_date,
      adjust: o.adjust,
      contractual: o.contractual,
      counterparty_id: o.counterparty_id,
      note: o.note,
    });
    setEditing(o.series_id);
  }

  return (
    <section aria-labelledby="obl-heading">
      <h2 id="obl-heading">{t("cm.obligations")}</h2>
      <p className="muted">{t("cm.obligationsHelp")}</p>
      {list.isPending ? <Loading /> : null}
      <ProblemMessage error={list.error ?? retire.error} />
      {list.data?.length === 0 ? <p>{t("cm.noObligations")}</p> : null}
      {list.data?.length ? (
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th scope="col">{t("cm.name")}</th>
                <th scope="col">{t("cm.category")}</th>
                <th scope="col">{t("cm.schedule")}</th>
                <th scope="col" className="amount">
                  {t("cm.amount")}
                </th>
                <th scope="col">{t("cm.nature")}</th>
                <th scope="col">{t("cm.version")}</th>
                <th scope="col">
                  <span className="visually-hidden">{t("cm.actions")}</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {list.data.map((o) => (
                <tr key={o.id}>
                  <td>{o.name}</td>
                  <td>{t(`cm.cat.${o.category}` as MessageKey)}</td>
                  <td>
                    {t(`cm.freq.${o.frequency}` as MessageKey)}
                    {o.day_of_month
                      ? ` · ${t("cm.day")} ${o.day_of_month}`
                      : ""}
                    {` · ${t("cm.from")} ${o.start_date}`}
                    {o.end_date ? ` ${t("cm.to")} ${o.end_date}` : ""}
                  </td>
                  <td className="amount">
                    {formatAmount(
                      o.direction === "OUTFLOW" ? `-${o.amount}` : o.amount,
                      locale,
                    )}
                  </td>
                  <td>
                    <NatureBadge nature={o.nature} />
                  </td>
                  <td>{o.version}</td>
                  <td>
                    <div className="row-actions table-actions">
                      <button type="button" onClick={() => edit(o)}>
                        {t("cm.change")}
                      </button>
                      <button
                        type="button"
                        onClick={() =>
                          retire.mutate({
                            kind: "obligations",
                            seriesId: o.series_id,
                          })
                        }
                      >
                        {t("cm.retire")}
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
      <form className="panel form inline" onSubmit={submit}>
        <h3>{editing ? t("cm.changeObligation") : t("cm.addObligation")}</h3>
        <label>
          {t("cm.name")}
          <input
            value={form.name}
            onChange={(e) => set({ name: e.target.value })}
            required
            maxLength={120}
          />
        </label>
        <label>
          {t("cm.category")}
          <select
            value={form.category}
            onChange={(e) =>
              set({ category: e.target.value as ObligationCategory })
            }
          >
            {CATEGORIES.map((c) => (
              <option key={c} value={c}>
                {t(`cm.cat.${c}`)}
              </option>
            ))}
          </select>
        </label>
        <label>
          {t("cm.direction")}
          <select
            value={form.direction}
            onChange={(e) =>
              set({ direction: e.target.value as "OUTFLOW" | "INFLOW" })
            }
          >
            <option value="OUTFLOW">{t("cm.dir.OUTFLOW")}</option>
            <option value="INFLOW">{t("cm.dir.INFLOW")}</option>
          </select>
        </label>
        <label>
          {t("cm.amount")}
          <input
            inputMode="decimal"
            value={form.amount}
            onChange={(e) => set({ amount: e.target.value })}
            required
            aria-describedby="obl-amount-error"
          />
          <FieldError
            error={saveObligation.error}
            field="amount"
            id="obl-amount-error"
          />
        </label>
        <label>
          {t("cm.frequency")}
          <select
            value={form.frequency}
            onChange={(e) => {
              const frequency = e.target.value as Frequency;
              set({
                frequency,
                day_of_month:
                  frequency === "WEEKLY" ? null : (form.day_of_month ?? 1),
              });
            }}
          >
            {FREQUENCIES.map((f) => (
              <option key={f} value={f}>
                {t(`cm.freq.${f}`)}
              </option>
            ))}
          </select>
        </label>
        <label>
          {t("cm.every")}
          <input
            type="number"
            min={1}
            max={52}
            value={form.interval}
            onChange={(e) => set({ interval: Number(e.target.value) })}
          />
        </label>
        {form.frequency !== "WEEKLY" ? (
          <label>
            {t("cm.dayOfMonth")}
            <input
              type="number"
              min={1}
              max={31}
              value={form.day_of_month ?? ""}
              onChange={(e) =>
                set({
                  day_of_month: e.target.value ? Number(e.target.value) : null,
                })
              }
            />
          </label>
        ) : null}
        <label>
          {t("cm.start")}
          <input
            type="date"
            value={form.start_date}
            onChange={(e) => set({ start_date: e.target.value })}
            required
          />
        </label>
        <label>
          {t("cm.end")}
          <input
            type="date"
            value={form.end_date ?? ""}
            onChange={(e) => set({ end_date: e.target.value || null })}
          />
        </label>
        <label>
          {t("cm.adjust")}
          <select
            value={form.adjust}
            onChange={(e) => set({ adjust: e.target.value as Adjustment })}
          >
            {ADJUSTMENTS.map((a) => (
              <option key={a} value={a}>
                {t(`cm.adj.${a}`)}
              </option>
            ))}
          </select>
        </label>
        <label className="checkbox">
          <input
            type="checkbox"
            checked={form.contractual}
            onChange={(e) => set({ contractual: e.target.checked })}
          />
          {t("cm.contractual")}
        </label>
        <FieldError error={saveObligation.error} field="schedule" />
        <ProblemMessage error={saveObligation.error} />
        <div className="actions">
          <button
            type="submit"
            className="primary"
            disabled={saveObligation.isPending}
          >
            {editing ? t("cm.saveVersion") : t("cm.addObligation")}
          </button>
          {editing ? (
            <button
              type="button"
              onClick={() => {
                setEditing(null);
                setForm(EMPTY_OBLIGATION);
              }}
            >
              {t("cm.cancel")}
            </button>
          ) : null}
        </div>
      </form>
    </section>
  );
}

function ScheduleTable({ seriesId }: { seriesId: string }) {
  const { t, locale } = useI18n();
  const rows = useDebtSchedule(seriesId);
  if (rows.isPending) {
    return <Loading />;
  }
  return (
    <>
      <ProblemMessage error={rows.error} />
      {rows.data?.length ? (
        <div className="table-scroll">
          <table>
            <caption>{t("cm.instalments")}</caption>
            <thead>
              <tr>
                <th scope="col">#</th>
                <th scope="col">{t("cm.due")}</th>
                <th scope="col" className="amount">
                  {t("cm.opening")}
                </th>
                <th scope="col" className="amount">
                  {t("cm.interest")}
                </th>
                <th scope="col" className="amount">
                  {t("cm.principal")}
                </th>
                <th scope="col" className="amount">
                  {t("cm.payment")}
                </th>
                <th scope="col" className="amount">
                  {t("cm.closing")}
                </th>
              </tr>
            </thead>
            <tbody>
              {rows.data.map((r) => (
                <tr key={r.number}>
                  <td>{r.number}</td>
                  <td>{r.due}</td>
                  <td className="amount">{formatAmount(r.opening, locale)}</td>
                  <td className="amount">{formatAmount(r.interest, locale)}</td>
                  <td className="amount">
                    {formatAmount(r.principal, locale)}
                  </td>
                  <td className="amount">{formatAmount(r.payment, locale)}</td>
                  <td className="amount">{formatAmount(r.closing, locale)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </>
  );
}

function DebtSection() {
  const { t, locale } = useI18n();
  const list = useDebts();
  const { saveDebt, retire } = useCommitmentMutations();
  const [form, setForm] = useState<DebtInput>(EMPTY_DEBT);
  const [editing, setEditing] = useState<string | null>(null);
  const [shown, setShown] = useState<string | null>(null);
  const [percents, setPercents] = useState<Percents>(NO_PERCENTS);
  const facility = FACILITIES.includes(form.kind);
  const set = (changes: Partial<DebtInput>) => setForm({ ...form, ...changes });

  function submit(event: SyntheticEvent) {
    event.preventDefault();
    const rates =
      form.rate_type === "FIXED"
        ? {
            fixed_rate: fromPercent(percents.fixed),
            margin: null,
            assumed_reference_rate: null,
          }
        : {
            fixed_rate: null,
            margin: fromPercent(percents.margin),
            assumed_reference_rate: fromPercent(percents.assumed),
          };
    const shape = facility
      ? {
          principal: null,
          maturity_date: null,
          repayment_type: "" as Repayment,
        }
      : { facility_limit: null, maturity_date: form.maturity_date || null };
    saveDebt.mutate(
      { seriesId: editing, body: { ...form, ...rates, ...shape } },
      {
        onSuccess: () => {
          setForm(EMPTY_DEBT);
          setPercents(NO_PERCENTS);
          setEditing(null);
        },
      },
    );
  }

  function edit(d: Debt) {
    setForm({
      name: d.name,
      kind: d.kind,
      principal: d.principal,
      facility_limit: d.facility_limit,
      start_date: d.start_date,
      maturity_date: d.maturity_date,
      payment_frequency_months: d.payment_frequency_months,
      rate_type: d.rate_type,
      fixed_rate: d.fixed_rate,
      reference_rate_key: d.reference_rate_key,
      margin: d.margin,
      assumed_reference_rate: d.assumed_reference_rate,
      day_count: d.day_count,
      repayment_type: d.repayment_type,
      interest_only_periods: d.interest_only_periods,
      adjust: d.adjust,
      lender_id: d.lender_id,
      note: d.note,
    });
    setPercents({
      fixed: toPercent(d.fixed_rate),
      margin: toPercent(d.margin),
      assumed: toPercent(d.assumed_reference_rate),
    });
    setEditing(d.series_id);
  }

  const rateText = (d: Debt) =>
    d.rate_type === "FIXED"
      ? `${toPercent(d.fixed_rate)}%`
      : `${d.reference_rate_key} + ${toPercent(d.margin)}% (${t("cm.assumed")} ${toPercent(d.assumed_reference_rate)}%)`;

  return (
    <section aria-labelledby="debt-heading">
      <h2 id="debt-heading">{t("cm.debts")}</h2>
      <p className="muted">{t("cm.debtsHelp")}</p>
      {list.isPending ? <Loading /> : null}
      <ProblemMessage error={list.error ?? retire.error} />
      {list.data?.length === 0 ? <p>{t("cm.noDebts")}</p> : null}
      {list.data?.length ? (
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th scope="col">{t("cm.name")}</th>
                <th scope="col">{t("cm.kind")}</th>
                <th scope="col" className="amount">
                  {t("cm.amount")}
                </th>
                <th scope="col">{t("cm.rate")}</th>
                <th scope="col">{t("cm.repayment")}</th>
                <th scope="col">{t("cm.maturity")}</th>
                <th scope="col">
                  <span className="visually-hidden">{t("cm.actions")}</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {list.data.map((d) => (
                <tr key={d.id}>
                  <td>{d.name}</td>
                  <td>{t(`cm.kind.${d.kind}` as MessageKey)}</td>
                  <td className="amount">
                    {formatAmount(
                      d.principal ?? d.facility_limit ?? "0.00",
                      locale,
                    )}
                    {d.facility_limit ? ` (${t("cm.limit")})` : ""}
                  </td>
                  <td>{rateText(d)}</td>
                  <td>
                    {d.repayment_type
                      ? t(`cm.rep.${d.repayment_type}` as MessageKey)
                      : "—"}
                  </td>
                  <td>{d.maturity_date ?? "—"}</td>
                  <td>
                    <div className="row-actions table-actions">
                      {d.repayment_type ? (
                        <button
                          type="button"
                          aria-expanded={shown === d.series_id}
                          onClick={() =>
                            setShown(shown === d.series_id ? null : d.series_id)
                          }
                        >
                          {t("cm.showSchedule")}
                        </button>
                      ) : null}
                      <button type="button" onClick={() => edit(d)}>
                        {t("cm.change")}
                      </button>
                      <button
                        type="button"
                        onClick={() =>
                          retire.mutate({
                            kind: "debt-instruments",
                            seriesId: d.series_id,
                          })
                        }
                      >
                        {t("cm.retire")}
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
      {shown ? <ScheduleTable seriesId={shown} /> : null}
      <form className="panel form inline" onSubmit={submit}>
        <h3>{editing ? t("cm.changeDebt") : t("cm.addDebt")}</h3>
        <label>
          {t("cm.name")}
          <input
            value={form.name}
            onChange={(e) => set({ name: e.target.value })}
            required
            maxLength={120}
          />
        </label>
        <label>
          {t("cm.kind")}
          <select
            value={form.kind}
            onChange={(e) => set({ kind: e.target.value as DebtKind })}
          >
            {KINDS.map((k) => (
              <option key={k} value={k}>
                {t(`cm.kind.${k}`)}
              </option>
            ))}
          </select>
        </label>
        {facility ? (
          <label>
            {t("cm.limit")}
            <input
              inputMode="decimal"
              value={form.facility_limit ?? ""}
              onChange={(e) => set({ facility_limit: e.target.value })}
              required
            />
            <FieldError error={saveDebt.error} field="facility_limit" />
          </label>
        ) : (
          <>
            <label>
              {t("cm.principal")}
              <input
                inputMode="decimal"
                value={form.principal ?? ""}
                onChange={(e) => set({ principal: e.target.value })}
                required
              />
              <FieldError error={saveDebt.error} field="principal" />
            </label>
            <label>
              {t("cm.maturity")}
              <input
                type="date"
                value={form.maturity_date ?? ""}
                onChange={(e) => set({ maturity_date: e.target.value })}
                required
              />
            </label>
            <label>
              {t("cm.repayment")}
              <select
                value={form.repayment_type}
                onChange={(e) =>
                  set({ repayment_type: e.target.value as Repayment })
                }
              >
                {REPAYMENTS.map((r) => (
                  <option key={r} value={r}>
                    {t(`cm.rep.${r}` as MessageKey)}
                  </option>
                ))}
              </select>
            </label>
            {form.repayment_type === "IO_THEN_ANNUITY" ? (
              <label>
                {t("cm.ioPeriods")}
                <input
                  type="number"
                  min={1}
                  value={form.interest_only_periods}
                  onChange={(e) =>
                    set({ interest_only_periods: Number(e.target.value) })
                  }
                />
              </label>
            ) : null}
            <label>
              {t("cm.paymentsEvery")}
              <select
                value={form.payment_frequency_months}
                onChange={(e) =>
                  set({
                    payment_frequency_months: Number(e.target.value) as
                      | 1
                      | 3
                      | 6
                      | 12,
                  })
                }
              >
                {[1, 3, 6, 12].map((m) => (
                  <option key={m} value={m}>
                    {t(`cm.months.${m}` as MessageKey)}
                  </option>
                ))}
              </select>
            </label>
            <label>
              {t("cm.dayCount")}
              <select
                value={form.day_count}
                onChange={(e) =>
                  set({ day_count: e.target.value as DebtInput["day_count"] })
                }
              >
                <option value="ACT_360">ACT/360</option>
                <option value="ACT_365">ACT/365</option>
                <option value="30_360">30/360</option>
              </select>
            </label>
          </>
        )}
        <label>
          {t("cm.start")}
          <input
            type="date"
            value={form.start_date}
            onChange={(e) => set({ start_date: e.target.value })}
            required
          />
        </label>
        <label>
          {t("cm.rateType")}
          <select
            value={form.rate_type}
            onChange={(e) =>
              set({ rate_type: e.target.value as "FIXED" | "VARIABLE" })
            }
          >
            <option value="FIXED">{t("cm.fixed")}</option>
            <option value="VARIABLE">{t("cm.variable")}</option>
          </select>
        </label>
        {form.rate_type === "FIXED" ? (
          <label>
            {t("cm.ratePercent")}
            <input
              inputMode="decimal"
              value={percents.fixed}
              onChange={(e) =>
                setPercents({ ...percents, fixed: e.target.value })
              }
              required
            />
            <FieldError error={saveDebt.error} field="fixed_rate" />
          </label>
        ) : (
          <>
            <label>
              {t("cm.referenceRate")}
              <input
                value={form.reference_rate_key}
                onChange={(e) => set({ reference_rate_key: e.target.value })}
                placeholder="EURIBOR_3M"
                maxLength={40}
                required
              />
            </label>
            <label>
              {t("cm.assumedPercent")}
              <input
                inputMode="decimal"
                value={percents.assumed}
                onChange={(e) =>
                  setPercents({ ...percents, assumed: e.target.value })
                }
                required
              />
            </label>
            <label>
              {t("cm.marginPercent")}
              <input
                inputMode="decimal"
                value={percents.margin}
                onChange={(e) =>
                  setPercents({ ...percents, margin: e.target.value })
                }
                required
              />
              <FieldError error={saveDebt.error} field="margin" />
            </label>
          </>
        )}
        <FieldError error={saveDebt.error} field="schedule" />
        <ProblemMessage error={saveDebt.error} />
        <div className="actions">
          <button
            type="submit"
            className="primary"
            disabled={saveDebt.isPending}
          >
            {editing ? t("cm.saveVersion") : t("cm.addDebt")}
          </button>
          {editing ? (
            <button
              type="button"
              onClick={() => {
                setEditing(null);
                setForm(EMPTY_DEBT);
                setPercents(NO_PERCENTS);
              }}
            >
              {t("cm.cancel")}
            </button>
          ) : null}
        </div>
      </form>
    </section>
  );
}

function HolidaysSection() {
  const { t } = useI18n();
  const list = useHolidays();
  const { addHoliday, removeHoliday } = useCommitmentMutations();
  const [form, setForm] = useState({ day: "", name: "" });

  function submit(event: SyntheticEvent) {
    event.preventDefault();
    addHoliday.mutate(form, {
      onSuccess: () => setForm({ day: "", name: "" }),
    });
  }

  return (
    <section aria-labelledby="hol-heading">
      <h2 id="hol-heading">{t("cm.holidays")}</h2>
      <p className="muted">{t("cm.holidaysHelp")}</p>
      <ProblemMessage error={list.error ?? removeHoliday.error} />
      {list.data?.length ? (
        <ul className="plain-list">
          {list.data.map((h) => (
            <li key={h.id}>
              {h.day} — {h.name}{" "}
              <button
                type="button"
                onClick={() => removeHoliday.mutate(h.id)}
                aria-label={`${t("cm.remove")} ${h.day}`}
              >
                {t("cm.remove")}
              </button>
            </li>
          ))}
        </ul>
      ) : null}
      <form className="panel form inline" onSubmit={submit}>
        <label>
          {t("cm.day")}
          <input
            type="date"
            value={form.day}
            onChange={(e) => setForm({ ...form, day: e.target.value })}
            required
          />
        </label>
        <label>
          {t("cm.name")}
          <input
            value={form.name}
            onChange={(e) => setForm({ ...form, name: e.target.value })}
            required
            maxLength={100}
          />
        </label>
        <ProblemMessage error={addHoliday.error} />
        <button type="submit" disabled={addHoliday.isPending}>
          {t("cm.addHoliday")}
        </button>
      </form>
    </section>
  );
}

function UpcomingSection() {
  const { t, locale } = useI18n();
  const from = today();
  const flows = useCommitmentFlows(from, addDays(from, 90));
  return (
    <section aria-labelledby="up-heading">
      <h2 id="up-heading">{t("cm.upcoming")}</h2>
      {flows.isPending ? <Loading /> : null}
      <ProblemMessage error={flows.error} />
      {flows.data?.length === 0 ? <p>{t("cm.noFlows")}</p> : null}
      {flows.data?.length ? (
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th scope="col">{t("cm.due")}</th>
                <th scope="col">{t("cm.name")}</th>
                <th scope="col">{t("cm.component")}</th>
                <th scope="col" className="amount">
                  {t("cm.amount")}
                </th>
                <th scope="col">{t("cm.nature")}</th>
              </tr>
            </thead>
            <tbody>
              {flows.data.map((f) => (
                <tr key={`${f.version_id}-${f.due}-${f.component}`}>
                  <td>
                    {f.due}
                    {f.due !== f.scheduled ? (
                      <span className="muted"> ({f.scheduled})</span>
                    ) : null}
                  </td>
                  <td>{f.name}</td>
                  <td>{t(`cm.comp.${f.component}` as MessageKey)}</td>
                  <td className="amount">{formatAmount(f.amount, locale)}</td>
                  <td>
                    <NatureBadge nature={f.nature} />
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

export function CommitmentsPage() {
  const { t } = useI18n();
  return (
    <Page title={t("cm.title")}>
      <ObligationsSection />
      <DebtSection />
      <HolidaysSection />
      <UpcomingSection />
    </Page>
  );
}
