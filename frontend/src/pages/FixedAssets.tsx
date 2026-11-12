// Fixed assets (M6-1): the register, each asset's depreciation schedule, disposals, and the
// monthly depreciation prepared as a draft entry that still needs the normal approval.
import { useState } from "react";
import { Link } from "react-router";
import {
  type AssetCategory,
  type AssetInput,
  type DepreciationMethod,
  type FixedAsset,
  useAssetMutations,
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
    </div>
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

export function FixedAssetsPage() {
  const { t, locale } = useI18n();
  const [asOf, setAsOf] = useState(today());
  const list = useFixedAssets(asOf);
  const [open, setOpen] = useState<{ id: string; view: string } | null>(null);
  return (
    <Page title={t("nav.fixedAssets")}>
      <AddAsset />
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
      <Depreciation />
    </Page>
  );
}
