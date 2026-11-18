// Small shared pieces of the Rival design system: brand marks, motion helpers and common building blocks.

import { useEffect, useLayoutEffect, useRef, useState, type ReactNode } from "react";

export const prefersReducedMotion = () =>
  typeof window !== "undefined" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

/** The "rival." wordmark. */
export function Wordmark({ className = "" }: { className?: string }) {
  return (
    <span className={`wordmark ${className}`} aria-label="Rival">
      rival<i aria-hidden>.</i>
    </span>
  );
}

export function DemoBanner() {
  return <div className="demo-banner">Demo · Devnet USDC only, no real money</div>;
}

export function Avatar({ name, size = "md" }: { name: string; size?: "sm" | "md" | "lg" }) {
  return (
    <span className={`avatar avatar-${size}`} aria-hidden>
      {name.trim().slice(0, 1).toUpperCase() || "?"}
    </span>
  );
}

/** Small uppercase label above a value or a section. */
export function Eyebrow({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <div className={`eyebrow ${className}`}>{children}</div>;
}

/** Placeholder blocks shown while something loads. */
export function Skeleton({ rows = 3, height = 64 }: { rows?: number; height?: number }) {
  return (
    <div className="skeleton-list" aria-busy="true" aria-label="Loading">
      {Array.from({ length: rows }, (_, i) => (
        <div key={i} className="skeleton" style={{ height }} />
      ))}
    </div>
  );
}

export function EmptyState(props: { icon?: ReactNode; title: string; text?: string; children?: ReactNode }) {
  return (
    <div className="empty">
      {props.icon && <div className="empty-icon">{props.icon}</div>}
      <div className="empty-title">{props.title}</div>
      {props.text && <p>{props.text}</p>}
      {props.children && <div className="empty-actions">{props.children}</div>}
    </div>
  );
}

/** Fades and lifts its children into place the first time they scroll into view. */
export function Reveal(props: { children: ReactNode; delay?: number; className?: string; as?: "div" | "section" | "li" }) {
  const ref = useRef<HTMLElement | null>(null);
  const [shown, setShown] = useState(prefersReducedMotion);
  useEffect(() => {
    const el = ref.current;
    if (!el || shown) return;
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((e) => e.isIntersecting)) {
          setShown(true);
          observer.disconnect();
        }
      },
      { rootMargin: "0px 0px -8% 0px", threshold: 0.12 },
    );
    observer.observe(el);
    return () => observer.disconnect();
  }, [shown]);
  const Tag = (props.as ?? "div") as "div";
  return (
    <Tag
      ref={ref as React.Ref<HTMLDivElement>}
      className={`reveal${shown ? " in" : ""} ${props.className ?? ""}`}
      style={props.delay ? { transitionDelay: `${props.delay}ms` } : undefined}
    >
      {props.children}
    </Tag>
  );
}

/**
 * Smooth re-ordering for lists (the leaderboard). Give each row `ref={flip(key)}`;
 * when a row's position changes between renders it glides to its new place.
 */
export function useFlip() {
  const nodes = useRef(new Map<string, HTMLElement>());
  const tops = useRef(new Map<string, number>());
  useLayoutEffect(() => {
    const still = prefersReducedMotion();
    const seen = new Map<string, number>();
    nodes.current.forEach((el, key) => {
      const top = el.offsetTop;
      const old = tops.current.get(key);
      seen.set(key, top);
      if (old !== undefined && old !== top && !still) {
        el.animate([{ transform: `translateY(${old - top}px)` }, { transform: "none" }], {
          duration: 520,
          easing: "cubic-bezier(0.22, 0.8, 0.2, 1)",
        });
      }
    });
    tops.current = seen;
  });
  return (key: string) => (el: HTMLElement | null) => {
    if (el) nodes.current.set(key, el);
    else nodes.current.delete(key);
  };
}

/** Closes a dialog on Escape. */
export function useEscape(onClose: () => void, enabled = true) {
  useEffect(() => {
    if (!enabled) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose, enabled]);
}
