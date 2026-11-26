// Bring your books in (R-2, #245): three steps, each with its template (Excel or CSV). A file is
// first checked (every problem by row; nothing is kept), then imported. The chart and the
// customers and suppliers are created directly; the opening balances, with the open invoices
// behind the receivables and payables, become one draft entry approved and posted as usual.
import { useState } from "react";
import { Link } from "react-router";
import { useAccounts, useScope } from "../api/hooks";
import type { Account } from "../api/types";
import {
  type ImportKind,
  type ImportOutcome,
  type TemplateKind,
  templateUrl,
  useImport,
  useImportPresets,
} from "../api/imports";
import { Page, ProblemMessage } from "../components/common";
import { useI18n } from "../i18n/I18n";
import type { MessageKey } from "../i18n/messages";
import { formatAmount } from "../money";

function Templates({ kinds }: { kinds: TemplateKind[] }) {
  const { t } = useI18n();
  const { base } = useScope();
  return (
    <p className="muted">
      {t("imp.templates")}{" "}
      {kinds.map((kind) => (
        <span key={kind}>
          {t(`imp.template.${kind}` as MessageKey)}:{" "}
          <a href={templateUrl(base, kind, "xlsx")} download>
            Excel
          </a>{" "}
          ·{" "}
          <a href={templateUrl(base, kind, "csv")} download>
            CSV
          </a>{" "}
        </span>
      ))}
    </p>
  );
}

function Outcome({ outcome }: { outcome: ImportOutcome }) {
  const { t, locale } = useI18n();
  const { slug, entityId } = useScope();
  const clean = outcome.problems.length === 0;
  const created = outcome.accounts.length || outcome.counterparties.length;
  return (
    <div className="stack">
      {outcome.committed ? (
        <p className="notice" role="status">
          {t("imp.done")}
          {outcome.entry_id ? (
            <>
              {" "}
              <Link to={`/w/${slug}/e/${entityId}/entries/${outcome.entry_id}`}>
                {t("imp.openEntry")}
              </Link>
            </>
          ) : null}
        </p>
      ) : clean ? (
        <p className="notice" role="status">
          {t("imp.ready")}
        </p>
      ) : (
        <p className="notice warn" role="alert">
          {t("imp.problems").replace("{n}", String(outcome.problems.length))}
        </p>
      )}
      {outcome.warnings.map((w) => (
        <p key={w} className="notice warn">
          {w}
        </p>
      ))}
      {!clean ? (
        <div className="table-scroll">
          <table aria-label={t("imp.problemTable")}>
            <thead>
              <tr>
                <th scope="col">{t("imp.file")}</th>
                <th scope="col">{t("imp.row")}</th>
                <th scope="col">{t("imp.column")}</th>
                <th scope="col">{t("imp.message")}</th>
              </tr>
            </thead>
            <tbody>
              {outcome.problems.map((p, i) => (
                <tr key={`${p.file}-${p.row}-${p.column}-${i}`}>
                  <td>{p.file}</td>
                  <td>{p.row || "—"}</td>
                  <td>{p.column || "—"}</td>
                  <td>{p.message}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
      {created || outcome.skipped.length ? (
        <p className="muted">
          {t("imp.summary")
            .replace(
              "{created}",
              String(outcome.accounts.length + outcome.counterparties.length),
            )
            .replace("{skipped}", String(outcome.skipped.length))}
        </p>
      ) : null}
      {outcome.lines.length ? (
        <div className="table-scroll">
          <table aria-label={t("imp.lineTable")}>
            <thead>
              <tr>
                <th scope="col">{t("imp.account")}</th>
                <th scope="col">{t("imp.party")}</th>
                <th scope="col">{t("imp.reference")}</th>
                <th scope="col" className="num">
                  {t("imp.debit")}
                </th>
                <th scope="col" className="num">
                  {t("imp.credit")}
                </th>
              </tr>
            </thead>
            <tbody>
              {outcome.lines.map((ln, i) => (
                <tr key={`${ln.account_code}-${ln.reference}-${i}`}>
                  <td>
                    {ln.account_code} {ln.account_name}
                  </td>
                  <td>{ln.counterparty_code}</td>
                  <td>{ln.reference}</td>
                  <td className="num">
                    {Number(ln.debit) ? formatAmount(ln.debit, locale) : ""}
                  </td>
                  <td className="num">
                    {Number(ln.credit) ? formatAmount(ln.credit, locale) : ""}
                  </td>
                </tr>
              ))}
            </tbody>
            <tfoot>
              <tr>
                <th scope="row" colSpan={3}>
                  {t("imp.total")}
                </th>
                <td className="num">
                  {formatAmount(outcome.total_debit, locale)}
                </td>
                <td className="num">
                  {formatAmount(outcome.total_credit, locale)}
                </td>
              </tr>
            </tfoot>
          </table>
        </div>
      ) : null}
    </div>
  );
}

function FileStep({
  kind,
  title,
  help,
}: {
  kind: Exclude<ImportKind, "opening-balances">;
  title: MessageKey;
  help: MessageKey;
}) {
  const { t } = useI18n();
  const run = useImport(kind);
  const [file, setFile] = useState<File | null>(null);
  const checked = run.data && !run.data.committed ? run.data : null;
  return (
    <section className="card stack" aria-labelledby={`imp-${kind}`}>
      <h2 id={`imp-${kind}`}>{t(title)}</h2>
      <p className="muted">{t(help)}</p>
      <Templates kinds={[kind]} />
      <label>
        {t("imp.chooseFile")}
        <input
          type="file"
          accept=".xlsx,.csv,text/csv"
          onChange={(e) => {
            setFile(e.target.files?.[0] ?? null);
            run.reset();
          }}
        />
      </label>
      <div className="row">
        <button
          type="button"
          disabled={!file || run.isPending}
          onClick={() => file && run.mutate({ file, commit: false })}
        >
          {t("imp.check")}
        </button>
        <button
          type="button"
          className="primary"
          disabled={
            !file || !checked || checked.problems.length > 0 || run.isPending
          }
          onClick={() => file && run.mutate({ file, commit: true })}
        >
          {t("imp.import")}
        </button>
      </div>
      <ProblemMessage error={run.error} />
      {run.data ? <Outcome outcome={run.data} /> : null}
    </section>
  );
}

function FileInput({
  label,
  onFile,
}: {
  label: MessageKey;
  onFile: (file: File | null) => void;
}) {
  const { t } = useI18n();
  return (
    <label>
      {t(label)}
      <input
        type="file"
        accept=".xlsx,.csv,text/csv"
        onChange={(e) => onFile(e.target.files?.[0] ?? null)}
      />
    </label>
  );
}

function AccountMapping({
  outcome,
  accounts,
  mapping,
  onChange,
}: {
  outcome: ImportOutcome | undefined;
  accounts: Account[];
  mapping: Record<string, string>;
  onChange: (mapping: Record<string, string>) => void;
}) {
  const { t } = useI18n();
  if (!outcome?.unknown_accounts.length) {
    return null;
  }
  return (
    <fieldset className="stack">
      <legend>{t("imp.map.title")}</legend>
      <p className="muted">{t("imp.map.help")}</p>
      {outcome.unknown_accounts.map((u) => (
        <label key={u.code}>
          {u.code === u.name ? u.code : `${u.code} ${u.name}`}
          <select
            value={mapping[u.code] ?? ""}
            onChange={(e) => onChange({ ...mapping, [u.code]: e.target.value })}
          >
            <option value="">{t("imp.map.choose")}</option>
            {accounts.map((a) => (
              <option key={a.id} value={a.code}>
                {a.code} {a.name}
              </option>
            ))}
          </select>
        </label>
      ))}
    </fieldset>
  );
}

function PriorStep() {
  const { t } = useI18n();
  const run = useImport("prior-year");
  const accounts = useAccounts();
  const [file, setFile] = useState<File | null>(null);
  const [mode, setMode] = useState<"year_to_date" | "month">("year_to_date");
  const [mapping, setMapping] = useState<Record<string, string>>({});
  const active = (accounts.data ?? []).filter((a) => a.is_postable);
  const checked = run.data && !run.data.committed ? run.data : null;
  const request = (commit: boolean) =>
    file &&
    run.mutate({ file, accountMap: mapping, profitAndLoss: mode, commit });
  return (
    <section className="card stack" aria-labelledby="imp-prior">
      <h2 id="imp-prior">{t("imp.prior.title")}</h2>
      <p className="muted">{t("imp.prior.help")}</p>
      <Templates kinds={["prior-year"]} />
      <label>
        {t("imp.prior.mode")}
        <select
          value={mode}
          onChange={(e) => {
            setMode(e.target.value as "year_to_date" | "month");
            run.reset();
          }}
        >
          <option value="year_to_date">{t("imp.prior.ytd")}</option>
          <option value="month">{t("imp.prior.month")}</option>
        </select>
      </label>
      <FileInput
        label="imp.chooseFile"
        onFile={(f) => {
          setFile(f);
          run.reset();
        }}
      />
      <AccountMapping
        outcome={run.data}
        accounts={active}
        mapping={mapping}
        onChange={setMapping}
      />
      <div className="row">
        <button
          type="button"
          disabled={!file || run.isPending}
          onClick={() => request(false)}
        >
          {t("imp.check")}
        </button>
        <button
          type="button"
          className="primary"
          disabled={
            !file || !checked || checked.problems.length > 0 || run.isPending
          }
          onClick={() => request(true)}
        >
          {t("imp.import")}
        </button>
      </div>
      <ProblemMessage error={run.error} />
      {run.data?.months.length ? (
        <p className="muted">
          {t("imp.prior.summary")
            .replace("{months}", run.data.months.join(", "))
            .replace("{accounts}", String(run.data.accounts.length))}
        </p>
      ) : null}
      {run.data ? <Outcome outcome={run.data} /> : null}
    </section>
  );
}

type Files = Record<"tb" | "items" | "ar" | "ap", File | null>;

function OpeningStep() {
  const { t } = useI18n();
  const run = useImport("opening-balances");
  const accounts = useAccounts();
  const presets = useImportPresets();
  const [files, setFiles] = useState<Files>({
    tb: null,
    items: null,
    ar: null,
    ap: null,
  });
  const [asOf, setAsOf] = useState(`${new Date().getFullYear()}-01-01`);
  const [source, setSource] = useState("");
  const [dateOrder, setDateOrder] = useState<"day" | "month">("day");
  const [results, setResults] = useState("");
  const [create, setCreate] = useState(false);
  const [mapping, setMapping] = useState<Record<string, string>>({});
  const active = (accounts.data ?? []).filter(
    (a) => a.is_postable && a.status === "ACTIVE",
  );
  const preset = presets.data?.find((p) => p.key === source);
  const checked = run.data && !run.data.committed ? run.data : null;
  const change = (apply: () => void) => {
    apply();
    run.reset();
  };
  const setFile = (key: keyof Files) => (file: File | null) =>
    change(() => setFiles((f) => ({ ...f, [key]: file })));
  const request = (commit: boolean) =>
    files.tb &&
    run.mutate({
      file: files.tb,
      openItems: files.items,
      agedReceivables: files.ar,
      agedPayables: files.ap,
      asOf,
      accountMap: mapping,
      resultsAccount: results,
      dateOrder,
      createCounterparties: create,
      commit,
    });
  return (
    <section className="card stack" aria-labelledby="imp-opening">
      <h2 id="imp-opening">{t("imp.opening.title")}</h2>
      <p className="muted">{t("imp.opening.help")}</p>
      <Templates kinds={["opening-balances", "open-items"]} />
      <label>
        {t("imp.source")}
        <select
          value={source}
          onChange={(e) => {
            const next = presets.data?.find((p) => p.key === e.target.value);
            change(() => {
              setSource(e.target.value);
              setDateOrder(next && !next.day_first ? "month" : "day");
            });
          }}
        >
          <option value="">{t("imp.source.own")}</option>
          {presets.data?.map((p) => (
            <option key={p.key} value={p.key}>
              {p.name}
            </option>
          ))}
        </select>
      </label>
      {preset ? (
        <p className="notice warn">
          {t("imp.source.toConfirm").replace("{name}", preset.name)}{" "}
          {preset.note}
        </p>
      ) : null}
      <label>
        {t("imp.asOf")}
        <input
          type="date"
          value={asOf}
          required
          onChange={(e) => change(() => setAsOf(e.target.value))}
        />
      </label>
      <label>
        {t("imp.dateOrder")}
        <select
          value={dateOrder}
          onChange={(e) =>
            change(() => setDateOrder(e.target.value as "day" | "month"))
          }
        >
          <option value="day">{t("imp.dateOrder.day")}</option>
          <option value="month">{t("imp.dateOrder.month")}</option>
        </select>
      </label>
      <FileInput label="imp.tbFile" onFile={setFile("tb")} />
      <FileInput label="imp.itemsFile" onFile={setFile("items")} />
      <FileInput label="imp.arFile" onFile={setFile("ar")} />
      <FileInput label="imp.apFile" onFile={setFile("ap")} />
      <label>
        {t("imp.results")}
        <select
          value={results}
          onChange={(e) => change(() => setResults(e.target.value))}
        >
          <option value="">{t("imp.results.keep")}</option>
          {active
            .filter((a) => a.type === "EQUITY")
            .map((a) => (
              <option key={a.id} value={a.code}>
                {a.code} {a.name}
              </option>
            ))}
        </select>
      </label>
      <AccountMapping
        outcome={run.data}
        accounts={active}
        mapping={mapping}
        onChange={setMapping}
      />
      {run.data?.unknown_counterparties.length || create ? (
        <fieldset className="stack">
          <legend>{t("imp.parties.unknown")}</legend>
          <ul>
            {run.data?.unknown_counterparties.map((u) => (
              <li key={`${u.side}-${u.name}`}>{u.name}</li>
            ))}
          </ul>
          <label className="inline">
            <input
              type="checkbox"
              checked={create}
              onChange={(e) => change(() => setCreate(e.target.checked))}
            />
            {t("imp.parties.create")}
          </label>
        </fieldset>
      ) : null}
      <div className="row">
        <button
          type="button"
          disabled={!files.tb || !asOf || run.isPending}
          onClick={() => request(false)}
        >
          {t("imp.check")}
        </button>
        <button
          type="button"
          className="primary"
          disabled={
            !files.tb ||
            !checked ||
            checked.problems.length > 0 ||
            run.isPending
          }
          onClick={() => request(true)}
        >
          {t("imp.createDraft")}
        </button>
      </div>
      <ProblemMessage error={run.error} />
      {run.data ? <Outcome outcome={run.data} /> : null}
    </section>
  );
}

export function ImportPage() {
  const { t } = useI18n();
  return (
    <Page title={t("imp.title")}>
      <p className="muted">{t("imp.help")}</p>
      <FileStep kind="chart" title="imp.chart.title" help="imp.chart.help" />
      <FileStep
        kind="counterparties"
        title="imp.parties.title"
        help="imp.parties.help"
      />
      <OpeningStep />
      <PriorStep />
    </Page>
  );
}
