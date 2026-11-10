// Engagements (M5-4). A business or personal workspace lets a firm in, within a scope and
// until a date; the firm assigns its people. The server enforces every rule.
import { useState } from "react";
import { NavLink, useParams } from "react-router";
import {
  type EngagementRole,
  type FirmEngagement,
  useClientEngagements,
  useEngagementMutations,
  useGrants,
  useMembers,
} from "../api/engagements";
import { useWorkspace } from "../api/hooks";
import { Loading, Page, ProblemMessage } from "../components/common";
import { useI18n } from "../i18n/I18n";
import type { MessageKey } from "../i18n/messages";

const ROLES: EngagementRole[] = ["accountant", "reviewer", "read_only"];
const inDays = (days: number) =>
  new Date(Date.now() + days * 86_400_000).toISOString().slice(0, 10);

function ClientView({ slug, personal }: { slug: string; personal: boolean }) {
  const { t } = useI18n();
  const grants = useGrants(slug, true);
  const m = useEngagementMutations(slug);
  const offered = personal ? (["read_only"] as EngagementRole[]) : ROLES;
  const [form, setForm] = useState({
    firm_slug: "",
    scope_roles: ["read_only"] as EngagementRole[],
    until: inDays(365),
  });
  const toggle = (role: EngagementRole) =>
    setForm({
      ...form,
      scope_roles: form.scope_roles.includes(role)
        ? form.scope_roles.filter((r) => r !== role)
        : [...form.scope_roles, role],
    });
  return (
    <>
      <p className="muted">{t("eng.clientText")}</p>
      <section className="card" aria-labelledby="eng-new">
        <h2 id="eng-new">{t("eng.grant")}</h2>
        <div className="form inline">
          <label>
            {t("eng.firm")}
            <input
              value={form.firm_slug}
              maxLength={64}
              onChange={(e) => setForm({ ...form, firm_slug: e.target.value })}
            />
          </label>
          <fieldset>
            <legend>{t("eng.scope")}</legend>
            {offered.map((role) => (
              <label key={role}>
                <input
                  type="checkbox"
                  checked={form.scope_roles.includes(role)}
                  onChange={() => toggle(role)}
                />{" "}
                {t(`role.${role}` as MessageKey)}
              </label>
            ))}
          </fieldset>
          <label>
            {t("eng.until")}
            <input
              type="date"
              value={form.until}
              onChange={(e) => setForm({ ...form, until: e.target.value })}
            />
          </label>
          <button
            type="button"
            className="primary"
            disabled={
              !form.firm_slug.trim() ||
              form.scope_roles.length === 0 ||
              !form.until ||
              m.grant.isPending
            }
            onClick={() =>
              m.grant.mutate(
                {
                  firm_slug: form.firm_slug.trim(),
                  scope_roles: form.scope_roles,
                  valid_until: `${form.until}T23:59:59Z`,
                },
                { onSuccess: () => setForm({ ...form, firm_slug: "" }) },
              )
            }
          >
            {t("eng.grantButton")}
          </button>
        </div>
        <ProblemMessage error={m.grant.error} />
      </section>
      {grants.isPending ? <Loading /> : null}
      <ProblemMessage error={grants.error ?? m.revoke.error} />
      {grants.data?.length ? (
        <div className="table-scroll">
          <table className="grid">
            <caption>{t("eng.grants")}</caption>
            <thead>
              <tr>
                <th scope="col">{t("eng.firm")}</th>
                <th scope="col">{t("eng.scope")}</th>
                <th scope="col">{t("eng.until")}</th>
                <th scope="col">{t("eng.status")}</th>
                <th scope="col">
                  <span className="visually-hidden">{t("eng.actions")}</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {grants.data.map((g) => (
                <tr key={g.id}>
                  <td>{g.firm_name}</td>
                  <td>
                    {g.scope_roles
                      .map((r) => t(`role.${r}` as MessageKey))
                      .join(", ")}
                  </td>
                  <td>{g.valid_until.slice(0, 10)}</td>
                  <td>{t(g.active ? "eng.active" : "eng.ended")}</td>
                  <td>
                    {g.active ? (
                      <button
                        type="button"
                        disabled={m.revoke.isPending}
                        onClick={() => {
                          if (window.confirm(t("eng.revokeConfirm")))
                            m.revoke.mutate(g.id);
                        }}
                      >
                        {t("eng.revoke")}
                      </button>
                    ) : null}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : grants.data ? (
        <p className="muted">{t("eng.noGrants")}</p>
      ) : null}
    </>
  );
}

function StaffCell({ slug, e }: { slug: string; e: FirmEngagement }) {
  const { t } = useI18n();
  const members = useMembers(slug, true);
  const m = useEngagementMutations(slug);
  const [pick, setPick] = useState("");
  const on = new Set(e.staff.map((s) => s.membership_id));
  const free = (members.data ?? []).filter(
    (x) => x.status === "ACTIVE" && !on.has(x.membership_id),
  );
  return (
    <>
      <ul className="plain">
        {e.staff.map((s) => (
          <li key={s.id}>
            {s.display_name || s.email}{" "}
            <button
              type="button"
              className="link-button"
              disabled={m.removeStaff.isPending}
              onClick={() => m.removeStaff.mutate(s.id)}
            >
              {t("eng.remove")}
            </button>
          </li>
        ))}
      </ul>
      <label>
        <span className="visually-hidden">
          {t("eng.assign")} {e.client_name}
        </span>
        <select value={pick} onChange={(ev) => setPick(ev.target.value)}>
          <option value="">—</option>
          {free.map((x) => (
            <option key={x.membership_id} value={x.membership_id}>
              {x.display_name || x.email}
            </option>
          ))}
        </select>
      </label>{" "}
      <button
        type="button"
        disabled={!pick || m.addStaff.isPending}
        onClick={() =>
          m.addStaff.mutate(
            { id: e.engagement_id, membershipId: pick },
            { onSuccess: () => setPick("") },
          )
        }
      >
        {t("eng.assign")}
      </button>
      <ProblemMessage error={m.addStaff.error ?? m.removeStaff.error} />
    </>
  );
}

function FirmView({ slug }: { slug: string }) {
  const { t } = useI18n();
  const list = useClientEngagements(slug, true);
  return (
    <>
      <p className="muted">
        {t("eng.firmText")} <code>{slug}</code>
      </p>
      {list.isPending ? <Loading /> : null}
      <ProblemMessage error={list.error} />
      {list.data?.length ? (
        <div className="table-scroll">
          <table className="grid">
            <caption>{t("eng.clients")}</caption>
            <thead>
              <tr>
                <th scope="col">{t("eng.client")}</th>
                <th scope="col">{t("eng.scope")}</th>
                <th scope="col">{t("eng.until")}</th>
                <th scope="col">{t("eng.staff")}</th>
              </tr>
            </thead>
            <tbody>
              {list.data.map((e) => (
                <tr key={e.engagement_id}>
                  <td>
                    <NavLink to={`/w/${e.client_slug}`}>
                      {e.client_name}
                    </NavLink>
                  </td>
                  <td>
                    {e.scope_roles
                      .map((r) => t(`role.${r}` as MessageKey))
                      .join(", ")}
                  </td>
                  <td>{e.valid_until.slice(0, 10)}</td>
                  <td>
                    <StaffCell slug={slug} e={e} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : list.data ? (
        <p className="muted">{t("eng.noClients")}</p>
      ) : null}
    </>
  );
}

export function EngagementsPage() {
  const { t } = useI18n();
  const { slug = "" } = useParams();
  const ws = useWorkspace(slug);
  const kind = ws.data?.kind;
  return (
    <Page title={t("nav.engagements")}>
      {!kind ? <Loading /> : null}
      {kind === "FIRM" ? <FirmView slug={slug} /> : null}
      {kind && kind !== "FIRM" ? (
        <ClientView slug={slug} personal={kind === "PERSONAL"} />
      ) : null}
    </Page>
  );
}
