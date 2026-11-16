import { useState } from "react";
import {
  type MoneyType,
  type PersonalAccount,
  type TransactionIn,
  useNetWorth,
  usePersonalAccounts,
  usePersonalMutations,
  useSpending,
  useTransactions,
} from "../api/personal";
import { Loading, Page, ProblemMessage } from "../components/common";
import { useI18n } from "../i18n/I18n";
import type { MessageKey } from "../i18n/messages";
import { formatAmount } from "../money";

const today = () => new Date().toISOString().slice(0, 10);
const monthStart = (d: string) => `${d.slice(0, 7)}-01`;
function monthEnd(d: string): string {
  const [y, m] = d.split("-").map(Number) as [number, number];
  return new Date(Date.UTC(y, m, 0)).toISOString().slice(0, 10);
}

function NatureBadge({ nature }: { nature: string }) {
  const { t } = useI18n();
  return (
    <span className={`badge nature-${nature.toLowerCase()}`}>
      {t(nature === "EXPECTED" ? "my.valuation" : "nature.ACTUAL")}
    </span>
  );
}

function Setup() {
  const { t } = useI18n();
  const m = usePersonalMutations();
  return (
    <section className="card" aria-labelledby="my-setup">
      <h2 id="my-setup">{t("my.setupTitle")}</h2>
      <p>{t("my.setupText")}</p>
      <button
        type="button"
        className="primary"
        disabled={m.setup.isPending}
        onClick={() => m.setup.mutate({})}
      >
        {t("my.setup")}
      </button>
      <ProblemMessage error={m.setup.error} />
    </section>
  );
}

function AccountTable({
  rows,
  caption,
}: {
  rows: PersonalAccount[];
  caption: string;
}) {
  const { t, locale } = useI18n();
  return (
    <div className="table-scroll">
      <table className="grid">
        <caption>{caption}</caption>
        <thead>
          <tr>
            <th scope="col">{t("my.account")}</th>
            <th scope="col" className="num">
              {t("my.amount")}
            </th>
            <th scope="col">{t("goal.nature")}</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((a) => (
            <tr key={a.id}>
              <td>{a.name}</td>
              <td className="num">{formatAmount(a.amount, locale)}</td>
              <td>
                <NatureBadge nature={a.nature} />
                {a.valuation_date ? ` ${a.valuation_date}` : ""}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Forms({ accounts }: { accounts: PersonalAccount[] }) {
  const { t } = useI18n();
  const m = usePersonalMutations();
  const money = accounts.filter(
    (a) => a.type === "ASSET" || a.type === "LIABILITY",
  );
  const assets = accounts.filter((a) => a.type === "ASSET");
  const [opening, setOpening] = useState({
    account_id: "",
    date: today(),
    amount: "",
  });
  const [value, setValue] = useState({
    account_id: "",
    date: today(),
    value: "",
    note: "",
  });
  const [account, setAccount] = useState<{ kind: MoneyType; name: string }>({
    kind: "ASSET",
    name: "",
  });
  return (
    <>
      <section className="card" aria-labelledby="my-opening">
        <h2 id="my-opening">{t("my.openingTitle")}</h2>
        <div className="form inline">
          <label>
            {t("my.account")}
            <select
              value={opening.account_id}
              onChange={(e) =>
                setOpening({ ...opening, account_id: e.target.value })
              }
            >
              <option value="">—</option>
              {money.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.name}
                </option>
              ))}
            </select>
          </label>
          <label>
            {t("my.date")}
            <input
              type="date"
              value={opening.date}
              onChange={(e) => setOpening({ ...opening, date: e.target.value })}
            />
          </label>
          <label>
            {t("my.amount")}
            <input
              inputMode="decimal"
              value={opening.amount}
              onChange={(e) =>
                setOpening({ ...opening, amount: e.target.value })
              }
            />
          </label>
          <button
            type="button"
            disabled={
              !opening.account_id || !opening.amount || m.opening.isPending
            }
            onClick={() =>
              m.opening.mutate(opening, {
                onSuccess: () => setOpening({ ...opening, amount: "" }),
              })
            }
          >
            {t("my.save")}
          </button>
        </div>
        <ProblemMessage error={m.opening.error} />
      </section>
      <section className="card" aria-labelledby="my-value">
        <h2 id="my-value">{t("my.valueTitle")}</h2>
        <p className="muted">{t("my.valueText")}</p>
        <div className="form inline">
          <label>
            {t("my.account")}
            <select
              value={value.account_id}
              onChange={(e) =>
                setValue({ ...value, account_id: e.target.value })
              }
            >
              <option value="">—</option>
              {assets.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.name}
                </option>
              ))}
            </select>
          </label>
          <label>
            {t("my.date")}
            <input
              type="date"
              value={value.date}
              onChange={(e) => setValue({ ...value, date: e.target.value })}
            />
          </label>
          <label>
            {t("my.worth")}
            <input
              inputMode="decimal"
              value={value.value}
              onChange={(e) => setValue({ ...value, value: e.target.value })}
            />
          </label>
          <label>
            {t("my.note")}
            <input
              value={value.note}
              maxLength={300}
              onChange={(e) => setValue({ ...value, note: e.target.value })}
            />
          </label>
          <button
            type="button"
            disabled={
              !value.account_id || !value.value || m.valuation.isPending
            }
            onClick={() =>
              m.valuation.mutate(value, {
                onSuccess: () => setValue({ ...value, value: "", note: "" }),
              })
            }
          >
            {t("my.save")}
          </button>
        </div>
        <ProblemMessage error={m.valuation.error} />
      </section>
      <section className="card" aria-labelledby="my-new-account">
        <h2 id="my-new-account">{t("my.newAccount")}</h2>
        <div className="form inline">
          <label>
            {t("my.kind")}
            <select
              value={account.kind}
              onChange={(e) =>
                setAccount({ ...account, kind: e.target.value as MoneyType })
              }
            >
              {(["ASSET", "LIABILITY", "INCOME", "EXPENSE"] as const).map(
                (k) => (
                  <option key={k} value={k}>
                    {t(`my.type.${k}` as MessageKey)}
                  </option>
                ),
              )}
            </select>
          </label>
          <label>
            {t("my.name")}
            <input
              value={account.name}
              maxLength={120}
              onChange={(e) => setAccount({ ...account, name: e.target.value })}
            />
          </label>
          <button
            type="button"
            disabled={!account.name.trim() || m.account.isPending}
            onClick={() =>
              m.account.mutate(account, {
                onSuccess: () => setAccount({ ...account, name: "" }),
              })
            }
          >
            {t("my.add")}
          </button>
        </div>
        <ProblemMessage error={m.account.error} />
      </section>
    </>
  );
}

export function PersonalOverviewPage() {
  const { t, locale } = useI18n();
  const accounts = usePersonalAccounts();
  const worth = useNetWorth();
  const ready = (accounts.data?.length ?? 0) > 0;
  const nw = worth.data;
  return (
    <Page title={t("my.title")}>
      <p className="muted">{t("my.intro")}</p>
      {accounts.isPending ? <Loading /> : null}
      <ProblemMessage error={accounts.error ?? worth.error} />
      {accounts.data && !ready ? <Setup /> : null}
      {ready && nw ? (
        <>
          <section className="card" aria-labelledby="my-worth">
            <h2 id="my-worth">
              {t("my.netWorth")} {nw.as_of}
            </h2>
            <dl className="facts">
              <dt>{t("my.totalAssets")}</dt>
              <dd>{formatAmount(nw.total_assets, locale)}</dd>
              <dt>{t("my.totalLiabilities")}</dt>
              <dd>{formatAmount(nw.total_liabilities, locale)}</dd>
              <dt>{t("my.netWorth")}</dt>
              <dd>
                <strong>{formatAmount(nw.net_worth, locale)}</strong>
              </dd>
            </dl>
            {nw.includes_valuations ? (
              <p className="muted">{t("my.includesValuations")}</p>
            ) : null}
            <AccountTable rows={nw.assets} caption={t("my.whatIOwn")} />
            <AccountTable rows={nw.liabilities} caption={t("my.whatIOwe")} />
            <div className="table-scroll">
              <table className="grid">
                <caption>{t("my.trend")}</caption>
                <thead>
                  <tr>
                    <th scope="col">{t("goal.period")}</th>
                    <th scope="col" className="num">
                      {t("my.netWorth")}
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {nw.trend.map((p) => (
                    <tr key={p.date}>
                      <td>{p.date}</td>
                      <td className="num">
                        {formatAmount(p.net_worth, locale)}
                        {p.includes_valuations ? " *" : ""}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
          <Forms accounts={accounts.data ?? []} />
        </>
      ) : null}
    </Page>
  );
}

const KINDS: TransactionIn["kind"][] = ["SPENT", "RECEIVED", "MOVED"];

function RecordForm({ accounts }: { accounts: PersonalAccount[] }) {
  const { t } = useI18n();
  const m = usePersonalMutations();
  const empty: TransactionIn = {
    kind: "SPENT",
    date: today(),
    amount: "",
    description: "",
    account_id: "",
  };
  const [form, setForm] = useState<TransactionIn>(empty);
  const money = accounts.filter(
    (a) => a.type === "ASSET" || a.type === "LIABILITY",
  );
  const categories = accounts.filter((a) =>
    form.kind === "SPENT" ? a.type === "EXPENSE" : a.type === "INCOME",
  );
  const other = form.kind === "MOVED" ? form.to_account_id : form.category_id;
  const save = () =>
    m.record.mutate(form, {
      onSuccess: () =>
        setForm({ ...empty, kind: form.kind, account_id: form.account_id }),
    });
  return (
    <section className="card" aria-labelledby="my-record">
      <h2 id="my-record">{t("my.record")}</h2>
      <fieldset>
        <legend>{t("my.kind")}</legend>
        {KINDS.map((k) => (
          <label key={k} className="checkbox">
            <input
              type="radio"
              name="kind"
              checked={form.kind === k}
              onChange={() =>
                setForm({
                  kind: k,
                  date: form.date,
                  amount: form.amount,
                  description: form.description,
                  account_id: form.account_id,
                })
              }
            />{" "}
            {t(`my.kind.${k}` as MessageKey)}
          </label>
        ))}
      </fieldset>
      <div className="form inline">
        <label>
          {t("my.date")}
          <input
            type="date"
            value={form.date}
            onChange={(e) => setForm({ ...form, date: e.target.value })}
          />
        </label>
        <label>
          {t("my.amount")}
          <input
            inputMode="decimal"
            value={form.amount}
            onChange={(e) => setForm({ ...form, amount: e.target.value })}
          />
        </label>
        <label>
          {t("my.description")}
          <input
            value={form.description}
            maxLength={300}
            onChange={(e) => setForm({ ...form, description: e.target.value })}
          />
        </label>
        <label>
          {t(form.kind === "RECEIVED" ? "my.into" : "my.from")}
          <select
            value={form.account_id}
            onChange={(e) => setForm({ ...form, account_id: e.target.value })}
          >
            <option value="">—</option>
            {money.map((a) => (
              <option key={a.id} value={a.id}>
                {a.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          {t(form.kind === "MOVED" ? "my.to" : "my.category")}
          <select
            value={other ?? ""}
            onChange={(e) =>
              setForm(
                form.kind === "MOVED"
                  ? { ...form, to_account_id: e.target.value }
                  : { ...form, category_id: e.target.value },
              )
            }
          >
            <option value="">—</option>
            {(form.kind === "MOVED" ? money : categories).map((a) => (
              <option key={a.id} value={a.id}>
                {a.name}
              </option>
            ))}
          </select>
        </label>
        <button
          type="button"
          className="primary"
          disabled={
            !form.amount ||
            !form.description.trim() ||
            !form.account_id ||
            !other ||
            m.record.isPending
          }
          onClick={save}
        >
          {t("my.save")}
        </button>
      </div>
      <ProblemMessage error={m.record.error} />
    </section>
  );
}

export function PersonalTransactionsPage() {
  const { t, locale } = useI18n();
  const [month, setMonth] = useState(monthStart(today()));
  const accounts = usePersonalAccounts();
  const list = useTransactions(month, monthEnd(month));
  const spent = useSpending(month, monthEnd(month));
  const m = usePersonalMutations();
  const names = new Map((accounts.data ?? []).map((a) => [a.id, a.name]));
  const undo = (id: string) => {
    const reason = window.prompt(t("my.undoReason"));
    if (reason) m.undo.mutate({ id, reason });
  };
  return (
    <Page title={t("my.transactions")}>
      {accounts.data && accounts.data.length === 0 ? <Setup /> : null}
      {accounts.data?.length ? <RecordForm accounts={accounts.data} /> : null}
      <label>
        {t("my.month")}
        <input
          type="month"
          value={month.slice(0, 7)}
          onChange={(e) => e.target.value && setMonth(`${e.target.value}-01`)}
        />
      </label>
      {list.isPending ? <Loading /> : null}
      <ProblemMessage error={list.error ?? m.undo.error} />
      {spent.data ? (
        <p role="status">
          {t("my.income")}: {formatAmount(spent.data.total_income, locale)} ·{" "}
          {t("my.spending")}: {formatAmount(spent.data.total_spending, locale)}{" "}
          · {t("my.leftOver")}: {formatAmount(spent.data.left_over, locale)}
        </p>
      ) : null}
      {list.data ? (
        <div className="table-scroll">
          <table className="grid">
            <caption>{t("my.transactions")}</caption>
            <thead>
              <tr>
                <th scope="col">{t("my.date")}</th>
                <th scope="col">{t("my.description")}</th>
                <th scope="col">{t("my.kind")}</th>
                <th scope="col">{t("my.account")}</th>
                <th scope="col">{t("my.categoryOrTo")}</th>
                <th scope="col" className="num">
                  {t("my.amount")}
                </th>
                <th scope="col">
                  <span className="visually-hidden">{t("my.actions")}</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {list.data.map((x) => (
                <tr key={x.entry_id} className={x.undone ? "muted" : ""}>
                  <td>{x.date}</td>
                  <td>{x.description}</td>
                  <td>
                    {t(`my.kind.${x.kind}` as MessageKey)}
                    {x.undone ? ` (${t("my.undone")})` : ""}
                  </td>
                  <td>{x.account_id ? (names.get(x.account_id) ?? "") : ""}</td>
                  <td>{x.other_id ? (names.get(x.other_id) ?? "") : ""}</td>
                  <td className="num">{formatAmount(x.amount, locale)}</td>
                  <td>
                    {x.kind !== "UNDO" && !x.undone ? (
                      <button
                        type="button"
                        className="link"
                        onClick={() => undo(x.entry_id)}
                      >
                        {t("my.undo")}
                      </button>
                    ) : null}
                  </td>
                </tr>
              ))}
              {list.data.length ? null : (
                <tr>
                  <td colSpan={7}>{t("my.none")}</td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      ) : null}
      {spent.data && spent.data.spending.length ? (
        <div className="table-scroll">
          <table className="grid">
            <caption>{t("my.byCategory")}</caption>
            <thead>
              <tr>
                <th scope="col">{t("my.category")}</th>
                <th scope="col" className="num">
                  {t("my.amount")}
                </th>
              </tr>
            </thead>
            <tbody>
              {spent.data.spending.map((c) => (
                <tr key={c.account_id}>
                  <td>{c.name}</td>
                  <td className="num">{formatAmount(c.amount, locale)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </Page>
  );
}
