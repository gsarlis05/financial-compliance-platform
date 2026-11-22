// Management report packs (M8-6 for M8-1 to M8-3): generate a pack whose figures are frozen,
// arrange its sections and comparison columns, write commentary and risks, send it for review,
// finalise it (never your own, except in a one-person workspace, where it is recorded as
// self-approved), start a new version, and export it to Excel or PDF.
import Decimal from "decimal.js";
import { type SyntheticEvent, useState } from "react";
import { useScope } from "../api/hooks";
import {
  COLUMN_KEYS,
  type Pack,
  type PackDetail,
  type Risk,
  SECTION_KEYS,
  type Section,
  type Table,
  packExportUrl,
  usePack,
  usePackMutations,
  usePackSections,
  usePacks,
} from "../api/packs";
import { Loading, Page, ProblemMessage } from "../components/common";
import { useI18n } from "../i18n/I18n";
import type { MessageKey } from "../i18n/messages";
import { formatAmount } from "../money";

const NUMBER = /^-?\d+(\.\d+)?$/;

/** A figure as the reader sees it: two decimals, and a percentage where the row holds ratios
 * shown as percentages (KPIs and goals). Text is shown as it is. */
export function cellText(
  value: string | null,
  locale: string,
  display?: string,
): string {
  if (value === null) return "—";
  if (!NUMBER.test(value)) return value;
  const n = new Decimal(value);
  return display === "percent"
    ? `${formatAmount(n.times(100).toFixed(2), locale)}%`
    : formatAmount(n.toFixed(2), locale);
}

function natureOf(table: Table, column: number): string | null {
  const found = new Set(
    table.rows.map((r) => r.cells[column]?.nature).filter(Boolean),
  );
  return found.size === 1 ? ([...found][0] as string) : null;
}

/** One table of a section: a header row, a nature row (what each column's figures are) and the
 * figures. Nature is written out, never shown by colour alone. */
function PackTable({ table }: { table: Table }) {
  const { t, locale } = useI18n();
  const el = locale === "el";
  const values = table.columns.slice(1);
  return (
    <div className="table-scroll">
      <table className="grid">
        <caption>{el ? table.caption_el : table.caption}</caption>
        <thead>
          <tr>
            {table.columns.map((c, i) => (
              <th key={c.key} scope="col" className={i ? "num" : undefined}>
                {el ? c.label_el : c.label}
              </th>
            ))}
          </tr>
          <tr className="nature-row">
            <th scope="row">{t("pk.nature")}</th>
            {values.map((c, i) => {
              const n = natureOf(table, i);
              return (
                <td key={c.key} className="num">
                  {n ? t(`nature.${n}` as MessageKey) : ""}
                </td>
              );
            })}
          </tr>
        </thead>
        <tbody>
          {table.rows.map((r) => (
            <tr
              key={r.key}
              className={
                r.kind === "total" || r.kind === "subtotal" ? r.kind : undefined
              }
            >
              <th scope="row">{el ? r.label_el : r.label}</th>
              {r.cells.map((c, i) => (
                <td key={values[i]?.key ?? i} className="num">
                  {cellText(c.value, locale, r.display)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function CommentEditor({
  packId,
  section,
}: {
  packId: string;
  section: Section;
}) {
  const { t, locale } = useI18n();
  const m = usePackMutations(packId);
  const [text, setText] = useState(section.comment ?? "");
  const id = `pk-comment-${section.key}`;
  return (
    <div className="form">
      <label htmlFor={id}>
        {t("pk.comment")}: {locale === "el" ? section.title_el : section.title}
      </label>
      <textarea
        id={id}
        rows={3}
        maxLength={4000}
        value={text}
        onChange={(e) => setText(e.target.value)}
      />
      <button
        type="button"
        disabled={m.comment.isPending || text === (section.comment ?? "")}
        onClick={() => m.comment.mutate({ section: section.key, text })}
      >
        {t("pk.saveComment")}
      </button>
      <ProblemMessage error={m.comment.error} />
    </div>
  );
}

function Risks({
  packId,
  risks,
  draft,
}: {
  packId: string;
  risks: Risk[];
  draft: boolean;
}) {
  const { t } = useI18n();
  const m = usePackMutations(packId);
  const [title, setTitle] = useState("");
  const [owner, setOwner] = useState("");
  const [mitigation, setMitigation] = useState("");
  const add = (e: SyntheticEvent) => {
    e.preventDefault();
    m.addRisk.mutate(
      { title, owner, mitigation, status: "OPEN" },
      {
        onSuccess: () => {
          setTitle("");
          setOwner("");
          setMitigation("");
        },
      },
    );
  };
  return (
    <>
      {risks.length === 0 ? <p className="muted">{t("pk.noRisks")}</p> : null}
      <ul>
        {risks.map((r) => (
          <li key={r.ref}>
            <strong>{r.title}</strong> ·{" "}
            {t(`pk.risk.${r.status}` as MessageKey)}
            {r.owner ? ` · ${t("pk.owner")}: ${r.owner}` : ""}
            {r.mitigation ? <p className="hint">{r.mitigation}</p> : null}
            {draft ? (
              <span className="form inline">
                <label>
                  <span className="visually-hidden">
                    {t("pk.status")} {r.title}
                  </span>
                  <select
                    value={r.status}
                    onChange={(e) =>
                      m.changeRisk.mutate({
                        ...r,
                        status: e.target.value as Risk["status"],
                      })
                    }
                  >
                    {(["OPEN", "MONITORING", "CLOSED"] as const).map((s) => (
                      <option key={s} value={s}>
                        {t(`pk.risk.${s}` as MessageKey)}
                      </option>
                    ))}
                  </select>
                </label>
                <button
                  type="button"
                  aria-label={`${t("pk.removeRisk")} ${r.title}`}
                  onClick={() => m.removeRisk.mutate(r.ref)}
                >
                  {t("pk.removeRisk")}
                </button>
              </span>
            ) : null}
          </li>
        ))}
      </ul>
      {draft ? (
        <form className="form" onSubmit={add} aria-label={t("pk.addRisk")}>
          <label>
            {t("pk.riskTitle")}
            <input
              required
              maxLength={200}
              value={title}
              onChange={(e) => setTitle(e.target.value)}
            />
          </label>
          <label>
            {t("pk.owner")}
            <input
              maxLength={120}
              value={owner}
              onChange={(e) => setOwner(e.target.value)}
            />
          </label>
          <label>
            {t("pk.mitigation")}
            <input
              maxLength={1000}
              value={mitigation}
              onChange={(e) => setMitigation(e.target.value)}
            />
          </label>
          <button type="submit" disabled={m.addRisk.isPending}>
            {t("pk.addRisk")}
          </button>
          <ProblemMessage error={m.addRisk.error ?? m.changeRisk.error} />
        </form>
      ) : null}
    </>
  );
}

function Arrange({ pack }: { pack: Pack }) {
  const { t } = useI18n();
  const m = usePackMutations(pack.id);
  const [sections, setSections] = useState<string[]>(pack.sections);
  const [columns, setColumns] = useState<string[]>(pack.columns);
  const flip = (list: string[], key: string) =>
    list.includes(key) ? list.filter((x) => x !== key) : [...list, key];
  return (
    <details className="card">
      <summary>{t("pk.arrange")}</summary>
      <fieldset>
        <legend>{t("pk.sections")}</legend>
        {SECTION_KEYS.map((k) => (
          <label key={k} className="checkbox">
            <input
              type="checkbox"
              checked={sections.includes(k)}
              onChange={() => setSections(flip(sections, k))}
            />{" "}
            {t(`pk.s.${k}` as MessageKey)}
          </label>
        ))}
      </fieldset>
      <fieldset>
        <legend>{t("pk.columns")}</legend>
        {COLUMN_KEYS.map((k) => (
          <label key={k} className="checkbox">
            <input
              type="checkbox"
              checked={columns.includes(k)}
              disabled={k === "actual"}
              onChange={() => setColumns(flip(columns, k))}
            />{" "}
            {t(`pk.c.${k}` as MessageKey)}
          </label>
        ))}
      </fieldset>
      <button
        type="button"
        disabled={!sections.length || m.arrange.isPending}
        onClick={() =>
          m.arrange.mutate({
            sections: SECTION_KEYS.filter((k) => sections.includes(k)),
            columns,
          })
        }
      >
        {t("pk.applyArrangement")}
      </button>
      <ProblemMessage error={m.arrange.error} />
    </details>
  );
}

function Actions({ pack }: { pack: PackDetail }) {
  const { t, locale } = useI18n();
  const { base } = useScope();
  const m = usePackMutations(pack.id);
  const [note, setNote] = useState("");
  const act = (
    what: "regenerate" | "submit" | "return" | "finalise" | "new-version",
    withNote = false,
  ) =>
    m.act.mutate(
      { what, ...(withNote ? { note } : {}) },
      { onSuccess: () => setNote("") },
    );
  return (
    <div className="actions">
      {pack.status === "DRAFT" ? (
        <>
          <button type="button" onClick={() => act("regenerate")}>
            {t("pk.regenerate")}
          </button>
          <button
            type="button"
            className="primary"
            onClick={() => act("submit")}
          >
            {t("pk.submit")}
          </button>
        </>
      ) : null}
      {pack.status === "IN_REVIEW" ? (
        <>
          <label>
            {t("pk.reviewNote")}
            <input
              value={note}
              maxLength={1000}
              onChange={(e) => setNote(e.target.value)}
            />
          </label>
          <button
            type="button"
            disabled={!note.trim()}
            onClick={() => act("return", true)}
          >
            {t("pk.return")}
          </button>
          <button
            type="button"
            className="primary"
            onClick={() => act("finalise", true)}
          >
            {t("pk.finalise")}
          </button>
        </>
      ) : null}
      {pack.status === "FINAL" ? (
        <button type="button" onClick={() => act("new-version")}>
          {t("pk.newVersion")}
        </button>
      ) : null}
      <a className="button" href={packExportUrl(base, pack.id, "xlsx", locale)}>
        {t("pk.exportExcel")}
      </a>
      <a className="button" href={packExportUrl(base, pack.id, "pdf", locale)}>
        {t("pk.exportPdf")}
      </a>
      <ProblemMessage error={m.act.error} />
    </div>
  );
}

function PackView({ id }: { id: string }) {
  const { t, locale } = useI18n();
  const pack = usePack(id);
  const rendered = usePackSections(id, locale);
  if (pack.isPending) return <Loading />;
  if (!pack.data) return <ProblemMessage error={pack.error} />;
  const p = pack.data;
  const draft = p.status === "DRAFT";
  return (
    <section className="card" aria-labelledby="pk-view">
      <h2 id="pk-view">
        {p.title}{" "}
        <span className="badge">
          {t(`pk.status.${p.status}` as MessageKey)}
        </span>{" "}
        {p.self_approved ? (
          <span className="badge">{t("approval.self")}</span>
        ) : null}{" "}
        <span className="badge">
          {t("pk.version")} {p.version}
        </span>
      </h2>
      <p>
        {p.period_start} – {p.period_end} · {t("pk.watermark")} #{p.watermark} ·{" "}
        {t("pk.generated")} {p.generated_at.slice(0, 16).replace("T", " ")}
      </p>
      {p.status !== "FINAL" && p.status !== "SUPERSEDED" ? (
        <p className="notice" role="note">
          {t("pk.draftNotice")}
        </p>
      ) : null}
      {p.review_note ? (
        <p>
          {t("pk.reviewNote")}: {p.review_note}
        </p>
      ) : null}
      {p.blockers.length ? (
        <div role="status" className="banner-warning">
          <p>{t("pk.blocked")}</p>
          <ul>
            {p.blockers.map((b) => (
              <li key={b}>{b}</li>
            ))}
          </ul>
        </div>
      ) : null}
      <Actions pack={p} />
      {draft ? <Arrange key={p.id + p.sections.join()} pack={p} /> : null}
      {rendered.isPending ? <Loading /> : null}
      <ProblemMessage error={rendered.error} />
      {(rendered.data?.sections ?? []).map((s) => (
        <section key={s.key} aria-labelledby={`pk-s-${s.key}`}>
          <h3 id={`pk-s-${s.key}`}>{locale === "el" ? s.title_el : s.title}</h3>
          {s.status === "denied" ? (
            <p className="muted">{t("pk.denied")}</p>
          ) : s.reason ? (
            <p className="muted">{s.reason}</p>
          ) : null}
          {s.notice ? (
            <p className="notice" role="note">
              {locale === "el" ? s.notice_el : s.notice}
            </p>
          ) : null}
          {s.tables.map((table) => (
            <PackTable key={table.caption} table={table} />
          ))}
          {s.key === "risks" ? (
            <Risks packId={p.id} risks={s.risks} draft={draft} />
          ) : null}
          {draft ? (
            <CommentEditor key={s.comment ?? ""} packId={p.id} section={s} />
          ) : s.comment ? (
            <p className="comment">{s.comment}</p>
          ) : null}
        </section>
      ))}
    </section>
  );
}

function NewPack({ onMade }: { onMade: (id: string) => void }) {
  const { t } = useI18n();
  const m = usePackMutations(null);
  const [kind, setKind] = useState("MONTH");
  const [month, setMonth] = useState(() => {
    const d = new Date();
    d.setDate(1);
    d.setMonth(d.getMonth() - 1);
    return d.toISOString().slice(0, 7);
  });
  const [title, setTitle] = useState("");
  const submit = (e: SyntheticEvent) => {
    e.preventDefault();
    m.create.mutate(
      { period_kind: kind, month: `${month}-01`, title },
      { onSuccess: (p) => onMade(p.id) },
    );
  };
  return (
    <form className="form inline" onSubmit={submit} aria-labelledby="pk-new">
      <h2 id="pk-new">{t("pk.new")}</h2>
      <label>
        {t("pk.periodKind")}
        <select value={kind} onChange={(e) => setKind(e.target.value)}>
          {(["MONTH", "QUARTER", "YEAR"] as const).map((k) => (
            <option key={k} value={k}>
              {t(`pk.kind.${k}` as MessageKey)}
            </option>
          ))}
        </select>
      </label>
      <label>
        {t("pk.month")}
        <input
          type="month"
          required
          value={month}
          onChange={(e) => setMonth(e.target.value)}
        />
      </label>
      <label>
        {t("pk.title")} ({t("sc.optional")})
        <input
          value={title}
          maxLength={160}
          onChange={(e) => setTitle(e.target.value)}
        />
      </label>
      <button type="submit" disabled={m.create.isPending}>
        {t("pk.generate")}
      </button>
      <ProblemMessage error={m.create.error} />
    </form>
  );
}

export function ReportPacksPage() {
  const { t } = useI18n();
  const list = usePacks();
  const [id, setId] = useState<string | null>(null);
  return (
    <Page title={t("nav.packs")}>
      <p>{t("pk.intro")}</p>
      <NewPack onMade={setId} />
      <section className="card" aria-labelledby="pk-list">
        <h2 id="pk-list">{t("pk.list")}</h2>
        {list.isPending ? <Loading /> : null}
        <ProblemMessage error={list.error} />
        {list.data && list.data.length === 0 ? <p>{t("pk.none")}</p> : null}
        {list.data?.length ? (
          <div className="table-scroll">
            <table className="grid">
              <caption className="visually-hidden">{t("pk.list")}</caption>
              <thead>
                <tr>
                  <th scope="col">{t("pk.title")}</th>
                  <th scope="col">{t("pk.period")}</th>
                  <th scope="col">{t("pk.version")}</th>
                  <th scope="col">{t("pk.statusLabel")}</th>
                </tr>
              </thead>
              <tbody>
                {list.data.map((p) => (
                  <tr key={p.id}>
                    <th scope="row">
                      <button
                        type="button"
                        className="link-button"
                        aria-pressed={id === p.id}
                        onClick={() => setId(p.id)}
                      >
                        {p.title}
                      </button>
                    </th>
                    <td>
                      {p.period_start} – {p.period_end}
                    </td>
                    <td>{p.version}</td>
                    <td>
                      {t(`pk.status.${p.status}` as MessageKey)}
                      {p.self_approved ? ` · ${t("approval.self")}` : ""}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}
      </section>
      {id ? <PackView key={id} id={id} /> : null}
    </Page>
  );
}
