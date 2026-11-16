import { NavLink, Outlet, useNavigate, useParams } from "react-router";
import { useEntities, useMe, useWorkspace, useWorkspaces } from "../api/hooks";
import { useI18n } from "../i18n/I18n";
import type { Locale, MessageKey } from "../i18n/messages";

function csrf(): string {
  const match = document.cookie.split("; ").find((c) => c.startsWith("__Host-fcp_csrftoken="));
  return match ? decodeURIComponent(match.split("=")[1] ?? "") : "";
}

/** Workspace switcher. Each workspace kind has its own colour and label, so the user always
 * sees whether they are in personal or business books (doc 11 §2). */
function WorkspaceSwitcher() {
  const { t } = useI18n();
  const { slug = "" } = useParams();
  const navigate = useNavigate();
  const workspaces = useWorkspaces();
  const current = useWorkspace(slug);
  return (
    <div className="switcher">
      {current.data ? (
        <span className={`kind kind-${current.data.kind.toLowerCase()}`} aria-label={t("ws.current")}>
          {t(`kind.${current.data.kind}` as MessageKey)}
        </span>
      ) : null}
      <label>
        <span className="visually-hidden">{t("ws.switch")}</span>
        <select
          value={slug}
          onChange={(e) => {
            void navigate(e.target.value ? `/w/${e.target.value}` : "/");
          }}
        >
          <option value="">{t("ws.title")}</option>
          {(workspaces.data ?? []).map((w) => (
            <option key={w.slug} value={w.slug}>
              {w.name} · {t(`kind.${w.kind}` as MessageKey)}
            </option>
          ))}
        </select>
      </label>
    </div>
  );
}

function EntityPicker() {
  const { t } = useI18n();
  const { slug = "", entityId = "" } = useParams();
  const navigate = useNavigate();
  const entities = useEntities(slug);
  if (!slug || (entities.data?.length ?? 0) < 2) {
    return null;
  }
  return (
    <label className="entity-picker">
      <span>{t("ws.entity")}</span>
      <select value={entityId} onChange={(e) => void navigate(`/w/${slug}/e/${e.target.value}/entries`)}>
        {(entities.data ?? []).map((e) => (
          <option key={e.id} value={e.id}>
            {e.legal_name}
          </option>
        ))}
      </select>
    </label>
  );
}

export function Layout() {
  const { t, locale, setLocale } = useI18n();
  const me = useMe();
  const { slug, entityId } = useParams();
  const base = slug && entityId ? `/w/${slug}/e/${entityId}` : null;
  const links: [string, MessageKey][] = base
    ? [
        [`${base}/entries`, "nav.entries"],
        [`${base}/approvals`, "nav.approvals"],
        [`${base}/accounts`, "nav.accounts"],
        [`${base}/periods`, "nav.periods"],
        [`${base}/trial-balance`, "nav.trialBalance"],
        [`/w/${slug ?? ""}/e/${entityId ?? ""}/integrity`, "nav.integrity"],
      ]
    : [];
  return (
    <div className="shell">
      <a className="skip-link" href="#main">
        Skip to content
      </a>
      <header className="topbar">
        <NavLink to="/" className="brand">
          {t("app.name")}
        </NavLink>
        <WorkspaceSwitcher />
        <EntityPicker />
        <div className="topbar-right">
          <label>
            <span className="visually-hidden">{t("app.language")}</span>
            <select value={locale} onChange={(e) => setLocale(e.target.value as Locale)}>
              <option value="en">English</option>
              <option value="el">Ελληνικά</option>
            </select>
          </label>
          {me.data ? <span className="muted">{me.data.display_name || me.data.email}</span> : null}
          <form method="post" action="/auth/logout">
            <input type="hidden" name="csrfmiddlewaretoken" value={csrf()} />
            <button type="submit" className="link-button">
              {t("app.signOut")}
            </button>
          </form>
        </div>
      </header>
      {links.length ? (
        <nav aria-label="Main" className="tabs">
          {links.map(([to, label]) => (
            <NavLink key={to} to={to}>
              {t(label)}
            </NavLink>
          ))}
        </nav>
      ) : null}
      <main id="main">
        <Outlet />
      </main>
    </div>
  );
}
