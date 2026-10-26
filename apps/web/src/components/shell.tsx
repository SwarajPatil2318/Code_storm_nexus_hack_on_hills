"use client";
import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";
import { workspaceHref } from "@/lib/workspace-context";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  ArrowUpRight,
  ChevronRight,
  Command,
  Hexagon,
  Menu,
  Search,
  Shield,
  X,
  LogOut,
} from "lucide-react";
import { AuthProvider, useAuth } from "./auth-provider";
import { permittedRoute, roleLabels, type OperatorSession } from "@/lib/auth-types";
import { navigation } from "@/lib/navigation";
import { ConnectivityProvider, useConnectivity } from "./connectivity";
import { Badge, Dialog } from "./ui";
function Header({ onMenu }: { onMenu: () => void }) {
  const { session, logout, loggingOut } = useAuth();
  const [logoutError, setLogoutError] = useState("");
  const pathname = usePathname();
  const contextQuery = useSearchParams();
  const page = navigation.find(
    (item) =>
      item.href === pathname ||
      (item.href === "/evaluations" && pathname.startsWith("/evaluations/")),
  );
  const connection = useConnectivity();
  const [searchOpen, setSearchOpen] = useState(false);
  const [query, setQuery] = useState("");
  useEffect(() => {
    const listener = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key === "k") {
        event.preventDefault();
        setSearchOpen((value) => !value);
      }
    };
    window.addEventListener("keydown", listener);
    return () => window.removeEventListener("keydown", listener);
  }, []);
  const results = navigation.filter(
    (item) =>
      permittedRoute(session.user.role, item.href) &&
      `${item.label} ${item.description}`.toLowerCase().includes(query.toLowerCase()),
  );
  return (
    <>
      <header className="header">
        <div className="breadcrumbs">
          <button className="icon-button mobile-only" onClick={onMenu} aria-label="Open navigation">
            <Menu size={20} />
          </button>
          <span className="breadcrumb-workspace">Workspace</span>
          <ChevronRight size={13} />
          <span>{page?.label || "Page not found"}</span>
        </div>
        <div className="header-actions">
          <button
            className="search-trigger"
            onClick={() => setSearchOpen(true)}
            aria-label="Search workspace"
          >
            <Search size={15} />
            <span>Search workspace</span>
            <kbd>⌘ K</kbd>
          </button>
          <div className="header-divider" />
          <Link
            href="/settings"
            className="connection-link"
            aria-label={`Backend ${connection.status}. View diagnostics`}
          >
            <span role="status" aria-live="polite">
              <Badge
                tone={
                  connection.status === "online"
                    ? "green"
                    : connection.status === "error"
                      ? "red"
                      : "neutral"
                }
                dot
              >
                API {connection.status}
              </Badge>
            </span>
          </Link>
          <Link className="operator-identity" href="/login" aria-label="Switch operator identity">
            <span className={`role-dot role-${session.user.role}`} />
            <span>{roleLabels[session.user.role]}</span>
          </Link>
          <button
            className="icon-button"
            aria-label="Sign out"
            disabled={loggingOut}
            onClick={() =>
              void logout().catch(() => setLogoutError("Sign out failed. Please try again."))
            }
          >
            <LogOut size={17} />
          </button>
          {logoutError && (
            <span className="header-error" role="alert">
              {logoutError}
            </span>
          )}
        </div>
      </header>
      <Dialog open={searchOpen} onClose={() => setSearchOpen(false)} title="Search workspace">
        <div className="search-input">
          <Search size={18} />
          <input
            autoFocus
            placeholder="Find a page…"
            aria-label="Find a page"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
          />
        </div>
        <div className="search-results">
          {results.map((item) => (
            <Link
              href={workspaceHref(item.href, pathname, contextQuery.toString())}
              key={item.href}
              onClick={() => {
                setSearchOpen(false);
                setQuery("");
              }}
            >
              <item.icon size={18} />
              <span>
                <strong>{item.label}</strong>
                <small>{item.description}</small>
              </span>
              <ArrowUpRight size={16} />
            </Link>
          ))}
          {results.length === 0 && <p>No pages match your search.</p>}
        </div>
      </Dialog>
    </>
  );
}
function Sidebar({ open, close }: { open: boolean; close: () => void }) {
  const { session } = useAuth();
  const path = usePathname();
  const contextQuery = useSearchParams();
  const ref = useRef<HTMLElement>(null);
  useEffect(() => {
    if (!open) return;
    const previous = document.activeElement as HTMLElement | null;
    ref.current?.querySelector<HTMLElement>('a[aria-current="page"]')?.focus();
    const handleKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        close();
      }
      if (event.key !== "Tab") return;
      const elements = Array.from(
        ref.current?.querySelectorAll<HTMLElement>("a[href], button:not([disabled]), summary") ||
          [],
      );
      const visible = elements.filter((el) => el.getClientRects().length);
      const first = visible[0];
      const last = visible[visible.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last?.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first?.focus();
      }
    };
    const handleResize = () => {
      if (window.innerWidth > 900) close();
    };
    document.addEventListener("keydown", handleKey);
    window.addEventListener("resize", handleResize);
    return () => {
      document.removeEventListener("keydown", handleKey);
      window.removeEventListener("resize", handleResize);
      previous?.focus();
    };
  }, [open, close]);
  return (
    <>
      {open && (
        <button className="sidebar-backdrop" aria-label="Close navigation" onClick={close} />
      )}
      <aside
        ref={ref}
        className={`sidebar ${open ? "sidebar-open" : ""}`}
        aria-label="Main navigation"
        role={open ? "dialog" : "complementary"}
        aria-modal={open || undefined}
      >
        <div className="brand-row">
          <Link className="brand" href="/" onClick={close}>
            <span className="brand-symbol">
              <Hexagon size={31} strokeWidth={1.7} />
              <span />
            </span>
            NEXUS<span className="brand-period">.</span>
          </Link>
          <button className="icon-button mobile-only" onClick={close} aria-label="Close navigation">
            <X size={20} />
          </button>
        </div>
        <div className="workspace-switch">
          <span className="workspace-icon">
            <Shield size={17} />
          </span>
          <div>
            <strong>{session.user.display_name}</strong>
            <small>{roleLabels[session.user.role]}</small>
          </div>
        </div>
        <div className="nav-group-label">PLATFORM</div>
        <nav>
          {navigation
            .filter(
              (item) =>
                permittedRoute(session.user.role, item.href) &&
                [
                  "/",
                  "/evaluations",
                  "/attack-lab",
                  "/defence-vault",
                  "/x-ray",
                  "/proof-vault",
                  "/assurance-center",
                ].includes(item.href),
            )
            .map((item) => (
              <Link
                href={workspaceHref(item.href, path, contextQuery.toString())}
                key={item.href}
                onClick={close}
                aria-current={
                  path === item.href ||
                  (item.href === "/evaluations" && path.startsWith("/evaluations/"))
                    ? "page"
                    : undefined
                }
                className={`nav-item ${path === item.href || (item.href === "/evaluations" && path.startsWith("/evaluations/")) ? "active" : ""}`}
              >
                <item.icon size={18} strokeWidth={1.7} />
                <span>{item.label}</span>
              </Link>
            ))}
          <details
            className="nav-specialist"
            open={
              ![
                "/",
                "/evaluations",
                "/attack-lab",
                "/defence-vault",
                "/x-ray",
                "/proof-vault",
                "/assurance-center",
              ].includes(path) && !path.startsWith("/evaluations/")
            }
          >
            <summary>Specialist tools</summary>
            {navigation
              .filter(
                (item) =>
                  permittedRoute(session.user.role, item.href) &&
                  ![
                    "/",
                    "/evaluations",
                    "/attack-lab",
                    "/defence-vault",
                    "/x-ray",
                    "/proof-vault",
                    "/assurance-center",
                  ].includes(item.href),
              )
              .map((item) => (
                <Link
                  href={workspaceHref(item.href, path, contextQuery.toString())}
                  key={item.href}
                  onClick={close}
                  aria-current={path === item.href ? "page" : undefined}
                  className={`nav-item ${path === item.href ? "active" : ""}`}
                >
                  <item.icon size={18} strokeWidth={1.7} />
                  <span>{item.label}</span>
                </Link>
              ))}
          </details>
        </nav>
        <div className="sidebar-bottom">
          <div className="foundation-card">
            <span className="foundation-label">
              <span className="small-marker" />
              LIGHT FORENSIC INTELLIGENCE
            </span>
            <strong>Every claim has a source.</strong>
            <p>Inspect measured outcomes and the evidence behind them.</p>
            <Link href="/settings">
              View environment <ArrowUpRight size={14} />
            </Link>
          </div>
          <div className="sidebar-footer">
            <span className="tiny-logo">
              <Command size={15} />
            </span>
            <span>NEXUS Platform</span>
            <span>v0.1.0</span>
          </div>
        </div>
      </aside>
    </>
  );
}
function ShellContent({ children }: { children: React.ReactNode }) {
  const [menuOpen, setMenuOpen] = useState(false);
  const closeMenu = useCallback(() => setMenuOpen(false), []);
  return (
    <ConnectivityProvider>
      <a className="skip-link" href="#main-content">
        Skip to content
      </a>
      <Sidebar open={menuOpen} close={closeMenu} />
      <div className="app-area" inert={menuOpen}>
        <Header onMenu={() => setMenuOpen(true)} />
        <main id="main-content" tabIndex={-1}>
          {children}
        </main>
        <footer className="main-footer">
          <span>
            NEXUS <span className="footer-dot">/</span> Adversarial AI safety infrastructure
          </span>
          <span>Light Forensic Intelligence</span>
        </footer>
      </div>
    </ConnectivityProvider>
  );
}

export function Shell({
  children,
  session,
}: {
  children: React.ReactNode;
  session: OperatorSession;
}) {
  return (
    <AuthProvider session={session}>
      <ShellContent>{children}</ShellContent>
    </AuthProvider>
  );
}
