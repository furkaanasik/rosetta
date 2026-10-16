import type { CSSProperties, ReactNode } from "react";
import { cx } from "./cx";

/** Static placeholder block (no shimmer: calm while content loads). */
export function Skeleton({ width, height = 12, className, style }: { width?: number | string; height?: number | string; className?: string; style?: CSSProperties }) {
  return <span className={cx("skeleton", className)} style={{ width, height, ...style }} aria-hidden="true" />;
}

/** A few text-line skeletons, the last one shorter — for paragraphs and lists. */
export function SkeletonLines({ lines = 4, className }: { lines?: number; className?: string }) {
  return (
    <span className={cx("skeleton-lines", className)} aria-hidden="true">
      {Array.from({ length: lines }, (_, i) => (
        <Skeleton key={i} width={i === lines - 1 ? "62%" : "100%"} />
      ))}
    </span>
  );
}

interface EmptyStateProps {
  icon?: ReactNode;
  title: string;
  children?: ReactNode;
  action?: ReactNode;
  className?: string;
  /** "compact" for side panels, default for full areas. */
  size?: "default" | "compact";
}

export function EmptyState({ icon, title, children, action, className, size = "default" }: EmptyStateProps) {
  return (
    <div className={cx("empty-state", size === "compact" && "empty-state--compact", className)}>
      {icon && (
        <span className="empty-state__icon" aria-hidden="true">
          {icon}
        </span>
      )}
      <p className="empty-state__title">{title}</p>
      {children && <div className="empty-state__body">{children}</div>}
      {action && <div className="empty-state__action">{action}</div>}
    </div>
  );
}

/** Keyboard shortcut badge. */
export function Kbd({ children }: { children: ReactNode }) {
  return <kbd className="kbd">{children}</kbd>;
}

interface ProgressProps {
  value: number;
  max: number;
  label: string;
  tone?: "accent" | "sage" | "amber" | "danger";
  /** Animated strip when the amount of work isn't known yet. */
  indeterminate?: boolean;
}

/** Thin progress bar (native <progress> semantics, custom look). */
export function Progress({ value, max, label, tone = "accent", indeterminate = false }: ProgressProps) {
  const pct = max > 0 ? Math.min(100, Math.max(0, (value / max) * 100)) : 0;
  return (
    <div
      className={cx("progress", `progress--${tone}`, indeterminate && "progress--indeterminate")}
      role="progressbar"
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={max}
      aria-valuenow={indeterminate ? undefined : value}
    >
      <span className="progress__bar" style={indeterminate ? undefined : { width: `${pct}%` }} />
    </div>
  );
}

/** Small status pill. */
export function Badge({ tone = "neutral", children }: { tone?: "neutral" | "accent" | "sage" | "amber" | "danger"; children: ReactNode }) {
  return <span className={cx("badge", `badge--${tone}`)}>{children}</span>;
}
