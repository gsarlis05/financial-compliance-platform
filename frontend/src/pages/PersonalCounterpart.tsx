// "From my business" (M5-3): opt-in suggestions of business payments to the owner, recorded in
// the personal books only when confirmed here. Nothing is recorded automatically.
import { useState } from "react";
import { useWorkspaces, useEntities } from "../api/hooks";
import {
  type CounterpartLink,
  useBusinessAccounts,
  useBusinessLedger,
  useCounterpartDecisions,
  useCounterpartLinks,
  useCounterpartMutations,
} from "../api/counterpart";
import type { PersonalAccount } from "../api/personal";
import { Loading, ProblemMessage } from "../components/common";
import { useI18n } from "../i18n/I18n";
import { formatAmount } from "../money";

const today = () => new Date().toISOString().slice(0, 10);

function Suggestions({ link }: { link: CounterpartLink }) {
  const { t, locale } = useI18n();
  const ledger = useBusinessLedger(link, today());
  const decisions = useCounterpartDecisions(link.id);
  const m = useCounterpartMutations();
  if (ledger.isPending || decisions.isPending) return <Loading />;
  if (!ledger.data) return <p className="muted">{t("biz.noAccess")}</p>;
  const seen = new Set((decisions.data ?? []).map((d) => d.business_entry_id));
  const open = ledger.data.lines.filter(
    (ln) => ln.debit !== "0.00" && !seen.has(ln.entry_id),
  );
  if (open.length === 0) return <p className="muted">{t("biz.none")}</p>;
  return (
    <div className="table-scroll">
      <table className="grid">
        <caption>
          {t("biz.suggestions")}: {link.label}
        </caption>
        <thead>
          <tr>
            <th scope="col">{t("my.date")}</th>
            <th scope="col">{t("my.description")}</th>
            <th scope="col" className="num">
              {t("my.amount")}
            </th>
            <th scope="col">
              <span className="visually-hidden">{t("biz.actions")}</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {open.map((ln) => {
            const body = {
              business_entry_id: ln.entry_id,
              date: ln.accounting_date,
              amount: ln.debit,
              description: `${link.label}: ${ln.description}`.slice(0, 300),
            };
            return (
              <tr key={ln.entry_id}>
                <td>{ln.accounting_date}</td>
                <td>{ln.description}</td>
                <td className="num">{formatAmount(ln.debit, locale)}</td>
                <td>
                  <button
                    type="button"
                    className="primary"
                    disabled={m.decide.isPending}
                    onClick={() =>
                      m.decide.mutate({ id: link.id, action: "confirm", body })
                    }
                  >
                    {t("biz.confirm")}
                  </button>{" "}
                  <button
                    type="button"
                    disabled={m.decide.isPending}
                    onClick={() =>
                      m.decide.mutate({ id: link.id, action: "dismiss", body })
                    }
                  >
                    {t("biz.dismiss")}
                  </button>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      <ProblemMessage error={m.decide.error} />
    </div>
  );
}

function LinkForm({ accounts }: { accounts: PersonalAccount[] }) {
  const { t } = useI18n();
  const m = useCounterpartMutations();
  const workspaces = useWorkspaces();
  const businesses = (workspaces.data ?? []).filter(
    (w) => w.kind === "BUSINESS",
  );
  const [form, setForm] = useState({
    business_slug: "",
    business_entity_id: "",
    business_account_id: "",
    account_id: "",
    category_id: "",
    since: `${today().slice(0, 4)}-01-01`,
  });
  const entities = useEntities(form.business_slug);
  const bizAccounts = useBusinessAccounts(
    form.business_slug,
    form.business_entity_id,
  );
  const postable = (bizAccounts.data ?? []).filter(
    (a) => a.is_postable && a.status === "ACTIVE",
  );
  if (businesses.length === 0) return null;
  const ws = businesses.find((w) => w.slug === form.business_slug);
  const account = postable.find((a) => a.id === form.business_account_id);
  const save = () =>
    m.link.mutate(
      {
        ...form,
        label: `${ws?.name ?? ""} · ${account?.code ?? ""} ${account?.name ?? ""}`,
      },
      {
        onSuccess: () =>
          setForm({ ...form, business_account_id: "", account_id: "" }),
      },
    );
  return (
    <>
      <h3>{t("biz.newLink")}</h3>
      <div className="form inline">
        <label>
          {t("biz.business")}
          <select
            value={form.business_slug}
            onChange={(e) =>
              setForm({
                ...form,
                business_slug: e.target.value,
                business_entity_id: "",
                business_account_id: "",
              })
            }
          >
            <option value="">—</option>
            {businesses.map((w) => (
              <option key={w.slug} value={w.slug}>
                {/* Same-named workspaces are told apart by their address. */}
                {businesses.filter((o) => o.name === w.name).length > 1
                  ? `${w.name} (${w.slug})`
                  : w.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          {t("ws.entity")}
          <select
            value={form.business_entity_id}
            onChange={(e) =>
              setForm({
                ...form,
                business_entity_id: e.target.value,
                business_account_id: "",
              })
            }
          >
            <option value="">—</option>
            {(entities.data ?? []).map((e) => (
              <option key={e.id} value={e.id}>
                {e.legal_name}
              </option>
            ))}
          </select>
        </label>
        <label>
          {t("biz.businessAccount")}
          <select
            value={form.business_account_id}
            onChange={(e) =>
              setForm({ ...form, business_account_id: e.target.value })
            }
          >
            <option value="">—</option>
            {postable.map((a) => (
              <option key={a.id} value={a.id}>
                {a.code} {a.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          {t("biz.into")}
          <select
            value={form.account_id}
            onChange={(e) => setForm({ ...form, account_id: e.target.value })}
          >
            <option value="">—</option>
            {accounts
              .filter((a) => a.type === "ASSET")
              .map((a) => (
                <option key={a.id} value={a.id}>
                  {a.name}
                </option>
              ))}
          </select>
        </label>
        <label>
          {t("biz.as")}
          <select
            value={form.category_id}
            onChange={(e) => setForm({ ...form, category_id: e.target.value })}
          >
            <option value="">—</option>
            {accounts
              .filter((a) => a.type === "INCOME")
              .map((a) => (
                <option key={a.id} value={a.id}>
                  {a.name}
                </option>
              ))}
          </select>
        </label>
        <label>
          {t("biz.since")}
          <input
            type="date"
            value={form.since}
            onChange={(e) => setForm({ ...form, since: e.target.value })}
          />
        </label>
        <button
          type="button"
          disabled={
            !form.business_account_id ||
            !form.account_id ||
            !form.category_id ||
            !form.since ||
            m.link.isPending
          }
          onClick={save}
        >
          {t("biz.link")}
        </button>
      </div>
      <ProblemMessage error={m.link.error} />
    </>
  );
}

export function CounterpartSection({
  accounts,
}: {
  accounts: PersonalAccount[];
}) {
  const { t } = useI18n();
  const links = useCounterpartLinks();
  const m = useCounterpartMutations();
  return (
    <section className="card" aria-labelledby="biz-title">
      <h2 id="biz-title">{t("biz.title")}</h2>
      <p className="muted">{t("biz.text")}</p>
      {links.isPending ? <Loading /> : null}
      <ProblemMessage error={links.error ?? m.revoke.error} />
      {(links.data ?? []).map((link) => (
        <div key={link.id}>
          <h3>{link.label}</h3>
          <button
            type="button"
            className="link-button"
            disabled={m.revoke.isPending}
            onClick={() => m.revoke.mutate(link.id)}
          >
            {t("biz.revoke")}
          </button>
          <Suggestions link={link} />
        </div>
      ))}
      <LinkForm accounts={accounts} />
    </section>
  );
}
