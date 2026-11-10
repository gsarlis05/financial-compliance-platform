import { useState } from "react";
import {
  type GoalKind,
  type PersonalAccount,
  useMonthBudget,
  usePersonalAccounts,
  usePersonalGoals,
  usePlanMutations,
  useProjection,
} from "../api/personal";
import { Loading, Page, ProblemMessage } from "../components/common";
import { useI18n } from "../i18n/I18n";
import type { MessageKey } from "../i18n/messages";
import { formatAmount } from "../money";

const thisMonth = () => `${new Date().toISOString().slice(0, 7)}-01`;

function BudgetRow({
  accountId,
  name,
  budgeted,
  actual,
  remaining,
  over,
  month,
}: {
  accountId: string;
  name: string;
  budgeted: string;
  actual: string;
  remaining: string;
  over: boolean;
  month: string;
}) {
  const { t, locale } = useI18n();
  const m = usePlanMutations();
  const [value, setValue] = useState(budgeted);
  return (
    <tr>
      <th scope="row">{name}</th>
      <td className="num">
        <input
          aria-label={`${t("plan.monthly")} ${name}`}
          inputMode="decimal"
          size={8}
          value={value}
          onChange={(e) => setValue(e.target.value)}
        />{" "}
        <button
          type="button"
          disabled={value === budgeted || m.budget.isPending}
          onClick={() =>
            m.budget.mutate({
              account_id: accountId,
              monthly_amount: value,
              from_month: month,
            })
          }
        >
          {t("my.save")}
        </button>
      </td>
      <td className="num">{formatAmount(actual, locale)}</td>
      <td className="num">
        {formatAmount(remaining, locale)}
        {over ? ` ▼ ${t("plan.over")}` : ""}
      </td>
    </tr>
  );
}

function BudgetSection({ accounts }: { accounts: PersonalAccount[] }) {
  const { t, locale } = useI18n();
  const [month, setMonth] = useState(thisMonth());
  const budget = useMonthBudget(month);
  const m = usePlanMutations();
  const shown = new Set((budget.data?.lines ?? []).map((l) => l.account_id));
  const others = accounts.filter(
    (a) => (a.type === "EXPENSE" || a.type === "INCOME") && !shown.has(a.id),
  );
  const [added, setAdded] = useState({ account_id: "", monthly_amount: "" });
  return (
    <section className="card" aria-labelledby="plan-budget">
      <h2 id="plan-budget">{t("plan.budget")}</h2>
      <p className="muted">{t("plan.budgetText")}</p>
      <label>
        {t("my.month")}
        <input
          type="month"
          value={month.slice(0, 7)}
          onChange={(e) => e.target.value && setMonth(`${e.target.value}-01`)}
        />
      </label>
      {budget.isPending ? <Loading /> : null}
      <ProblemMessage error={budget.error ?? m.budget.error} />
      {budget.data ? (
        <div className="table-scroll">
          <table className="grid">
            <caption>
              {t("plan.budgetFor")} {month.slice(0, 7)}: {t("plan.spent")}{" "}
              {formatAmount(budget.data.actual_spending, locale)} /{" "}
              {t("plan.planned")}{" "}
              {formatAmount(budget.data.budgeted_spending, locale)}
            </caption>
            <thead>
              <tr>
                <th scope="col">{t("my.category")}</th>
                <th scope="col" className="num">
                  {t("plan.monthly")}
                </th>
                <th scope="col" className="num">
                  {t("my.amount")}
                </th>
                <th scope="col" className="num">
                  {t("plan.remaining")}
                </th>
              </tr>
            </thead>
            <tbody>
              {budget.data.lines.map((l) => (
                <BudgetRow
                  key={`${l.account_id}-${month}`}
                  accountId={l.account_id}
                  name={l.name}
                  budgeted={l.budgeted}
                  actual={l.actual}
                  remaining={l.remaining}
                  over={l.over}
                  month={month}
                />
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
      <div className="form inline">
        <label>
          {t("plan.addCategory")}
          <select
            value={added.account_id}
            onChange={(e) => setAdded({ ...added, account_id: e.target.value })}
          >
            <option value="">—</option>
            {others.map((a) => (
              <option key={a.id} value={a.id}>
                {a.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          {t("plan.monthly")}
          <input
            inputMode="decimal"
            value={added.monthly_amount}
            onChange={(e) =>
              setAdded({ ...added, monthly_amount: e.target.value })
            }
          />
        </label>
        <button
          type="button"
          disabled={
            !added.account_id || !added.monthly_amount || m.budget.isPending
          }
          onClick={() =>
            m.budget.mutate(
              { ...added, from_month: month },
              {
                onSuccess: () =>
                  setAdded({ account_id: "", monthly_amount: "" }),
              },
            )
          }
        >
          {t("my.add")}
        </button>
      </div>
    </section>
  );
}

const KINDS: GoalKind[] = ["SAVINGS", "EMERGENCY_FUND", "DEBT_PAYOFF"];

function GoalsSection({ accounts }: { accounts: PersonalAccount[] }) {
  const { t, locale } = useI18n();
  const goals = usePersonalGoals();
  const m = usePlanMutations();
  const [form, setForm] = useState({
    kind: "SAVINGS" as GoalKind,
    name: "",
    account_id: "",
    target_amount: "",
    months: "3",
    target_date: "",
  });
  const choices = accounts.filter((a) =>
    form.kind === "DEBT_PAYOFF" ? a.type === "LIABILITY" : a.type === "ASSET",
  );
  const names = new Map(accounts.map((a) => [a.id, a.name]));
  const save = () =>
    m.goal.mutate(
      {
        kind: form.kind,
        name: form.name,
        account_ids: [form.account_id],
        target_date: form.target_date,
        target_amount:
          form.kind === "EMERGENCY_FUND" ? "0" : form.target_amount || "0",
        ...(form.kind === "EMERGENCY_FUND"
          ? { months: Number(form.months) }
          : {}),
      },
      { onSuccess: () => setForm({ ...form, name: "", target_amount: "" }) },
    );
  return (
    <section className="card" aria-labelledby="plan-goals">
      <h2 id="plan-goals">{t("plan.goals")}</h2>
      {goals.isPending ? <Loading /> : null}
      <ProblemMessage error={goals.error ?? m.retire.error} />
      {goals.data?.length ? (
        <div className="table-scroll">
          <table className="grid">
            <caption>{t("plan.goals")}</caption>
            <thead>
              <tr>
                <th scope="col">{t("goal.name")}</th>
                <th scope="col" className="num">
                  {t("plan.now")}
                </th>
                <th scope="col" className="num">
                  {t("goal.target")}
                </th>
                <th scope="col" className="num">
                  {t("plan.needed")}
                </th>
                <th scope="col" className="num">
                  {t("plan.pace")}
                </th>
                <th scope="col" className="num">
                  {t("plan.projected")}
                </th>
                <th scope="col">{t("goal.statusCol")}</th>
                <th scope="col">
                  <span className="visually-hidden">{t("my.actions")}</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {goals.data.map((g) => (
                <tr key={g.id}>
                  <th scope="row">
                    {g.name}
                    <br />
                    <span className="muted">
                      {t(`plan.kind.${g.kind}` as MessageKey)} ·{" "}
                      {g.account_ids.map((a) => names.get(a) ?? "").join(", ")}{" "}
                      · {g.target_date}
                    </span>
                  </th>
                  <td className="num">{formatAmount(g.current, locale)}</td>
                  <td className="num">{formatAmount(g.target, locale)}</td>
                  <td className="num">
                    {g.needed_per_month === null
                      ? "—"
                      : formatAmount(g.needed_per_month, locale)}
                  </td>
                  <td className="num">
                    {formatAmount(g.pace_per_month, locale)}
                  </td>
                  <td className="num">{formatAmount(g.projected, locale)}</td>
                  <td>
                    <span
                      className={`badge ${g.status === "ON_TRACK" ? "badge-open" : "badge-warn"}`}
                    >
                      {t(`goal.status.${g.status}` as MessageKey)}
                    </span>
                  </td>
                  <td>
                    <button
                      type="button"
                      className="link"
                      onClick={() => m.retire.mutate(g.id)}
                    >
                      {t("goal.retire")}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : goals.data ? (
        <p className="muted">{t("plan.noGoals")}</p>
      ) : null}
      <h3>{t("plan.newGoal")}</h3>
      <div className="form inline">
        <label>
          {t("my.kind")}
          <select
            value={form.kind}
            onChange={(e) =>
              setForm({
                ...form,
                kind: e.target.value as GoalKind,
                account_id: "",
              })
            }
          >
            {KINDS.map((k) => (
              <option key={k} value={k}>
                {t(`plan.kind.${k}` as MessageKey)}
              </option>
            ))}
          </select>
        </label>
        <label>
          {t("goal.name")}
          <input
            value={form.name}
            maxLength={120}
            onChange={(e) => setForm({ ...form, name: e.target.value })}
          />
        </label>
        <label>
          {t("my.account")}
          <select
            value={form.account_id}
            onChange={(e) => setForm({ ...form, account_id: e.target.value })}
          >
            <option value="">—</option>
            {choices.map((a) => (
              <option key={a.id} value={a.id}>
                {a.name}
              </option>
            ))}
          </select>
        </label>
        {form.kind === "EMERGENCY_FUND" ? (
          <label>
            {t("plan.months")}
            <input
              inputMode="numeric"
              value={form.months}
              onChange={(e) => setForm({ ...form, months: e.target.value })}
            />
          </label>
        ) : (
          <label>
            {t(
              form.kind === "DEBT_PAYOFF"
                ? "plan.owedAtMost"
                : "plan.saveTotal",
            )}
            <input
              inputMode="decimal"
              value={form.target_amount}
              onChange={(e) =>
                setForm({ ...form, target_amount: e.target.value })
              }
            />
          </label>
        )}
        <label>
          {t("plan.byDate")}
          <input
            type="date"
            value={form.target_date}
            onChange={(e) => setForm({ ...form, target_date: e.target.value })}
          />
        </label>
        <button
          type="button"
          className="primary"
          disabled={
            !form.name.trim() ||
            !form.account_id ||
            !form.target_date ||
            m.goal.isPending
          }
          onClick={save}
        >
          {t("my.add")}
        </button>
      </div>
      <ProblemMessage error={m.goal.error} />
    </section>
  );
}

function ProjectionSection() {
  const { t, locale } = useI18n();
  const p = useProjection();
  if (p.isPending) return <Loading />;
  if (!p.data) return <ProblemMessage error={p.error} />;
  return (
    <section className="card" aria-labelledby="plan-projection">
      <h2 id="plan-projection">{t("plan.projection")}</h2>
      <p className="muted">
        {t("plan.projectionText")} {t("plan.cashToday")}:{" "}
        {formatAmount(p.data.opening_cash, locale)}
      </p>
      {p.data.first_negative ? (
        <p className="error" role="alert">
          {t("plan.firstNegative")} {p.data.first_negative.slice(0, 7)}
        </p>
      ) : null}
      <div className="table-scroll">
        <table className="grid">
          <caption>{t("plan.projection")}</caption>
          <thead>
            <tr>
              <th scope="col">{t("my.month")}</th>
              <th scope="col" className="num">
                {t("my.income")}
              </th>
              <th scope="col" className="num">
                {t("my.spending")}
              </th>
              <th scope="col" className="num">
                {t("plan.cash")}
              </th>
              <th scope="col">{t("goal.nature")}</th>
            </tr>
          </thead>
          <tbody>
            {p.data.months.map((m) => (
              <tr key={m.month}>
                <td>{m.month.slice(0, 7)}</td>
                <td className="num">{formatAmount(m.income, locale)}</td>
                <td className="num">{formatAmount(m.spending, locale)}</td>
                <td className="num">{formatAmount(m.closing_cash, locale)}</td>
                <td>
                  <span className={`badge nature-${m.nature.toLowerCase()}`}>
                    {t(`nature.${m.nature}` as MessageKey)}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

export function PersonalPlanPage() {
  const { t } = useI18n();
  const accounts = usePersonalAccounts();
  return (
    <Page title={t("plan.title")}>
      {accounts.isPending ? <Loading /> : null}
      <ProblemMessage error={accounts.error} />
      {accounts.data ? (
        <>
          <BudgetSection accounts={accounts.data} />
          <GoalsSection accounts={accounts.data} />
          <ProjectionSection />
        </>
      ) : null}
    </Page>
  );
}
