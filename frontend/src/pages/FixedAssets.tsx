// Fixed assets (M6-1): the register, each asset's depreciation schedule, disposals, and the
// monthly depreciation prepared as a draft entry that still needs the normal approval. M6F-3:
// depreciation begins when the asset is available for use (IAS 16), and tax capital allowances
// are kept separately, by allowance class.
import { useState } from "react";
import { Link } from "react-router";
import {
  type AllowanceClassInput,
  type AssetCategory,
  type AssetInput,
  type Commencement,
  type DepreciationMethod,
  type FirstYearRule,
  type FixedAsset,
  useAllowanceClasses,
  useAssetMutations,
  useAssetReconciliation,
  useAssetSchedule,
  useDepreciationRuns,
  useFixedAssets,
} from "../api/assets";
import { useAccounts, useScope } from "../api/hooks";
import {
  FieldError,
  Loading,
  Page,
  ProblemMessage,
} from "../components/common";
import { useI18n } from "../i18n/I18n";
import type { MessageKey } from "../i18n/messages";
import { formatAmount } from "../money";

const CATEGORIES: AssetCategory[] = [
  "BUILDINGS",
  "MACHINERY",
  "VEHICLES",
  "IT_EQUIPMENT",
  "FURNITURE",
  "OTHER",
];
const today = () => new Date().toISOString().slice(0, 10);
const COMMENCEMENTS: Commencement[] = [
  "PRORATA_DAYS",
  "NEXT_MONTH",
  "FULL_MONTH",
];
const FIRST_YEAR: FirstYearRule[] = ["FULL_YEAR", "MONTHS_IN_USE", "NONE"];

function Schedule({ asset }: { asset: FixedAsset }) {
  const { t, locale } = useI18n();
  const { slug, entityId } = useScope();
  const s = useAssetSchedule(asset.id);
  if (s.isPending) return <Loading />;
  if (!s.data) return <ProblemMessage error={s.error} />;
  return (
    <div className="table-scroll">
      <p className="muted">{s.data.convention}</p>
      <table className="grid">
        <caption>
          {t("fa.schedule")}: {asset.code} {asset.name}
        </caption>
        <thead>
          <tr>
            <th scope="col">{t("fa.month")}</th>
            <th scope="col" className="num">
              {t("fa.opening")}
            </th>
            <th scope="col" className="num">
              {t("fa.depreciation")}
            </th>
            <th scope="col" className="num">
              {t("fa.closing")}
            </th>
            <th scope="col">{t("fa.entry")}</th>
          </tr>
        </thead>
        <tbody>
          {s.data.rows.map((r) => (
            <tr key={r.month}>
              <td>{r.month.slice(0, 7)}</td>
              <td className="num">{formatAmount(r.opening, locale)}</td>
              <td className="num">{formatAmount(r.depreciation, locale)}</td>
              <td className="num">{formatAmount(r.closing, locale)}</td>
              <td>
                {r.entry_id ? (
                  <Link to={`/w/${slug}/e/${entityId}/entries/${r.entry_id}`}>
                    {t("fa.prepared")}
                  </Link>
                ) : (
                  "—"
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <h3>{t("fa.allowances")}</h3>
      <p className="muted">{s.data.allowance_rules}</p>
      {s.data.allowances.length === 0 ? (
        <p className="muted">{t("fa.noAllowances")}</p>
      ) : (
        <table className="grid">
          <caption>
            {t("fa.allowances")}: {asset.code} {asset.name}
          </caption>
          <thead>
            <tr>
              <th scope="col">{t("fa.taxYear")}</th>
              <th scope="col" className="num">
                {t("fa.allowanceRate")}
              </th>
              <th scope="col" className="num">
                {t("fa.allowance")}
              </th>
              <th scope="col" className="num">
                {t("fa.writtenDown")}
              </th>
            </tr>
          </thead>
          <tbody>
            {s.data.allowances.map((r) => (
              <tr key={r.tax_year}>
                <td>{r.tax_year}</td>
                <td className="num">{r.rate}%</td>
                <td className="num">{formatAmount(r.allowance, locale)}</td>
                <td className="num">{formatAmount(r.written_down, locale)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

function AllowanceClasses() {
  const { t } = useI18n();
  const classes = useAllowanceClasses();
  const m = useAssetMutations();
  const blank = (): AllowanceClassInput => ({
    code: "",
    name: "",
    annual_rate: "",
    first_year: "FULL_YEAR",
    effective_from: `${new Date().getFullYear()}-01-01`,
    source: "",
  });
  const [form, setForm] = useState<AllowanceClassInput>(blank);
  const set = (patch: Partial<AllowanceClassInput>) =>
    setForm({ ...form, ...patch });
  return (
    <section className="card" aria-labelledby="fa-classes">
      <h2 id="fa-classes">{t("fa.classes")}</h2>
      <p>{t("fa.classesIntro")}</p>
      {classes.data?.length ? (
        <div className="table-scroll">
          <table className="grid">
            <caption>{t("fa.classes")}</caption>
            <thead>
              <tr>
                <th scope="col">{t("fa.classCode")}</th>
                <th scope="col">{t("fa.className")}</th>
                <th scope="col" className="num">
                  {t("fa.allowanceRate")}
                </th>
                <th scope="col">{t("fa.firstYear")}</th>
                <th scope="col">{t("fa.effectiveFrom")}</th>
                <th scope="col">{t("fa.source")}</th>
              </tr>
            </thead>
            <tbody>
              {classes.data.map((c) => (
                <tr key={c.id}>
                  <td>{c.code}</td>
                  <td>{c.name}</td>
                  <td className="num">{c.annual_rate}%</td>
                  <td>{t(`fa.fy.${c.first_year}` as MessageKey)}</td>
                  <td>{c.effective_from}</td>
                  <td>{c.source}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="muted">{t("fa.noClasses")}</p>
      )}
      <div className="form inline">
        <label>
          {t("fa.classCode")}
          <input
            value={form.code}
            maxLength={20}
            onChange={(e) => set({ code: e.target.value })}
          />
        </label>
        <label>
          {t("fa.className")}
          <input
            value={form.name}
            maxLength={200}
            onChange={(e) => set({ name: e.target.value })}
          />
        </label>
        <label>
          {t("fa.allowanceRate")}
          <input
            inputMode="decimal"
            value={form.annual_rate}
            onChange={(e) => set({ annual_rate: e.target.value })}
          />
          <FieldError error={m.addClass.error} field="annual_rate" />
        </label>
        <label>
          {t("fa.firstYear")}
          <select
            value={form.first_year}
            onChange={(e) =>
              set({ first_year: e.target.value as FirstYearRule })
            }
          >
            {FIRST_YEAR.map((r) => (
              <option key={r} value={r}>
                {t(`fa.fy.${r}` as MessageKey)}
              </option>
            ))}
          </select>
        </label>
        <label>
          {t("fa.effectiveFrom")}
          <input
            type="date"
            value={form.effective_from}
            onChange={(e) => set({ effective_from: e.target.value })}
          />
          <FieldError error={m.addClass.error} field="effective_from" />
        </label>
        <label>
          {t("fa.source")}
          <input
            value={form.source}
            maxLength={500}
            onChange={(e) => set({ source: e.target.value })}
          />
          <FieldError error={m.addClass.error} field="source" />
        </label>
        <button
          type="button"
          disabled={
            !form.code.trim() ||
            !form.name.trim() ||
            !form.annual_rate ||
            !form.source.trim() ||
            m.addClass.isPending
          }
          onClick={() =>
            m.addClass.mutate(form, { onSuccess: () => setForm(blank()) })
          }
        >
          {t("fa.addClass")}
        </button>
      </div>
      <ProblemMessage error={m.addClass.error} />
    </section>
  );
}

function Dispose({ asset, done }: { asset: FixedAsset; done: () => void }) {
  const { t } = useI18n();
  const m = useAssetMutations();
  const [form, setForm] = useState({ disposed_on: today(), proceeds: "0" });
  return (
    <div className="form inline">
      <label>
        {t("fa.disposedOn")}
        <input
          type="date"
          value={form.disposed_on}
          onChange={(e) => setForm({ ...form, disposed_on: e.target.value })}
        />
      </label>
      <label>
        {t("fa.proceeds")}
        <input
          inputMode="decimal"
          value={form.proceeds}
          onChange={(e) => setForm({ ...form, proceeds: e.target.value })}
        />
      </label>
      <button
        type="button"
        disabled={m.dispose.isPending}
        onClick={() =>
          m.dispose.mutate({ id: asset.id, ...form }, { onSuccess: done })
        }
      >
        {t("fa.recordDisposal")}
      </button>
      <ProblemMessage error={m.dispose.error} />
    </div>
  );
}

function AddAsset() {
  const { t } = useI18n();
  const accounts = useAccounts();
  const classes = useAllowanceClasses();
  const m = useAssetMutations();
  const postable = (accounts.data ?? []).filter(
    (a) => a.is_postable && a.status === "ACTIVE",
  );
  const byCode = (code: string) =>
    postable.find((a) => a.code === code)?.id ?? "";
  const blank = (): AssetInput => ({
    code: "",
    name: "",
    category: "MACHINERY",
    asset_account_id: byCode("1010"),
    accumulated_account_id: byCode("1019"),
    expense_account_id: byCode("6600"),
    acquired_on: today(),
    cost: "",
    residual_value: "0",
    useful_life_months: 60,
    method: "STRAIGHT_LINE",
    annual_rate: null,
    available_on: null,
    commencement: "PRORATA_DAYS",
    allowance_class_code: "",
  });
  const [form, setForm] = useState<AssetInput | null>(null);
  if (!form) {
    return (
      <button
        type="button"
        className="primary"
        disabled={!accounts.data}
        onClick={() => setForm(blank())}
      >
        {t("fa.add")}
      </button>
    );
  }
  const set = (patch: Partial<AssetInput>) => setForm({ ...form, ...patch });
  const select = (
    field: "asset_account_id" | "accumulated_account_id" | "expense_account_id",
    type: string,
    label: MessageKey,
  ) => (
    <label>
      {t(label)}
      <select
        value={form[field]}
        onChange={(e) => set({ [field]: e.target.value })}
      >
        <option value="">—</option>
        {postable
          .filter((a) => a.type === type)
          .map((a) => (
            <option key={a.id} value={a.id}>
              {a.code} {a.name}
            </option>
          ))}
      </select>
      <FieldError error={m.create.error} field={field} />
    </label>
  );
  return (
    <section className="card" aria-labelledby="fa-new">
      <h2 id="fa-new">{t("fa.add")}</h2>
      <div className="form inline">
        <label>
          {t("fa.code")}
          <input
            value={form.code}
            maxLength={20}
            onChange={(e) => set({ code: e.target.value })}
          />
          <FieldError error={m.create.error} field="code" />
        </label>
        <label>
          {t("fa.name")}
          <input
            value={form.name}
            maxLength={200}
            onChange={(e) => set({ name: e.target.value })}
          />
        </label>
        <label>
          {t("fa.category")}
          <select
            value={form.category}
            onChange={(e) => set({ category: e.target.value as AssetCategory })}
          >
            {CATEGORIES.map((c) => (
              <option key={c} value={c}>
                {t(`fa.cat.${c}` as MessageKey)}
              </option>
            ))}
          </select>
        </label>
        <label>
          {t("fa.acquiredOn")}
          <input
            type="date"
            value={form.acquired_on}
            onChange={(e) => set({ acquired_on: e.target.value })}
          />
        </label>
        <label>
          {t("fa.cost")}
          <input
            inputMode="decimal"
            value={form.cost}
            onChange={(e) => set({ cost: e.target.value })}
          />
          <FieldError error={m.create.error} field="cost" />
        </label>
        <label>
          {t("fa.residual")}
          <input
            inputMode="decimal"
            value={form.residual_value}
            onChange={(e) => set({ residual_value: e.target.value })}
          />
          <FieldError error={m.create.error} field="residual_value" />
        </label>
        <label>
          {t("fa.life")}
          <input
            inputMode="numeric"
            value={form.useful_life_months}
            onChange={(e) =>
              set({ useful_life_months: Number(e.target.value) || 0 })
            }
          />
        </label>
        <label>
          {t("fa.method")}
          <select
            value={form.method}
            onChange={(e) =>
              set({ method: e.target.value as DepreciationMethod })
            }
          >
            <option value="STRAIGHT_LINE">{t("fa.straightLine")}</option>
            <option value="DECLINING_BALANCE">{t("fa.declining")}</option>
          </select>
        </label>
        {form.method === "DECLINING_BALANCE" ? (
          <label>
            {t("fa.rate")}
            <input
              inputMode="decimal"
              value={form.annual_rate ?? ""}
              onChange={(e) => set({ annual_rate: e.target.value })}
            />
            <FieldError error={m.create.error} field="annual_rate" />
          </label>
        ) : null}
        <label>
          {t("fa.availableOn")}
          <input
            type="date"
            value={form.available_on ?? form.acquired_on}
            onChange={(e) => set({ available_on: e.target.value || null })}
          />
          <FieldError error={m.create.error} field="available_on" />
        </label>
        <label>
          {t("fa.commencement")}
          <select
            value={form.commencement}
            onChange={(e) =>
              set({ commencement: e.target.value as Commencement })
            }
          >
            {COMMENCEMENTS.map((c) => (
              <option key={c} value={c}>
                {t(`fa.comm.${c}` as MessageKey)}
              </option>
            ))}
          </select>
        </label>
        <label>
          {t("fa.allowanceClass")}
          <select
            value={form.allowance_class_code}
            onChange={(e) => set({ allowance_class_code: e.target.value })}
          >
            <option value="">{t("fa.noAllowanceClass")}</option>
            {[...new Set((classes.data ?? []).map((c) => c.code))].map(
              (code) => (
                <option key={code} value={code}>
                  {code}
                </option>
              ),
            )}
          </select>
        </label>
        {select("asset_account_id", "ASSET", "fa.assetAccount")}
        {select("accumulated_account_id", "ASSET", "fa.accumulatedAccount")}
        {select("expense_account_id", "EXPENSE", "fa.expenseAccount")}
        <button
          type="button"
          className="primary"
          disabled={
            !form.code.trim() ||
            !form.name.trim() ||
            !form.cost ||
            m.create.isPending
          }
          onClick={() =>
            m.create.mutate(
              {
                ...form,
                annual_rate:
                  form.method === "DECLINING_BALANCE"
                    ? (form.annual_rate ?? null)
                    : null,
              },
              { onSuccess: () => setForm(null) },
            )
          }
        >
          {t("my.save")}
        </button>
        <button type="button" onClick={() => setForm(null)}>
          {t("data.cancel")}
        </button>
      </div>
      <ProblemMessage error={m.create.error} />
    </section>
  );
}

function Depreciation() {
  const { t, locale } = useI18n();
  const { slug, entityId } = useScope();
  const runs = useDepreciationRuns();
  const m = useAssetMutations();
  const [month, setMonth] = useState(today().slice(0, 7));
  return (
    <section className="card" aria-labelledby="fa-dep">
      <h2 id="fa-dep">{t("fa.prepareTitle")}</h2>
      <p className="muted">{t("fa.prepareText")}</p>
      <div className="form inline">
        <label>
          {t("fa.month")}
          <input
            type="month"
            value={month}
            onChange={(e) => setMonth(e.target.value)}
          />
        </label>
        <button
          type="button"
          className="primary"
          disabled={!month || m.prepare.isPending}
          onClick={() => m.prepare.mutate(`${month}-01`)}
        >
          {t("fa.prepare")}
        </button>
      </div>
      <ProblemMessage error={m.prepare.error ?? runs.error} />
      {runs.data?.length ? (
        <div className="table-scroll">
          <table className="grid">
            <caption>{t("fa.runs")}</caption>
            <thead>
              <tr>
                <th scope="col">{t("fa.month")}</th>
                <th scope="col" className="num">
                  {t("fa.depreciation")}
                </th>
                <th scope="col" className="num">
                  {t("fa.assets")}
                </th>
                <th scope="col">{t("fa.entry")}</th>
              </tr>
            </thead>
            <tbody>
              {runs.data.map((r) => (
                <tr key={r.id} className={r.cancelled ? "muted" : undefined}>
                  <td>{r.month.slice(0, 7)}</td>
                  <td className="num">{formatAmount(r.total, locale)}</td>
                  <td className="num">{r.assets}</td>
                  <td>
                    <Link to={`/w/${slug}/e/${entityId}/entries/${r.entry_id}`}>
                      {r.entry_ref || t("fa.draft")}
                    </Link>{" "}
                    · {t(`fa.status.${r.entry_status}` as MessageKey)}
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

/** The register against the ledger on the date shown (V1-4). */
function Reconciliation({ asOf }: { asOf: string }) {
  const { t, locale } = useI18n();
  const found = useAssetReconciliation(asOf);
  const data = found.data;
  if (!data || data.rows.length === 0) {
    return <ProblemMessage error={found.error} />;
  }
  return (
    <section className="panel" aria-labelledby="fa-rec">
      <h2 id="fa-rec">{t("fa.rec.title")}</h2>
      <p className={data.agrees ? "muted" : "notice warn"} role="status">
        {data.agrees ? t("fa.rec.agrees") : t("fa.rec.differs")}
      </p>
      <div className="table-scroll">
        <table className="grid">
          <caption className="visually-hidden">{t("fa.rec.title")}</caption>
          <thead>
            <tr>
              <th scope="col">{t("fa.rec.account")}</th>
              <th scope="col" className="num">
                {t("fa.rec.register")}
              </th>
              <th scope="col" className="num">
                {t("fa.rec.ledger")}
              </th>
              <th scope="col" className="num">
                {t("fa.rec.difference")}
              </th>
            </tr>
          </thead>
          <tbody>
            {data.rows.map((r) => (
              <tr key={`${r.kind}-${r.account_id}`}>
                <th scope="row">
                  {r.account_code} · {r.account_name}
                  <br />
                  <span className="muted">
                    {t(`fa.rec.${r.kind}` as MessageKey)}
                  </span>
                </th>
                <td className="num">
                  {formatAmount(r.register_total, locale)}
                </td>
                <td className="num">{formatAmount(r.ledger_total, locale)}</td>
                <td className="num">{formatAmount(r.difference, locale)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {data.unposted_runs.length ? (
        <p className="muted">
          {t("fa.rec.unposted").replace(
            "{months}",
            data.unposted_runs.map((r) => r.month.slice(0, 7)).join(", "),
          )}
        </p>
      ) : null}
    </section>
  );
}

export function FixedAssetsPage() {
  const { t, locale } = useI18n();
  const [asOf, setAsOf] = useState(today());
  const list = useFixedAssets(asOf);
  const [open, setOpen] = useState<{ id: string; view: string } | null>(null);
  return (
    <Page title={t("nav.fixedAssets")}>
      <AddAsset />
      <AllowanceClasses />
      <label>
        {t("fa.asOf")}
        <input
          type="date"
          value={asOf}
          onChange={(e) => e.target.value && setAsOf(e.target.value)}
        />
      </label>
      {list.isPending ? <Loading /> : null}
      <ProblemMessage error={list.error} />
      {list.data && list.data.length === 0 ? (
        <p className="muted">{t("fa.none")}</p>
      ) : null}
      {list.data?.length ? (
        <div className="table-scroll">
          <table className="grid">
            <caption>{t("fa.register")}</caption>
            <thead>
              <tr>
                <th scope="col">{t("fa.code")}</th>
                <th scope="col">{t("fa.name")}</th>
                <th scope="col">{t("fa.acquiredOn")}</th>
                <th scope="col" className="num">
                  {t("fa.cost")}
                </th>
                <th scope="col" className="num">
                  {t("fa.accumulated")}
                </th>
                <th scope="col" className="num">
                  {t("fa.bookValue")}
                </th>
                <th scope="col">{t("fa.statusCol")}</th>
                <th scope="col">
                  <span className="visually-hidden">{t("eng.actions")}</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {list.data.map((a) => (
                <tr key={a.id}>
                  <th scope="row">{a.code}</th>
                  <td>
                    {a.name}
                    <br />
                    <span className="muted">
                      {t(`fa.cat.${a.category}` as MessageKey)} ·{" "}
                      {a.method === "STRAIGHT_LINE"
                        ? t("fa.straightLine")
                        : `${t("fa.declining")} ${a.annual_rate}%`}{" "}
                      · {a.useful_life_months} {t("fa.months")}
                    </span>
                  </td>
                  <td>{a.acquired_on}</td>
                  <td className="num">{formatAmount(a.cost, locale)}</td>
                  <td className="num">{formatAmount(a.accumulated, locale)}</td>
                  <td className="num">{formatAmount(a.book_value, locale)}</td>
                  <td>
                    {t(`fa.st.${a.status}` as MessageKey)}
                    {a.disposal_gain !== null ? (
                      <>
                        <br />
                        <span className="muted">
                          {t("fa.gain")} {formatAmount(a.disposal_gain, locale)}
                        </span>
                      </>
                    ) : null}
                  </td>
                  <td>
                    <button
                      type="button"
                      className="link-button"
                      aria-expanded={
                        open?.id === a.id && open.view === "schedule"
                      }
                      onClick={() =>
                        setOpen(
                          open?.id === a.id && open.view === "schedule"
                            ? null
                            : { id: a.id, view: "schedule" },
                        )
                      }
                    >
                      {t("fa.schedule")}
                    </button>
                    {a.disposed_on ? null : (
                      <>
                        {" "}
                        <button
                          type="button"
                          className="link-button"
                          aria-expanded={
                            open?.id === a.id && open.view === "dispose"
                          }
                          onClick={() =>
                            setOpen(
                              open?.id === a.id && open.view === "dispose"
                                ? null
                                : { id: a.id, view: "dispose" },
                            )
                          }
                        >
                          {t("fa.dispose")}
                        </button>
                      </>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
      {list.data?.map((a) =>
        open?.id === a.id ? (
          <section
            key={a.id}
            className="card"
            aria-label={`${a.code} ${a.name}`}
          >
            {open.view === "schedule" ? (
              <Schedule asset={a} />
            ) : (
              <Dispose asset={a} done={() => setOpen(null)} />
            )}
          </section>
        ) : null,
      )}
      <Reconciliation asOf={asOf} />
      <Depreciation />
    </Page>
  );
}
