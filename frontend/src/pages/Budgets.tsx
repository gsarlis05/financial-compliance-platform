import Decimal from "decimal.js";
import { useMemo, useState } from "react";
import {
  type Budget,
  type BudgetKind,
  type BudgetVersionDetail,
  type LineIn,
  useBudgetEvents,
  useBudgetMutations,
  useBudgetSettings,
  useBudgets,
  useBudgetVersion,
} from "../api/budget";
import {
  useAccounts,
  useDimensions,
  useFiscalYears,
  useTaxonomy,
} from "../api/hooks";
import { Loading, Page, ProblemMessage } from "../components/common";
import { useI18n } from "../i18n/I18n";
import type { MessageKey } from "../i18n/messages";
import { formatAmount } from "../money";

const SIGNED = /^-?\d{1,15}(\.\d{1,2})?$/;

function amountOf(text: string): Decimal {
  const trimmed = text.trim();
  return SIGNED.test(trimmed) ? new Decimal(trimmed) : new Decimal(0);
}

function monthLabel(iso: string, locale: string): string {
  return new Intl.DateTimeFormat(locale === "el" ? "el-GR" : "en-GB", {
    month: "short",
    timeZone: "UTC",
  }).format(new Date(`${iso}T00:00:00Z`));
}

interface Row {
  key: string;
  taxonomy_code: string | null;
  account_id: string | null;
  dimension_value_id: string | null;
  note: string;
  amounts: string[];
}

function useNames() {
  const { locale } = useI18n();
  const taxonomy = useTaxonomy();
  const accounts = useAccounts();
  const dimensions = useDimensions();
  return useMemo(() => {
    const lines = new Map(
      (taxonomy.data ?? []).map((l) => [
        l.code,
        locale === "el" && l.name_el ? l.name_el : l.name,
      ]),
    );
    const accs = new Map(
      (accounts.data ?? []).map((a) => [
        a.id,
        `${a.code} · ${locale === "el" && a.name_el ? a.name_el : a.name}`,
      ]),
    );
    const values = new Map(
      (dimensions.data ?? []).flatMap((d) =>
        d.values.map((v) => [v.id, `${d.code}: ${v.name}`] as const),
      ),
    );
    return {
      subject: (r: {
        taxonomy_code: string | null;
        account_id: string | null;
      }) =>
        r.taxonomy_code
          ? `${r.taxonomy_code} · ${lines.get(r.taxonomy_code) ?? ""}`
          : (accs.get(r.account_id ?? "") ?? "?"),
      value: (id: string | null) => (id ? (values.get(id) ?? "?") : ""),
      taxonomy: taxonomy.data ?? [],
      accounts: (accounts.data ?? []).filter(
        (a) => a.is_postable && a.status === "ACTIVE",
      ),
      dimensions: dimensions.data ?? [],
    };
  }, [taxonomy.data, accounts.data, dimensions.data, locale]);
}

function LineEditor({ detail }: { detail: BudgetVersionDetail }) {
  const { t, locale } = useI18n();
  const names = useNames();
  const { saveLines } = useBudgetMutations();
  const [rows, setRows] = useState<Row[]>(() =>
    detail.lines.map((l) => ({
      key: l.id,
      taxonomy_code: l.taxonomy_code,
      account_id: l.account_id,
      dimension_value_id: l.dimension_value_id,
      note: l.note,
      amounts: [...l.amounts],
    })),
  );
  const [subject, setSubject] = useState("");
  const months = detail.months;
  const blank = () => months.map(() => "0.00");
  const invalid = rows.some((r) =>
    r.amounts.some((a) => !SIGNED.test(a.trim())),
  );
  const set = (i: number, m: number, value: string) =>
    setRows((rs) =>
      rs.map((r, j) =>
        j === i
          ? { ...r, amounts: r.amounts.map((a, k) => (k === m ? value : a)) }
          : r,
      ),
    );
  const add = () => {
    if (!subject) return;
    const [kind, id] = subject.split(":", 2) as [string, string];
    setRows((rs) => [
      ...rs,
      {
        key: `new-${String(rs.length)}-${subject}`,
        taxonomy_code: kind === "t" ? id : null,
        account_id: kind === "a" ? id : null,
        dimension_value_id: null,
        note: "",
        amounts: blank(),
      },
    ]);
    setSubject("");
  };
  const payload = (): LineIn[] =>
    rows.map((r) => ({
      taxonomy_code: r.taxonomy_code,
      account_id: r.account_id,
      dimension_value_id: r.dimension_value_id,
      note: r.note,
      amounts: Object.fromEntries(
        months.map((m, k) => [m, r.amounts[k]?.trim() ?? "0"]),
      ),
    }));
  const totals = months.map((_, k) =>
    rows.reduce(
      (acc, r) => acc.plus(amountOf(r.amounts[k] ?? "")),
      new Decimal(0),
    ),
  );
  return (
    <section aria-labelledby="bu-lines">
      <h3 id="bu-lines">{t("bu.lines")}</h3>
      <p className="muted">{t("bu.linesHelp")}</p>
      <div className="table-scroll">
        <table className="grid budget-grid">
          <caption className="visually-hidden">{t("bu.lines")}</caption>
          <thead>
            <tr>
              <th scope="col">{t("bu.line")}</th>
              {months.map((m) => (
                <th scope="col" key={m} className="num">
                  {monthLabel(m, locale)}
                </th>
              ))}
              <th scope="col" className="num">
                {t("bu.total")}
              </th>
              <th scope="col">
                <span className="visually-hidden">{t("bu.actions")}</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => {
              const label = names.subject(r);
              const total = r.amounts.reduce(
                (acc, a) => acc.plus(amountOf(a)),
                new Decimal(0),
              );
              return (
                <tr key={r.key}>
                  <th scope="row">
                    {label}
                    {r.dimension_value_id ? (
                      <span className="muted">
                        {" "}
                        · {names.value(r.dimension_value_id)}
                      </span>
                    ) : null}
                  </th>
                  {months.map((m, k) => (
                    <td key={m}>
                      <input
                        className="num"
                        inputMode="decimal"
                        aria-label={`${label} ${monthLabel(m, locale)}`}
                        aria-invalid={!SIGNED.test((r.amounts[k] ?? "").trim())}
                        value={r.amounts[k] ?? ""}
                        onChange={(e) => set(i, k, e.target.value)}
                        size={9}
                      />
                    </td>
                  ))}
                  <td className="num">{formatAmount(total, locale)}</td>
                  <td>
                    <button
                      type="button"
                      onClick={() =>
                        setRows((rs) => rs.filter((_, j) => j !== i))
                      }
                    >
                      {t("bu.remove")}
                      <span className="visually-hidden"> {label}</span>
                    </button>
                  </td>
                </tr>
              );
            })}
          </tbody>
          <tfoot>
            <tr>
              <th scope="row">{t("bu.total")}</th>
              {totals.map((v, k) => (
                <td key={months[k]} className="num">
                  {formatAmount(v, locale)}
                </td>
              ))}
              <td className="num">
                {formatAmount(
                  totals.reduce((a, b) => a.plus(b), new Decimal(0)),
                  locale,
                )}
              </td>
              <td />
            </tr>
          </tfoot>
        </table>
      </div>
      <div className="form inline">
        <label>
          {t("bu.addLine")}
          <select value={subject} onChange={(e) => setSubject(e.target.value)}>
            <option value="">{t("bu.choose")}</option>
            <optgroup label={t("bu.taxonomyLines")}>
              {names.taxonomy
                .filter((l) => l.statement === "PL")
                .map((l) => (
                  <option key={l.code} value={`t:${l.code}`}>
                    {names.subject({ taxonomy_code: l.code, account_id: null })}
                  </option>
                ))}
            </optgroup>
            <optgroup label={t("bu.accounts")}>
              {names.accounts.map((a) => (
                <option key={a.id} value={`a:${a.id}`}>
                  {names.subject({ taxonomy_code: null, account_id: a.id })}
                </option>
              ))}
            </optgroup>
          </select>
        </label>
        <button type="button" onClick={add} disabled={!subject}>
          {t("bu.add")}
        </button>
        <button
          type="button"
          className="primary"
          disabled={invalid || saveLines.isPending}
          onClick={() =>
            saveLines.mutate({ versionId: detail.id, lines: payload() })
          }
        >
          {t("bu.saveLines")}
        </button>
        {saveLines.isSuccess ? (
          <span role="status">{t("bu.saved")}</span>
        ) : null}
      </div>
      {invalid ? <p className="error">{t("bu.invalidAmount")}</p> : null}
      <ProblemMessage error={saveLines.error} />
    </section>
  );
}

function LineTable({ detail }: { detail: BudgetVersionDetail }) {
  const { t, locale } = useI18n();
  const names = useNames();
  const quarters =
    detail.lines[0]?.quarters.length ?? Math.ceil(detail.months.length / 3);
  const quarterTotals = Array.from({ length: quarters }, (_, q) =>
    detail.lines.reduce(
      (acc, l) => acc.plus(amountOf(l.quarters[q] ?? "0")),
      new Decimal(0),
    ),
  );
  return (
    <section aria-labelledby="bu-lines">
      <h3 id="bu-lines">{t("bu.lines")}</h3>
      <div className="table-scroll">
        <table className="grid">
          <caption className="visually-hidden">{t("bu.lines")}</caption>
          <thead>
            <tr>
              <th scope="col">{t("bu.line")}</th>
              <th scope="col">{t("bu.nature")}</th>
              {detail.months.map((m) => (
                <th scope="col" key={m} className="num">
                  {monthLabel(m, locale)}
                </th>
              ))}
              {quarterTotals.map((_, q) => (
                <th scope="col" key={`q${String(q)}`} className="num">
                  {t("bu.quarter")} {q + 1}
                </th>
              ))}
              <th scope="col" className="num">
                {t("bu.total")}
              </th>
            </tr>
          </thead>
          <tbody>
            {detail.lines.map((l) => (
              <tr key={l.id}>
                <th scope="row">
                  {names.subject(l)}
                  {l.dimension_value_id ? (
                    <span className="muted">
                      {" "}
                      · {names.value(l.dimension_value_id)}
                    </span>
                  ) : null}
                </th>
                <td>{t("nature.BUDGET")}</td>
                {l.amounts.map((a, k) => (
                  <td key={detail.months[k]} className="num">
                    {formatAmount(a, locale)}
                  </td>
                ))}
                {l.quarters.map((q, k) => (
                  <td key={`q${String(k)}`} className="num">
                    {formatAmount(q, locale)}
                  </td>
                ))}
                <td className="num">
                  <strong>{formatAmount(l.total, locale)}</strong>
                </td>
              </tr>
            ))}
          </tbody>
          <tfoot>
            <tr>
              <th scope="row">{t("bu.total")}</th>
              <td />
              {detail.month_totals.map((v, k) => (
                <td key={detail.months[k]} className="num">
                  {formatAmount(v, locale)}
                </td>
              ))}
              {quarterTotals.map((v, q) => (
                <td key={`q${String(q)}`} className="num">
                  {formatAmount(v, locale)}
                </td>
              ))}
              <td className="num">
                <strong>{formatAmount(detail.total, locale)}</strong>
              </td>
            </tr>
          </tfoot>
        </table>
      </div>
    </section>
  );
}

function VersionActions({ detail }: { detail: BudgetVersionDetail }) {
  const { t } = useI18n();
  const m = useBudgetMutations();
  const [text, setText] = useState("");
  const versionId = detail.id;
  const error =
    m.submit.error ??
    m.approve.error ??
    m.returnToDraft.error ??
    m.lock.error ??
    m.revise.error;
  return (
    <section aria-labelledby="bu-actions">
      <h3 id="bu-actions">{t("bu.actions")}</h3>
      {detail.status === "DRAFT" ? (
        <button
          type="button"
          className="primary"
          disabled={m.submit.isPending}
          onClick={() => m.submit.mutate({ versionId })}
        >
          {t("bu.submit")}
        </button>
      ) : null}
      {detail.status === "SUBMITTED" ? (
        <div className="form inline">
          <label>
            {t("bu.comment")}
            <input
              value={text}
              onChange={(e) => setText(e.target.value)}
              maxLength={500}
            />
          </label>
          <button
            type="button"
            className="primary"
            disabled={m.approve.isPending}
            onClick={() =>
              m.approve.mutate(
                { versionId, body: { comment: text } },
                { onSuccess: () => setText("") },
              )
            }
          >
            {t("bu.approve")}
          </button>
          <button
            type="button"
            disabled={m.returnToDraft.isPending || !text.trim()}
            onClick={() =>
              m.returnToDraft.mutate(
                { versionId, body: { comment: text } },
                { onSuccess: () => setText("") },
              )
            }
          >
            {t("bu.return")}
          </button>
        </div>
      ) : null}
      {detail.status === "APPROVED" ? (
        <button
          type="button"
          disabled={m.lock.isPending}
          onClick={() => m.lock.mutate({ versionId })}
        >
          {t("bu.lock")}
        </button>
      ) : null}
      {detail.status === "APPROVED" || detail.status === "LOCKED" ? (
        <div className="form inline">
          <label>
            {t("bu.reason")}
            <input
              value={text}
              onChange={(e) => setText(e.target.value)}
              maxLength={500}
            />
          </label>
          <button
            type="button"
            disabled={m.revise.isPending || !text.trim()}
            onClick={() =>
              m.revise.mutate(
                { versionId, body: { reason: text } },
                { onSuccess: () => setText("") },
              )
            }
          >
            {t("bu.revise")}
          </button>
        </div>
      ) : null}
      {detail.status === "SUPERSEDED" ? (
        <p className="muted">{t("bu.supersededHelp")}</p>
      ) : null}
      <ProblemMessage error={error} />
    </section>
  );
}

function Trail({ budgetId }: { budgetId: string }) {
  const { t } = useI18n();
  const events = useBudgetEvents(budgetId);
  return (
    <section aria-labelledby="bu-trail">
      <h3 id="bu-trail">{t("bu.trail")}</h3>
      {events.isPending ? <Loading /> : null}
      <ol className="trail">
        {(events.data ?? []).map((e) => (
          <li key={`${String(e.version_number)}-${String(e.seq)}`}>
            {t("bu.version")} {e.version_number} ·{" "}
            {t(`bu.event.${e.action}` as MessageKey)} · {e.actor_name} ·{" "}
            <time dateTime={e.at}>{e.at.slice(0, 16).replace("T", " ")}</time>
            {e.comment ? <> · “{e.comment}”</> : null}
          </li>
        ))}
      </ol>
    </section>
  );
}

function BudgetDetail({ budget }: { budget: Budget }) {
  const { t } = useI18n();
  const [chosen, setChosen] = useState<string | null>(null);
  const latest = budget.versions.at(-1);
  const versionId =
    chosen ??
    budget.open_version_id ??
    budget.current_version_id ??
    latest?.id ??
    null;
  const detail = useBudgetVersion(versionId);
  const tag = (id: string) =>
    [
      id === budget.original_version_id ? t("bu.original") : "",
      id === budget.current_version_id ? t("bu.current") : "",
    ]
      .filter(Boolean)
      .join(", ");
  return (
    <section className="card" aria-labelledby="bu-detail">
      <h2 id="bu-detail">{budget.name}</h2>
      <div role="group" aria-label={t("bu.versions")} className="chips">
        {budget.versions.map((v) => (
          <button
            key={v.id}
            type="button"
            aria-pressed={v.id === versionId}
            onClick={() => setChosen(v.id)}
          >
            {t("bu.version")} {v.number} · {t(`bu.status.${v.status}`)}
            {tag(v.id) ? ` (${tag(v.id)})` : ""}
          </button>
        ))}
      </div>
      {detail.isPending ? <Loading /> : null}
      <ProblemMessage error={detail.error} />
      {detail.data ? (
        <>
          {detail.data.reason ? (
            <p>
              {t("bu.reason")}: {detail.data.reason}
            </p>
          ) : null}
          {detail.data.status === "DRAFT" ? (
            <LineEditor key={detail.data.id} detail={detail.data} />
          ) : (
            <LineTable detail={detail.data} />
          )}
          <VersionActions detail={detail.data} />
        </>
      ) : null}
      <Trail budgetId={budget.id} />
    </section>
  );
}

function CreateBudget({ fiscalYearId }: { fiscalYearId: string }) {
  const { t } = useI18n();
  const { create } = useBudgetMutations();
  const dimensions = useDimensions();
  const [name, setName] = useState("");
  const [kind, setKind] = useState<BudgetKind>("ANNUAL");
  const [value, setValue] = useState("");
  const kinds =
    kind === "PROJECT" ? ["PROJECT"] : ["DEPARTMENT", "COST_CENTRE"];
  const options = (dimensions.data ?? [])
    .filter((d) => kinds.includes(d.kind))
    .flatMap((d) =>
      d.values.map((v) => ({ id: v.id, label: `${d.code}: ${v.name}` })),
    );
  return (
    <form
      className="form inline"
      onSubmit={(e) => {
        e.preventDefault();
        create.mutate(
          {
            name,
            fiscal_year_id: fiscalYearId,
            kind,
            dimension_value_id: kind === "ANNUAL" ? null : value || null,
          },
          { onSuccess: () => setName("") },
        );
      }}
    >
      <label>
        {t("bu.name")}
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          maxLength={120}
          required
        />
      </label>
      <label>
        {t("bu.kind")}
        <select
          value={kind}
          onChange={(e) => setKind(e.target.value as BudgetKind)}
        >
          {(["ANNUAL", "DEPARTMENTAL", "PROJECT"] as const).map((k) => (
            <option key={k} value={k}>
              {t(`bu.kind.${k}`)}
            </option>
          ))}
        </select>
      </label>
      {kind === "ANNUAL" ? null : (
        <label>
          {t("bu.scope")}
          <select
            value={value}
            onChange={(e) => setValue(e.target.value)}
            required
          >
            <option value="">{t("bu.choose")}</option>
            {options.map((o) => (
              <option key={o.id} value={o.id}>
                {o.label}
              </option>
            ))}
          </select>
        </label>
      )}
      <button
        type="submit"
        className="primary"
        disabled={create.isPending || !fiscalYearId}
      >
        {t("bu.create")}
      </button>
      <ProblemMessage error={create.error} />
    </form>
  );
}

function SodSetting() {
  const { t } = useI18n();
  const settings = useBudgetSettings();
  const { saveSettings } = useBudgetMutations();
  if (!settings.data) return null;
  return (
    <div className="form inline">
      <label className="checkbox">
        <input
          type="checkbox"
          checked={
            saveSettings.isPending
              ? saveSettings.variables
              : settings.data.sod_required
          }
          disabled={saveSettings.isPending}
          onChange={(e) => saveSettings.mutate(e.target.checked)}
        />{" "}
        {t("bu.sod")}
      </label>
      <ProblemMessage error={saveSettings.error} />
    </div>
  );
}

/** Budgets (M4-1): versions, approval with segregation of duties, revisions, approval trail. */
export function BudgetsPage() {
  const { t } = useI18n();
  const years = useFiscalYears();
  const [yearId, setYearId] = useState("");
  const fiscalYearId = yearId || years.data?.at(-1)?.id || "";
  const budgets = useBudgets(fiscalYearId);
  const [selected, setSelected] = useState<string | null>(null);
  const names = useNames();
  const budget = budgets.data?.find((b) => b.id === selected) ?? null;
  return (
    <Page title={t("bu.title")}>
      <p className="muted">{t("bu.help")}</p>
      <div className="form inline">
        <label>
          {t("bu.fiscalYear")}
          <select
            value={fiscalYearId}
            onChange={(e) => setYearId(e.target.value)}
          >
            {(years.data ?? []).map((y) => (
              <option key={y.id} value={y.id}>
                {y.name}
              </option>
            ))}
          </select>
        </label>
      </div>
      <SodSetting />
      <CreateBudget fiscalYearId={fiscalYearId} />
      {budgets.isPending ? <Loading /> : null}
      <ProblemMessage error={budgets.error} />
      {budgets.data?.length === 0 ? <p>{t("bu.none")}</p> : null}
      {budgets.data?.length ? (
        <div className="table-scroll">
          <table className="grid">
            <caption>{t("bu.list")}</caption>
            <thead>
              <tr>
                <th scope="col">{t("bu.name")}</th>
                <th scope="col">{t("bu.kind")}</th>
                <th scope="col">{t("bu.versions")}</th>
              </tr>
            </thead>
            <tbody>
              {budgets.data.map((b) => (
                <tr key={b.id}>
                  <th scope="row">
                    <button
                      type="button"
                      className="link"
                      aria-pressed={b.id === selected}
                      onClick={() => setSelected(b.id)}
                    >
                      {b.name}
                    </button>
                  </th>
                  <td>
                    {t(`bu.kind.${b.kind}`)}
                    {b.dimension_value_id
                      ? ` · ${names.value(b.dimension_value_id)}`
                      : ""}
                  </td>
                  <td>
                    {b.versions
                      .map(
                        (v) =>
                          `${t("bu.version")} ${String(v.number)}: ${t(`bu.status.${v.status}`)}`,
                      )
                      .join("; ")}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
      {budget ? <BudgetDetail key={budget.id} budget={budget} /> : null}
    </Page>
  );
}
