// Assumption sets (M6-2): the drivers of a projection, month by month. Drafts are edited in a
// grid; an approved set never changes, and a revision is a new version.
import { useState } from "react";
import {
  type AssumptionGrid,
  type Change,
  type GridRow,
  type StartFrom,
  useAssumptionGrid,
  useAssumptionMutations,
  type LoanInput,
  type LoanStructure,
  useAssumptionSets,
  useLoanMutations,
  useLoans,
} from "../api/projections";
import {
  FieldError,
  Loading,
  Page,
  ProblemMessage,
} from "../components/common";
import { useI18n } from "../i18n/I18n";
import type { MessageKey } from "../i18n/messages";
import { formatAmount } from "../money";

const lastMonthEnd = () => {
  const d = new Date();
  return new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), 0))
    .toISOString()
    .slice(0, 10);
};
const monthEnd = (ym: string) => {
  const [y, m] = ym.split("-").map(Number);
  return new Date(Date.UTC(y ?? 2000, m ?? 1, 0)).toISOString().slice(0, 10);
};
const key = (row: GridRow, month: string) =>
  `${row.driver}|${row.line}|${month}`;

function NewSet({ onMade }: { onMade: (id: string) => void }) {
  const { t } = useI18n();
  const m = useAssumptionMutations();
  const [form, setForm] = useState({
    name: "",
    cutover: lastMonthEnd().slice(0, 7),
    months: 24,
    start_from: "ACTUALS" as StartFrom,
    revenue_growth: "0",
  });
  return (
    <section className="card" aria-labelledby="as-new">
      <h2 id="as-new">{t("as.new")}</h2>
      <div className="form inline">
        <label>
          {t("as.name")}
          <input
            value={form.name}
            maxLength={120}
            onChange={(e) => setForm({ ...form, name: e.target.value })}
          />
        </label>
        <label>
          {t("as.cutover")}
          <input
            type="month"
            value={form.cutover}
            onChange={(e) => setForm({ ...form, cutover: e.target.value })}
          />
        </label>
        <label>
          {t("as.horizon")}
          <select
            value={form.months}
            onChange={(e) =>
              setForm({ ...form, months: Number(e.target.value) })
            }
          >
            {[12, 24, 36].map((n) => (
              <option key={n} value={n}>
                {n} {t("fa.months")}
              </option>
            ))}
          </select>
        </label>
        <label>
          {t("as.startFrom")}
          <select
            value={form.start_from}
            onChange={(e) =>
              setForm({ ...form, start_from: e.target.value as StartFrom })
            }
          >
            {(["ACTUALS", "BUDGET", "EMPTY"] as StartFrom[]).map((s) => (
              <option key={s} value={s}>
                {t(`as.from.${s}` as MessageKey)}
              </option>
            ))}
          </select>
        </label>
        {form.start_from === "ACTUALS" ? (
          <label>
            {t("as.growth")}
            <input
              inputMode="decimal"
              value={form.revenue_growth}
              onChange={(e) =>
                setForm({ ...form, revenue_growth: e.target.value })
              }
            />
          </label>
        ) : null}
        <button
          type="button"
          className="primary"
          disabled={!form.name.trim() || !form.cutover || m.create.isPending}
          onClick={() =>
            m.create.mutate(
              {
                ...form,
                cutover: monthEnd(form.cutover),
                revenue_growth: form.revenue_growth || "0",
              },
              { onSuccess: (made) => onMade(made.id) },
            )
          }
        >
          {t("as.create")}
        </button>
      </div>
      <ProblemMessage error={m.create.error} />
    </section>
  );
}

function rowLabel(t: (k: MessageKey) => string, row: GridRow) {
  const driver = t(`as.driver.${row.driver}` as MessageKey);
  if (row.driver.startsWith("loan_")) return `${driver}: ${row.line}`;
  return row.line
    ? `${driver}: ${t(`as.line.${row.line}` as MessageKey)}`
    : driver;
}

const STRUCTURES: LoanStructure[] = ["ANNUITY", "EQUAL_PRINCIPAL", "BULLET"];

function Loans({ setId, draft }: { setId: string; draft: boolean }) {
  const { t, locale } = useI18n();
  const list = useLoans(setId);
  const m = useLoanMutations(setId);
  const blank = (): LoanInput => ({
    code: "",
    name: "",
    kind: "NEW",
    structure: "ANNUITY",
    term_months: 60,
    annual_rate: "5",
    opening_balance: "0",
    amount: "",
    drawdown_month: null,
    interest_only_months: 0,
  });
  const [form, setForm] = useState<LoanInput>(blank);
  const set = (patch: Partial<LoanInput>) => setForm({ ...form, ...patch });
  const error = m.add.error ?? m.fromRegister.error ?? m.remove.error;
  return (
    <section className="card" aria-labelledby="as-loans">
      <h2 id="as-loans">{t("as.loans")}</h2>
      <p className="muted">{t("as.loansIntro")}</p>
      {list.data?.length ? (
        <div className="table-scroll">
          <table className="grid">
            <caption>{t("as.loans")}</caption>
            <thead>
              <tr>
                <th scope="col">{t("as.loanCode")}</th>
                <th scope="col">{t("as.name")}</th>
                <th scope="col">{t("as.loanKind")}</th>
                <th scope="col">{t("as.loanStructure")}</th>
                <th scope="col" className="num">
                  {t("as.loanBalance")}
                </th>
                <th scope="col" className="num">
                  {t("as.loanRate")}
                </th>
                <th scope="col" className="num">
                  {t("as.loanTerm")}
                </th>
                {draft ? (
                  <th scope="col">
                    <span className="visually-hidden">{t("eng.actions")}</span>
                  </th>
                ) : null}
              </tr>
            </thead>
            <tbody>
              {list.data.map((loan) => (
                <tr key={loan.code}>
                  <th scope="row">{loan.code}</th>
                  <td>
                    {loan.name}
                    {loan.note ? (
                      <span className="muted"> · {loan.note}</span>
                    ) : null}
                  </td>
                  <td>
                    {t(`as.kind.${loan.kind}` as MessageKey)}
                    {loan.drawdown_month
                      ? ` (${loan.drawdown_month.slice(0, 7)})`
                      : ""}
                  </td>
                  <td>{t(`as.structure.${loan.structure}` as MessageKey)}</td>
                  <td className="num">
                    {formatAmount(
                      loan.kind === "NEW" ? loan.amount : loan.opening_balance,
                      locale,
                    )}
                  </td>
                  <td className="num">{loan.annual_rate}%</td>
                  <td className="num">
                    {loan.term_months}
                    {loan.interest_only_months
                      ? ` (${loan.interest_only_months} ${t("as.interestOnly")})`
                      : ""}
                  </td>
                  {draft ? (
                    <td>
                      <button
                        type="button"
                        className="link-button"
                        onClick={() => m.remove.mutate(loan.code)}
                      >
                        {t("as.removeLoan")} {loan.code}
                      </button>
                    </td>
                  ) : null}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="muted">{t("as.noLoans")}</p>
      )}
      {draft ? (
        <>
          <button
            type="button"
            disabled={m.fromRegister.isPending}
            onClick={() => m.fromRegister.mutate()}
          >
            {t("as.fromRegister")}
          </button>
          <div className="form inline">
            <label>
              {t("as.loanCode")}
              <input
                value={form.code}
                maxLength={20}
                onChange={(e) => set({ code: e.target.value })}
              />
              <FieldError error={m.add.error} field="code" />
            </label>
            <label>
              {t("as.name")}
              <input
                value={form.name}
                maxLength={120}
                onChange={(e) => set({ name: e.target.value })}
              />
            </label>
            <label>
              {t("as.loanKind")}
              <select
                value={form.kind}
                onChange={(e) =>
                  set({ kind: e.target.value as LoanInput["kind"] })
                }
              >
                <option value="NEW">{t("as.kind.NEW")}</option>
                <option value="EXISTING">{t("as.kind.EXISTING")}</option>
              </select>
            </label>
            {form.kind === "NEW" ? (
              <>
                <label>
                  {t("as.loanAmount")}
                  <input
                    inputMode="decimal"
                    value={form.amount}
                    onChange={(e) => set({ amount: e.target.value })}
                  />
                </label>
                <label>
                  {t("as.drawdownMonth")}
                  <input
                    type="month"
                    value={form.drawdown_month?.slice(0, 7) ?? ""}
                    onChange={(e) =>
                      set({
                        drawdown_month: e.target.value
                          ? `${e.target.value}-01`
                          : null,
                      })
                    }
                  />
                  <FieldError error={m.add.error} field="drawdown_month" />
                </label>
              </>
            ) : (
              <label>
                {t("as.loanBalance")}
                <input
                  inputMode="decimal"
                  value={form.opening_balance}
                  onChange={(e) => set({ opening_balance: e.target.value })}
                />
                <FieldError error={m.add.error} field="opening_balance" />
              </label>
            )}
            <label>
              {t("as.loanStructure")}
              <select
                value={form.structure}
                onChange={(e) =>
                  set({ structure: e.target.value as LoanStructure })
                }
              >
                {STRUCTURES.map((x) => (
                  <option key={x} value={x}>
                    {t(`as.structure.${x}` as MessageKey)}
                  </option>
                ))}
              </select>
            </label>
            <label>
              {t("as.loanRate")}
              <input
                inputMode="decimal"
                value={form.annual_rate}
                onChange={(e) => set({ annual_rate: e.target.value })}
              />
            </label>
            <label>
              {t("as.loanTerm")}
              <input
                inputMode="numeric"
                value={form.term_months}
                onChange={(e) =>
                  set({ term_months: Number(e.target.value) || 0 })
                }
              />
              <FieldError error={m.add.error} field="term_months" />
            </label>
            <label>
              {t("as.interestOnlyMonths")}
              <input
                inputMode="numeric"
                value={form.interest_only_months}
                onChange={(e) =>
                  set({ interest_only_months: Number(e.target.value) || 0 })
                }
              />
            </label>
            <button
              type="button"
              disabled={
                !form.code.trim() || !form.name.trim() || m.add.isPending
              }
              onClick={() =>
                m.add.mutate(form, { onSuccess: () => setForm(blank()) })
              }
            >
              {t("as.addLoan")}
            </button>
          </div>
        </>
      ) : null}
      <ProblemMessage error={error} />
    </section>
  );
}

function Grid({ grid }: { grid: AssumptionGrid }) {
  const { t } = useI18n();
  const m = useAssumptionMutations();
  const set = grid.assumption_set;
  const draft = set.status === "DRAFT";
  const [edits, setEdits] = useState<Record<string, string>>({});
  const value = (row: GridRow, i: number) =>
    edits[key(row, grid.months[i] ?? "")] ?? row.values[i] ?? "";
  const edit = (row: GridRow, month: string, v: string) =>
    setEdits({ ...edits, [key(row, month)]: v });
  const fillRight = (row: GridRow) => {
    const first = value(row, 0);
    const next = { ...edits };
    for (const month of grid.months) next[key(row, month)] = first;
    setEdits(next);
  };
  const changes: Change[] = Object.entries(edits).map(([k, v]) => {
    const [driver = "", line = "", month = ""] = k.split("|");
    return { driver, line, month, value: v.trim() };
  });
  return (
    <section className="card" aria-labelledby="as-grid">
      <h2 id="as-grid">
        {set.name} · {t("as.version")} {set.version} ·{" "}
        {t(`as.status.${set.status}` as MessageKey)}
      </h2>
      <p className="muted">
        {set.note} {t("as.forecastNote")}
      </p>
      <div className="form inline">
        {draft ? (
          <>
            <button
              type="button"
              className="primary"
              disabled={changes.length === 0 || m.save.isPending}
              onClick={() =>
                m.save.mutate(
                  { id: set.id, changes },
                  { onSuccess: () => setEdits({}) },
                )
              }
            >
              {t("as.save")} ({changes.length})
            </button>
            <button
              type="button"
              disabled={changes.length > 0 || m.approve.isPending}
              onClick={() => m.approve.mutate(set.id)}
            >
              {t("as.approve")}
            </button>
          </>
        ) : (
          <button
            type="button"
            disabled={m.revise.isPending}
            onClick={() => m.revise.mutate(set.id)}
          >
            {t("as.revise")}
          </button>
        )}
      </div>
      <ProblemMessage
        error={m.save.error ?? m.approve.error ?? m.revise.error}
      />
      <div className="table-scroll">
        <table className="grid assumptions">
          <caption>{t("as.gridCaption")}</caption>
          <thead>
            <tr>
              <th scope="col">{t("as.driver")}</th>
              {grid.months.map((month) => (
                <th key={month} scope="col" className="num">
                  {month.slice(0, 7)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {grid.rows.map((row) => (
              <tr key={`${row.driver}|${row.line}`}>
                <th scope="row">
                  {rowLabel(t, row)}{" "}
                  <span className="muted">
                    ({t(`as.unit.${row.unit}` as MessageKey)})
                  </span>
                  {draft ? (
                    <>
                      {" "}
                      <button
                        type="button"
                        className="link-button"
                        aria-label={`${t("as.fillRight")}: ${rowLabel(t, row)}`}
                        onClick={() => fillRight(row)}
                      >
                        {t("as.fillRight")}
                      </button>
                    </>
                  ) : null}
                </th>
                {grid.months.map((month, i) => (
                  <td
                    key={month}
                    className={`num source-${(row.sources[i] ?? "").toLowerCase()}`}
                    title={t(
                      `as.src.${row.sources[i] ?? "DEFAULT"}` as MessageKey,
                    )}
                  >
                    {draft ? (
                      <input
                        inputMode="decimal"
                        size={7}
                        aria-label={`${rowLabel(t, row)} ${month.slice(0, 7)}`}
                        value={value(row, i)}
                        onChange={(e) => edit(row, month, e.target.value)}
                      />
                    ) : (
                      value(row, i)
                    )}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

export function AssumptionsPage() {
  const { t } = useI18n();
  const list = useAssumptionSets();
  const [open, setOpen] = useState<string | null>(null);
  const grid = useAssumptionGrid(open);
  return (
    <Page title={t("nav.assumptions")}>
      <p className="muted">{t("as.intro")}</p>
      <NewSet onMade={setOpen} />
      {list.isPending ? <Loading /> : null}
      <ProblemMessage error={list.error ?? grid.error} />
      {list.data?.length ? (
        <div className="table-scroll">
          <table className="grid">
            <caption>{t("as.sets")}</caption>
            <thead>
              <tr>
                <th scope="col">{t("as.name")}</th>
                <th scope="col">{t("as.version")}</th>
                <th scope="col">{t("as.cutover")}</th>
                <th scope="col">{t("as.horizon")}</th>
                <th scope="col">{t("as.statusCol")}</th>
                <th scope="col">
                  <span className="visually-hidden">{t("eng.actions")}</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {list.data.map((s) => (
                <tr key={s.id}>
                  <th scope="row">{s.name}</th>
                  <td>{s.version}</td>
                  <td>{s.cutover}</td>
                  <td>
                    {s.months} {t("fa.months")}
                  </td>
                  <td>{t(`as.status.${s.status}` as MessageKey)}</td>
                  <td>
                    <button
                      type="button"
                      className="link-button"
                      aria-pressed={open === s.id}
                      onClick={() => setOpen(open === s.id ? null : s.id)}
                    >
                      {t("as.open")}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : list.data ? (
        <p className="muted">{t("as.none")}</p>
      ) : null}
      {grid.data && open ? (
        <>
          <Loans
            setId={open}
            draft={grid.data.assumption_set.status === "DRAFT"}
          />
          <Grid key={open + grid.data.assumption_set.status} grid={grid.data} />
        </>
      ) : null}
    </Page>
  );
}
