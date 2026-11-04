import { type KeyboardEvent, useEffect, useRef, useState } from "react";
import {
  NavLink,
  Outlet,
  useLocation,
  useNavigate,
  useParams,
} from "react-router";
import { useEntities, useMe, useWorkspace, useWorkspaces } from "../api/hooks";
import { useI18n } from "../i18n/I18n";
import type { Locale, MessageKey } from "../i18n/messages";

function csrf(): string {
  const match = document.cookie
    .split("; ")
    .find((c) => c.startsWith("__Host-fcp_csrftoken="));
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
        <span
          className={`kind kind-${current.data.kind.toLowerCase()}`}
          aria-label={t("ws.current")}
        >
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
      <select
        value={entityId}
        onChange={(e) =>
          void navigate(`/w/${slug}/e/${e.target.value}/entries`)
        }
      >
        {(entities.data ?? []).map((e) => (
          <option key={e.id} value={e.id}>
            {e.legal_name}
          </option>
        ))}
      </select>
    </label>
  );
}

type NavGroupSpec = { label: MessageKey; links: [string, MessageKey][] };

/** One navigation group: a button that shows or hides its links (WAI-ARIA disclosure
 * navigation). Arrow keys move between links, Escape closes the group and returns focus to its
 * button, and clicking elsewhere or following a link closes it. */
function NavGroup({
  group,
  open,
  onToggle,
}: {
  group: NavGroupSpec;
  open: boolean;
  onToggle: (open: boolean) => void;
}) {
  const { t } = useI18n();
  const { pathname } = useLocation();
  const button = useRef<HTMLButtonElement>(null);
  const list = useRef<HTMLUListElement>(null);
  const id = `nav-${group.label.replace(/\W/g, "-")}`;
  const current = group.links.some(
    ([to]) => pathname === to || pathname.startsWith(`${to}/`),
  );
  const links = () => Array.from(list.current?.querySelectorAll("a") ?? []);
  const move = (event: KeyboardEvent, step: number | "first" | "last") => {
    const items = links();
    const index = items.indexOf(document.activeElement as HTMLAnchorElement);
    const next =
      step === "first"
        ? 0
        : step === "last"
          ? items.length - 1
          : (index + step + items.length) % items.length;
    event.preventDefault();
    items[next]?.focus();
  };
  const onKeyDown = (event: KeyboardEvent) => {
    if (event.key === "Escape" && open) {
      onToggle(false);
      button.current?.focus();
    } else if (event.key === "ArrowDown") {
      if (!open) {
        onToggle(true);
        requestAnimationFrame(() => links()[0]?.focus());
        event.preventDefault();
      } else {
        move(event, document.activeElement === button.current ? "first" : 1);
      }
    } else if (event.key === "ArrowUp" && open) {
      move(event, -1);
    } else if (
      event.key === "Home" &&
      open &&
      document.activeElement !== button.current
    ) {
      move(event, "first");
    } else if (
      event.key === "End" &&
      open &&
      document.activeElement !== button.current
    ) {
      move(event, "last");
    }
  };
  return (
    <li
      className={`nav-group${current ? " current" : ""}`}
      onKeyDown={onKeyDown}
    >
      <button
        ref={button}
        type="button"
        aria-expanded={open}
        aria-controls={id}
        onClick={() => onToggle(!open)}
      >
        {t(group.label)} <span aria-hidden="true">▾</span>
      </button>
      <ul id={id} ref={list} hidden={!open}>
        {group.links.map(([to, label]) => (
          <li key={to}>
            <NavLink to={to} onClick={() => onToggle(false)}>
              {t(label)}
            </NavLink>
          </li>
        ))}
      </ul>
    </li>
  );
}

function MainNav({ base }: { base: string }) {
  const { t } = useI18n();
  const { pathname } = useLocation();
  // The open group belongs to the page it was opened on, so navigating closes it.
  const [opened, setOpened] = useState<{ label: string; path: string } | null>(
    null,
  );
  const open = opened?.path === pathname ? opened.label : null;
  const setOpen = (label: string | null) =>
    setOpened(label ? { label, path: pathname } : null);
  const nav = useRef<HTMLElement>(null);
  const groups: NavGroupSpec[] = [
    {
      label: "nav.group.bookkeeping",
      links: [
        [`${base}/entries`, "nav.entries"],
        [`${base}/approvals`, "nav.approvals"],
        [`${base}/bank`, "nav.bank"],
      ],
    },
    {
      label: "nav.group.parties",
      links: [
        [`${base}/counterparties`, "nav.counterparties"],
        [`${base}/receivables`, "nav.receivables"],
      ],
    },
    {
      label: "nav.group.planning",
      links: [
        [`${base}/cash-forecast`, "nav.cashForecast"],
        [`${base}/commitments`, "nav.commitments"],
      ],
    },
    {
      label: "nav.group.reports",
      links: [
        [`${base}/trial-balance`, "nav.trialBalance"],
        [`${base}/statements`, "nav.statements"],
      ],
    },
    {
      label: "nav.group.setup",
      links: [
        [`${base}/accounts`, "nav.accounts"],
        [`${base}/dimensions`, "nav.dimensions"],
        [`${base}/mapping`, "nav.mapping"],
        [`${base}/periods`, "nav.periods"],
      ],
    },
    {
      label: "nav.group.controls",
      links: [[`${base}/integrity`, "nav.integrity"]],
    },
  ];
  useEffect(() => {
    if (open === null) {
      return;
    }
    const close = (event: MouseEvent) => {
      if (!nav.current?.contains(event.target as Node)) {
        setOpened(null);
      }
    };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [open]);
  return (
    <nav aria-label={t("nav.main")} className="main-nav" ref={nav}>
      <ul>
        {groups.map((group) => (
          <NavGroup
            key={group.label}
            group={group}
            open={open === group.label}
            onToggle={(next) => setOpen(next ? group.label : null)}
          />
        ))}
      </ul>
    </nav>
  );
}

export function Layout() {
  const { t, locale, setLocale } = useI18n();
  const me = useMe();
  const { slug, entityId } = useParams();
  const base = slug && entityId ? `/w/${slug}/e/${entityId}` : null;
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
            <select
              value={locale}
              onChange={(e) => setLocale(e.target.value as Locale)}
            >
              <option value="en">English</option>
              <option value="el">Ελληνικά</option>
            </select>
          </label>
          {me.data ? (
            <span className="muted">
              {me.data.display_name || me.data.email}
            </span>
          ) : null}
          <form method="post" action="/auth/logout">
            <input type="hidden" name="csrfmiddlewaretoken" value={csrf()} />
            <button type="submit" className="link-button">
              {t("app.signOut")}
            </button>
          </form>
        </div>
      </header>
      {base ? <MainNav base={base} /> : null}
      <main id="main">
        <Outlet />
      </main>
    </div>
  );
}
