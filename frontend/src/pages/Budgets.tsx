import Decimal from "decimal.js";
import { Fragment, useMemo, useState } from "react";
import {
  type Budget,
  type BudgetKind,
  type BudgetVersionDetail,
  type LineIn,
  type PhasingMethod,
  type PhasingParams,
  useBudgetEvents,
  useBudgetMembers,
  useBudgetOwners,
  useExportUrl,
  useVariance,
  useVarianceMutations,
  type VarianceComparison,
  type VarianceRow,
  type VarianceView,
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
  method: PhasingMethod;
  annual: string;
  weights: string;
  quantity: string;
  rate: string;
  phasingNote: string;
}

const METHODS: PhasingMethod[] = [
  "MANUAL",
  "EVEN",
  "SEASONAL",
  "PROFILE",
  "DRIVER",
];

function params(r: Row): PhasingParams | null {
  switch (r.method) {
    case "MANUAL":
      return null;
    case "PROFILE":
      return {
        annual: r.annual.trim(),
        weights: r.weights.split(/[\s,;]+/).filter(Boolean),
      };
    case "DRIVER":
      return { quantity: r.quantity.trim(), rate: r.rate.trim() };
    default:
      return { annual: r.annual.trim() };
  }
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

function PhasingRow({
  row,
  span,
  onChange,
  onPreview,
  pending,
}: {
  row: Row;
  span: number;
  onChange: (patch: Partial<Row>) => void;
  onPreview: () => void;
  pending: boolean;
}) {
  const { t } = useI18n();
  const field = (
    key: "annual" | "weights" | "quantity" | "rate",
    label: MessageKey,
  ) => (
    <label>
      {t(label)}
      <input
        value={row[key]}
        onChange={(e) => onChange({ [key]: e.target.value })}
        inputMode={key === "weights" ? "text" : "decimal"}
        size={key === "weights" ? 30 : 12}
      />
    </label>
  );
  return (
    <tr className="phasing-row">
      <td colSpan={span}>
        <div className="form inline">
          {row.method === "DRIVER" ? (
            <>
              {field("quantity", "bu.quantity")}
              {field("rate", "bu.rate")}
            </>
          ) : (
            field("annual", "bu.annual")
          )}
          {row.method === "PROFILE" ? field("weights", "bu.weights") : null}
          <button type="button" onClick={onPreview} disabled={pending}>
            {t("bu.phase")}
          </button>
          {row.phasingNote ? (
            <span className="muted">{row.phasingNote}</span>
          ) : null}
        </div>
      </td>
    </tr>
  );
}

function LineEditor({ detail }: { detail: BudgetVersionDetail }) {
  const { t, locale } = useI18n();
  const names = useNames();
  const { saveLines, preview } = useBudgetMutations();
  const [rows, setRows] = useState<Row[]>(() =>
    detail.lines.map((l) => ({
      key: l.id,
      taxonomy_code: l.taxonomy_code,
      account_id: l.account_id,
      dimension_value_id: l.dimension_value_id,
      note: l.note,
      amounts: [...l.amounts],
      method: l.method,
      annual: l.method_params.annual ?? "",
      weights: (l.method_params.weights ?? []).join(" "),
      quantity: l.method_params.quantity ?? "",
      rate: l.method_params.rate ?? "",
      phasingNote: l.phasing_note,
    })),
  );
  const [subject, setSubject] = useState("");
  const [dimension, setDimension] = useState("");
  const months = detail.months;
  const blank = () => months.map(() => "0.00");
  const invalid = rows.some(
    (r) =>
      r.method === "MANUAL" && r.amounts.some((a) => !SIGNED.test(a.trim())),
  );
  const patch = (i: number, change: Partial<Row>) =>
    setRows((rs) => rs.map((r, j) => (j === i ? { ...r, ...change } : r)));
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
        key: `new-${String(rs.length)}-${subject}-${dimension}`,
        taxonomy_code: kind === "t" ? id : null,
        account_id: kind === "a" ? id : null,
        dimension_value_id: dimension || null,
        note: "",
        amounts: blank(),
        method: "MANUAL",
        annual: "",
        weights: "",
        quantity: "",
        rate: "",
        phasingNote: "",
      },
    ]);
    setSubject("");
  };
  const runPreview = (i: number) => {
    const r = rows[i];
    const body = r ? params(r) : null;
    if (!r || !body || r.method === "MANUAL") return;
    preview.mutate(
      {
        versionId: detail.id,
        body: {
          taxonomy_code: r.taxonomy_code,
          account_id: r.account_id,
          method: r.method,
          params: body,
        },
      },
      {
        onSuccess: (res) =>
          patch(i, { amounts: res.amounts, phasingNote: res.note }),
      },
    );
  };
  const payload = (): LineIn[] =>
    rows.map((r) => ({
      taxonomy_code: r.taxonomy_code,
      account_id: r.account_id,
      dimension_value_id: r.dimension_value_id,
      note: r.note,
      method: r.method,
      params: params(r),
      amounts:
        r.method === "MANUAL"
          ? Object.fromEntries(
              months.map((m, k) => [m, r.amounts[k]?.trim() ?? "0"]),
            )
          : {},
    }));
  const totals = months.map((_, k) =>
    rows.reduce(
      (acc, r) => acc.plus(amountOf(r.amounts[k] ?? "")),
      new Decimal(0),
    ),
  );
  const span = months.length + 4;
  return (
    <section aria-labelledby="bu-lines">
      <h3 id="bu-lines">{t("bu.lines")}</h3>
      <p className="muted">{t("bu.linesHelp")}</p>
      <p className="muted">{t("bu.phasingHelp")}</p>
      <div className="table-scroll">
        <table className="grid budget-grid">
          <caption className="visually-hidden">{t("bu.lines")}</caption>
          <thead>
            <tr>
              <th scope="col">{t("bu.line")}</th>
              <th scope="col">{t("bu.method")}</th>
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
                <Fragment key={r.key}>
                  <tr>
                    <th scope="row">
                      {label}
                      {r.dimension_value_id ? (
                        <span className="muted">
                          {" "}
                          · {names.value(r.dimension_value_id)}
                        </span>
                      ) : null}
                    </th>
                    <td>
                      <select
                        aria-label={`${t("bu.method")} ${label}`}
                        value={r.method}
                        onChange={(e) =>
                          patch(i, {
                            method: e.target.value as PhasingMethod,
                            phasingNote: "",
                          })
                        }
                      >
                        {METHODS.map((m) => (
                          <option key={m} value={m}>
                            {t(`bu.method.${m}`)}
                          </option>
                        ))}
                      </select>
                    </td>
                    {months.map((m, k) => (
                      <td key={m}>
                        {r.method === "MANUAL" ? (
                          <input
                            className="num"
                            inputMode="decimal"
                            aria-label={`${label} ${monthLabel(m, locale)}`}
                            aria-invalid={
                              !SIGNED.test((r.amounts[k] ?? "").trim())
                            }
                            value={r.amounts[k] ?? ""}
                            onChange={(e) => set(i, k, e.target.value)}
                            size={9}
                          />
                        ) : (
                          <span className="num">
                            {formatAmount(r.amounts[k] ?? "0", locale)}
                          </span>
                        )}
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
                  {r.method === "MANUAL" ? null : (
                    <PhasingRow
                      row={r}
                      span={span}
                      onChange={(change) => patch(i, change)}
                      onPreview={() => runPreview(i)}
                      pending={preview.isPending}
                    />
                  )}
                </Fragment>
              );
            })}
          </tbody>
          <tfoot>
            <tr>
              <th scope="row">{t("bu.total")}</th>
              <td />
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
      <ProblemMessage error={preview.error} />
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
        <label>
          {t("bu.dimension")}
          <select
            value={dimension}
            onChange={(e) => setDimension(e.target.value)}
          >
            <option value="">{t("bu.noDimension")}</option>
            {names.dimensions.flatMap((d) =>
              d.values.map((v) => (
                <option key={v.id} value={v.id}>
                  {d.code}: {v.name}
                </option>
              )),
            )}
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
            saveLines.mutate(
              { versionId: detail.id, lines: payload() },
              {
                onSuccess: (saved) =>
                  setRows((rs) =>
                    rs.map((r, i) => {
                      const line = saved.lines[i];
                      return line
                        ? {
                            ...r,
                            amounts: [...line.amounts],
                            phasingNote: line.phasing_note,
                          }
                        : r;
                    }),
                  ),
              },
            )
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
      <ImportPanel detail={detail} />
    </section>
  );
}

function ImportPanel({ detail }: { detail: BudgetVersionDetail }) {
  const { t, locale } = useI18n();
  const { importFile } = useBudgetMutations();
  const [file, setFile] = useState<File | null>(null);
  const result = importFile.data;
  const run = (apply: boolean) => {
    if (!file) return;
    importFile.mutate({
      versionId: detail.id,
      file,
      apply,
      expectedHash: apply && result ? result.draft_hash : "",
    });
  };
  return (
    <section aria-labelledby="bu-import" className="import-panel">
      <h3 id="bu-import">{t("bu.import")}</h3>
      <p className="muted">{t("bu.importHelp")}</p>
      <ExportLink versionId={detail.id} />
      <div className="form inline">
        <label>
          {t("bu.file")}
          <input
            type="file"
            accept=".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            onChange={(e) => {
              setFile(e.target.files?.[0] ?? null);
              importFile.reset();
            }}
          />
        </label>
        <button
          type="button"
          disabled={!file || importFile.isPending}
          onClick={() => run(false)}
        >
          {t("bu.importPreview")}
        </button>
        {result && !result.applied && result.problems.length === 0 ? (
          <button
            type="button"
            className="primary"
            disabled={importFile.isPending}
            onClick={() => run(true)}
          >
            {t("bu.importApply")}
          </button>
        ) : null}
      </div>
      <ProblemMessage error={importFile.error} />
      {result?.applied ? <p role="status">{t("bu.imported")}</p> : null}
      {result && result.problems.length ? (
        <div className="table-scroll">
          <table className="grid">
            <caption>{t("bu.importProblems")}</caption>
            <thead>
              <tr>
                <th scope="col">{t("bu.row")}</th>
                <th scope="col">{t("bu.column")}</th>
                <th scope="col">{t("bu.problem")}</th>
              </tr>
            </thead>
            <tbody>
              {result.problems.map((p) => (
                <tr key={`${String(p.row)}-${p.column}-${p.message}`}>
                  <td>{p.row || "—"}</td>
                  <td>{p.column || "—"}</td>
                  <td>{p.message}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
      {result && !result.problems.length && !result.applied ? (
        <div className="table-scroll">
          <table className="grid">
            <caption>
              {t("bu.importChanges")} ({t("bu.unchanged")}: {result.unchanged})
            </caption>
            <thead>
              <tr>
                <th scope="col">{t("bu.line")}</th>
                <th scope="col">{t("bu.change")}</th>
                <th scope="col" className="num">
                  {t("bu.before")}
                </th>
                <th scope="col" className="num">
                  {t("bu.after")}
                </th>
              </tr>
            </thead>
            <tbody>
              {result.changes.map((c) => (
                <tr key={`${c.kind}-${c.line}`}>
                  <td>{c.line}</td>
                  <td>{t(`bu.change.${c.kind}`)}</td>
                  <td className="num">{formatAmount(c.before, locale)}</td>
                  <td className="num">{formatAmount(c.after, locale)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
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

const VIEWS: VarianceView[] = ["MONTH", "QTD", "YTD", "FULL_YEAR"];
const COMPARISONS: VarianceComparison[] = [
  "ACTUAL_VS_BUDGET",
  "ACTUAL_VS_PRIOR_YEAR",
  "CURRENT_VS_ORIGINAL",
];

function ExplainForm({
  row,
  onSave,
  pending,
}: {
  row: VarianceRow;
  onSave: (comment: string) => void;
  pending: boolean;
}) {
  const { t } = useI18n();
  const [text, setText] = useState("");
  return (
    <form
      className="inline-form"
      onSubmit={(e) => {
        e.preventDefault();
        onSave(text);
      }}
    >
      <label>
        <span className="visually-hidden">
          {t("va.explanationFor")} {row.taxonomy_code ?? row.account_id}
        </span>
        <input
          value={text}
          onChange={(e) => setText(e.target.value)}
          maxLength={1000}
          placeholder={row.explanation ? t("va.change") : t("va.why")}
          required
        />
      </label>
      <button type="submit" disabled={pending || !text.trim()}>
        {t("va.save")}
      </button>
    </form>
  );
}

function VariancePanel({ detail }: { detail: BudgetVersionDetail }) {
  const { t, locale } = useI18n();
  const names = useNames();
  const today = new Date().toISOString().slice(0, 8) + "01";
  const fallback = detail.months.includes(today)
    ? today
    : (detail.months.at(-1) ?? "");
  const [month, setMonth] = useState(fallback);
  const [view, setView] = useState<VarianceView>("MONTH");
  const [comparison, setComparison] =
    useState<VarianceComparison>("ACTUAL_VS_BUDGET");
  const result = useVariance(detail.id, month, view, comparison);
  const { explain, review } = useVarianceMutations();
  const current = detail.status === "APPROVED" || detail.status === "LOCKED";
  const data = result.data;
  const missing = data
    ? data.rows.filter((r) => r.requires_explanation && !r.explanation)
    : [];
  const label = (r: VarianceRow) =>
    names.subject(r) +
    (r.dimension_value_id ? ` · ${names.value(r.dimension_value_id)}` : "");
  return (
    <section aria-labelledby="bu-variance">
      <h3 id="bu-variance">{t("va.title")}</h3>
      <p className="muted">{t("va.help")}</p>
      <div className="form inline">
        <label>
          {t("va.month")}
          <select value={month} onChange={(e) => setMonth(e.target.value)}>
            {detail.months.map((m) => (
              <option key={m} value={m}>
                {m.slice(0, 7)}
              </option>
            ))}
          </select>
        </label>
        <label>
          {t("va.view")}
          <select
            value={view}
            onChange={(e) => setView(e.target.value as VarianceView)}
          >
            {VIEWS.map((v) => (
              <option key={v} value={v}>
                {t(`va.view.${v}`)}
              </option>
            ))}
          </select>
        </label>
        <label>
          {t("va.comparison")}
          <select
            value={comparison}
            onChange={(e) =>
              setComparison(e.target.value as VarianceComparison)
            }
          >
            {COMPARISONS.map((c) => (
              <option key={c} value={c}>
                {t(`va.cmp.${c}`)}
              </option>
            ))}
          </select>
        </label>
      </div>
      {result.isPending ? <Loading /> : null}
      <ProblemMessage error={result.error ?? explain.error ?? review.error} />
      {data ? (
        <>
          <p className="muted">
            {t("va.basis")} {data.actuals_watermark}
            {data.cutover
              ? ` · ${t("va.blended")} ${data.cutover.slice(0, 7)}`
              : ""}{" "}
            · {t("va.threshold")}{" "}
            {formatAmount(data.explain_above_amount, locale)} /{" "}
            {data.explain_above_percent}%
          </p>
          {data.unposted_entries ? (
            <p className="notice warn" role="status">
              {t("va.unposted")}: {data.unposted_entries}
            </p>
          ) : null}
          <div className="table-scroll">
            <table className="grid">
              <caption>
                {t(`va.cmp.${data.comparison}`)} · {t(`va.view.${data.view}`)}
              </caption>
              <thead>
                <tr>
                  <th scope="col">{t("bu.line")}</th>
                  <th scope="col" className="num">
                    {t(`va.subject.${data.comparison}`)}
                  </th>
                  <th scope="col" className="num">
                    {t(`va.compared.${data.comparison}`)}
                  </th>
                  <th scope="col" className="num">
                    {t("va.variance")}
                  </th>
                  <th scope="col" className="num">
                    %
                  </th>
                  <th scope="col">{t("va.effect")}</th>
                  <th scope="col">{t("va.explanation")}</th>
                </tr>
              </thead>
              <tbody>
                {data.rows.map((r) => (
                  <tr
                    key={`${r.line_id ?? "orig"}-${r.taxonomy_code ?? r.account_id ?? ""}`}
                  >
                    <th scope="row">{label(r)}</th>
                    <td className="num">
                      {formatAmount(r.subject, locale)}{" "}
                      <span className="muted">
                        ({t(`nature.${r.subject_nature}`)})
                      </span>
                    </td>
                    <td className="num">
                      {formatAmount(r.comparison, locale)}{" "}
                      <span className="muted">
                        ({t(`nature.${r.comparison_nature}`)})
                      </span>
                    </td>
                    <td className="num">{formatAmount(r.variance, locale)}</td>
                    <td className="num">{r.percent ?? t("va.nm")}</td>
                    <td>
                      {r.favourable === null
                        ? "—"
                        : r.favourable
                          ? t("va.favourable")
                          : t("va.unfavourable")}
                    </td>
                    <td>
                      {r.explanation ? (
                        <p>
                          “{r.explanation.comment}” ·{" "}
                          {r.explanation.author_name}
                        </p>
                      ) : r.requires_explanation ? (
                        <strong>{t("va.needed")}</strong>
                      ) : null}
                      {current &&
                      r.line_id &&
                      (r.requires_explanation || r.explanation) ? (
                        <ExplainForm
                          key={`${month}-${view}-${comparison}-${r.line_id}`}
                          row={r}
                          pending={explain.isPending}
                          onSave={(comment) => {
                            if (!r.line_id) return;
                            explain.mutate({
                              versionId: detail.id,
                              body: {
                                line_id: r.line_id,
                                month,
                                view,
                                comparison,
                                comment,
                              },
                            });
                          }}
                        />
                      ) : null}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {current ? (
            data.review ? (
              <p role="status">
                {t("va.reviewed")} {data.review.completed_by_name} ·{" "}
                {data.review.at.slice(0, 10)}
              </p>
            ) : (
              <p>
                <button
                  type="button"
                  disabled={review.isPending}
                  onClick={() => review.mutate({ versionId: detail.id, month })}
                >
                  {t("va.complete")} {month.slice(0, 7)}
                </button>{" "}
                {missing.length ? (
                  <span className="muted">
                    {t("va.missing")}: {missing.length}
                  </span>
                ) : null}
              </p>
            )
          ) : null}
        </>
      ) : null}
    </section>
  );
}

function OwnersPanel({ budget }: { budget: Budget }) {
  const { t } = useI18n();
  const owners = useBudgetOwners(budget.id);
  const members = useBudgetMembers(owners.isSuccess);
  const names = useNames();
  const { saveOwners } = useBudgetMutations();
  const [chosen, setChosen] = useState<Record<string, string> | null>(null);
  if (!owners.data || !members.data) return null;
  const current: Record<string, string> =
    chosen ??
    Object.fromEntries(
      owners.data.map((o) => [o.dimension_value_id, o.user_id]),
    );
  const values = names.dimensions
    .filter((d) => d.kind !== "CUSTOM")
    .flatMap((d) =>
      d.values.map((v) => ({ id: v.id, label: `${d.code}: ${v.name}` })),
    )
    .filter(
      (v) => !budget.dimension_value_id || v.id === budget.dimension_value_id,
    );
  if (!values.length) {
    return (
      <section aria-labelledby="bu-owners">
        <h3 id="bu-owners">{t("bu.owners")}</h3>
        <p className="muted">{t("bu.noDepartments")}</p>
      </section>
    );
  }
  return (
    <section aria-labelledby="bu-owners">
      <h3 id="bu-owners">{t("bu.owners")}</h3>
      <p className="muted">{t("bu.ownersHelp")}</p>
      <div className="form inline">
        {values.map((v) => (
          <label key={v.id}>
            {v.label}
            <select
              value={current[v.id] ?? ""}
              onChange={(e) =>
                setChosen({ ...current, [v.id]: e.target.value })
              }
            >
              <option value="">{t("bu.noOwner")}</option>
              {members.data.map((m) => (
                <option key={m.user_id} value={m.user_id}>
                  {m.name}
                </option>
              ))}
            </select>
          </label>
        ))}
        <button
          type="button"
          disabled={saveOwners.isPending}
          onClick={() =>
            saveOwners.mutate(
              {
                budgetId: budget.id,
                owners: Object.entries(current)
                  .filter(([, user]) => user)
                  .map(([dimension_value_id, user_id]) => ({
                    dimension_value_id,
                    user_id,
                  })),
              },
              { onSuccess: () => setChosen(null) },
            )
          }
        >
          {t("bu.saveOwners")}
        </button>
        {saveOwners.isSuccess ? (
          <span role="status">{t("bu.saved")}</span>
        ) : null}
      </div>
      <ProblemMessage error={saveOwners.error} />
    </section>
  );
}

function ExportLink({ versionId }: { versionId: string }) {
  const { t } = useI18n();
  return (
    <p>
      <a className="download" href={useExportUrl(versionId)} download>
        {t("bu.export")}
      </a>
    </p>
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
            <LineEditor key={`editor-${detail.data.id}`} detail={detail.data} />
          ) : (
            <LineTable detail={detail.data} />
          )}
          {detail.data.status === "DRAFT" ? null : (
            <ExportLink versionId={detail.data.id} />
          )}
          <VariancePanel
            key={`variance-${detail.data.id}`}
            detail={detail.data}
          />
          <VersionActions detail={detail.data} />
        </>
      ) : null}
      <OwnersPanel budget={budget} />
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
  // Shown at once when clicked; reverts if the server refuses the change.
  const [pending, setPending] = useState<boolean | null>(null);
  if (!settings.data) return null;
  return (
    <div className="form inline">
      <label className="checkbox">
        <input
          type="checkbox"
          checked={pending ?? settings.data.sod_required}
          onChange={(e) => {
            const value = e.target.checked;
            setPending(value);
            saveSettings.mutate(value, { onSettled: () => setPending(null) });
          }}
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
