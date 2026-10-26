"use client";
import { Children, useEffect, useRef, useState, type KeyboardEvent } from "react";
import { ArrowUpRight, Copy, Inbox, LoaderCircle, X, type LucideIcon } from "lucide-react";
import Link from "next/link";
export function Badge({
  children,
  tone = "neutral",
  dot = false,
}: {
  children: React.ReactNode;
  tone?: "neutral" | "green" | "red" | "blue" | "amber";
  dot?: boolean;
}) {
  return (
    <span className={`badge badge-${tone}`}>
      {dot && <span className="status-dot" />}
      {children}
    </span>
  );
}
export function Button({
  children,
  onClick,
  variant = "secondary",
  disabled = false,
  type = "button",
  className = "",
}: {
  children: React.ReactNode;
  onClick?: () => void;
  variant?: "primary" | "secondary" | "ghost";
  disabled?: boolean;
  type?: "button" | "submit";
  className?: string;
}) {
  return (
    <button
      type={type}
      onClick={onClick}
      disabled={disabled}
      className={`button button-${variant} ${className}`}
    >
      {children}
    </button>
  );
}
export function PageHeading({
  eyebrow,
  title,
  description,
  action,
}: {
  eyebrow: string;
  title: string;
  description: string;
  action?: React.ReactNode;
}) {
  return (
    <div className="page-heading">
      <div>
        <div className="eyebrow">{eyebrow}</div>
        <h1>{title}</h1>
        <p>{description}</p>
      </div>
      {action}
    </div>
  );
}
export function Panel({
  title,
  subtitle,
  action,
  children,
  className = "",
}: {
  title: string;
  subtitle?: string;
  action?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <section className={`panel ${className}`}>
      <div className="panel-heading">
        <div>
          <h2>{title}</h2>
          {subtitle && <p>{subtitle}</p>}
        </div>
        {action}
      </div>
      {children}
    </section>
  );
}
export function EmptyState({
  icon: Icon = Inbox,
  title,
  description,
  children,
}: {
  icon?: LucideIcon;
  title: string;
  description: string;
  children?: React.ReactNode;
}) {
  return (
    <div className="empty-state">
      <span className="empty-icon">
        <Icon size={23} strokeWidth={1.5} />
      </span>
      <h3>{title}</h3>
      <p>{description}</p>
      {children}
    </div>
  );
}
export function MetricCard({
  icon: Icon,
  label,
  detail,
  accent,
}: {
  icon: LucideIcon;
  label: string;
  detail: string;
  accent: string;
}) {
  return (
    <div className="metric-card">
      <div className="metric-top">
        <span>{label}</span>
        <Icon size={17} className={`text-${accent}`} />
      </div>
      <div className="metric-value">
        —<span>Awaiting evaluations</span>
      </div>
      <div className="metric-bottom">
        <span className={`small-marker marker-${accent}`} />
        {detail}
      </div>
    </div>
  );
}
export function TextLink({ href, children }: { href: string; children: React.ReactNode }) {
  return (
    <Link className="text-link" href={href}>
      {children}
      <ArrowUpRight size={14} />
    </Link>
  );
}
export function LoadingState({ text = "Loading workspace…" }: { text?: string }) {
  return (
    <div className="loading-state" role="status">
      <LoaderCircle className="spin" size={21} />
      <span>{text}</span>
    </div>
  );
}
export function Dialog({
  open,
  onClose,
  title,
  children,
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  children: React.ReactNode;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const node = ref.current;
    if (open && !node?.open) node?.showModal();
    else if (!open && node?.open) node.close();
  }, [open]);
  return (
    <dialog
      ref={ref}
      className="dialog"
      onKeyDown={trapDialogFocus}
      onCancel={onClose}
      onClick={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
      aria-label={title}
    >
      <div className="dialog-heading">
        <h2>{title}</h2>
        <button aria-label="Close dialog" className="icon-button" onClick={onClose}>
          <X size={20} />
        </button>
      </div>
      {children}
    </dialog>
  );
}
export function DataTable({
  columns,
  children,
  caption,
}: {
  columns: string[];
  children: React.ReactNode;
  caption: string;
}) {
  const [page, setPage] = useState(0);
  const [size, setSize] = useState(8);
  const rows = Children.toArray(children);
  const last = Math.max(0, Math.ceil(rows.length / size) - 1);
  const current = Math.min(page, last);
  return (
    <div className="data-table">
      <div className="table-scroll">
        <table>
          <caption className="sr-only">{caption}</caption>
          <thead>
            <tr>
              {columns.map((column) => (
                <th key={column} scope="col">
                  {column}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>{rows.slice(current * size, (current + 1) * size)}</tbody>
        </table>
      </div>
      {rows.length > 8 && (
        <div className="table-pagination" aria-label={`${caption} pagination`}>
          <span>
            {current * size + 1}–{Math.min((current + 1) * size, rows.length)} of {rows.length}
          </span>
          <label>
            Rows{" "}
            <select
              aria-label={`${caption} rows per page`}
              value={size}
              onChange={(e) => {
                setSize(Number(e.target.value));
                setPage(0);
              }}
            >
              <option value={8}>8</option>
              <option value={20}>20</option>
              <option value={Number.MAX_SAFE_INTEGER}>All available</option>
            </select>
          </label>
          <button
            className="button button-secondary"
            disabled={current === 0}
            onClick={() => setPage(current - 1)}
            aria-label={`Previous ${caption} page`}
          >
            Previous
          </button>
          <button
            className="button button-secondary"
            disabled={current >= last}
            onClick={() => setPage(current + 1)}
            aria-label={`Next ${caption} page`}
          >
            Next
          </button>
        </div>
      )}
    </div>
  );
}

export function trapDialogFocus(e: KeyboardEvent<HTMLDialogElement>) {
  if (e.key !== "Tab") return;
  const items = [
    ...e.currentTarget.querySelectorAll<HTMLElement>(
      "button:not([disabled]), a[href], summary, select:not([disabled]), input:not([disabled]), textarea:not([disabled]), [tabindex='0']",
    ),
  ].filter((item) => item.checkVisibility());
  const first = items[0],
    last = items[items.length - 1];
  if (e.shiftKey && document.activeElement === first) {
    e.preventDefault();
    last?.focus();
  } else if (!e.shiftKey && document.activeElement === last) {
    e.preventDefault();
    first?.focus();
  }
}

export function InspectorDrawer({
  title,
  onClose,
  children,
  closeLabel = "Close inspector",
}: {
  title: string;
  onClose: () => void;
  children: React.ReactNode;
  closeLabel?: string;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const prior = document.activeElement;
    ref.current?.showModal();
    return () => {
      if (prior instanceof HTMLElement && prior.isConnected) prior.focus();
    };
  }, []);
  return (
    <dialog
      ref={ref}
      className="inspector-drawer"
      aria-label={title}
      onKeyDown={trapDialogFocus}
      onCancel={(e) => {
        e.preventDefault();
        onClose();
      }}
    >
      <header>
        <div>
          <p className="eyebrow">EVIDENCE INSPECTOR</p>
          <h2>{title}</h2>
        </div>
        <button className="icon-button" aria-label={closeLabel} onClick={onClose}>
          <X size={20} />
        </button>
      </header>
      {children}
    </dialog>
  );
}

export function CopyValue({ value, label }: { value: string; label: string }) {
  const [message, setMessage] = useState("");
  async function copy() {
    try {
      await navigator.clipboard.writeText(value);
      setMessage("Copied");
    } catch {
      setMessage("Copy unavailable. Select the value to copy.");
    }
  }
  return (
    <span className="copy-value">
      <code>{value}</code>
      <button className="icon-button" aria-label={`Copy ${label}`} onClick={() => void copy()}>
        <Copy size={14} />
      </button>
      <span role="status">{message}</span>
    </span>
  );
}
