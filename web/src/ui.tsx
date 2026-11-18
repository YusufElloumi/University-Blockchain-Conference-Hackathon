// Small shared pieces of the Rival design system: brand marks, motion helpers and common building blocks.

import { useEffect, useLayoutEffect, useRef, useState, type ReactNode } from "react";
import logoMark from "./assets/logo-mark.png";
import peakBlue from "./assets/logo-peak-blue.png";
import peakGreen from "./assets/logo-peak-green.png";

export const prefersReducedMotion = () =>
  typeof window !== "undefined" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

/** The Rival logo: the two-peak mark, followed by the "rival" wordmark unless `markOnly` is set. */
export function Wordmark({ className = "", markOnly = false }: { className?: string; markOnly?: boolean }) {
  return (
    <span className={`wordmark ${className}`} role="img" aria-label="Rival">
      <img className="wordmark-mark" src={logoMark} alt="" width={869} height={463} />
      {!markOnly && (
        <span aria-hidden>rival</span>
      )}
    </span>
  );
}

/** The exact shape of the path that winds between the logo's blue and green peaks (traced from the artwork). */
const LOGO_PATH_SHAPE =
  "M313.5 463.0 L313.5 459.5 L310.5 456.5 L307.5 453.5 L304.6 450.5 L301.9 447.5 L299.5 444.5 L296.7 441.5 L294.5 438.5 L291.9 435.5 L289.6 432.5 L287.5 429.5 L285.5 426.5 L283.6 423.5 L281.7 420.5 L280.5 417.5 L278.5 414.5 L276.8 411.5 L275.6 408.5 L274.5 405.5 L273.5 402.5 L272.5 399.5 L271.6 396.5 L270.6 393.5 L270.0 390.5 L269.5 387.5 L269.0 384.5 L268.6 381.5 L268.6 378.5 L268.6 375.5 L268.6 372.5 L268.9 369.5 L269.5 366.5 L269.8 363.5 L270.6 360.5 L271.5 357.5 L272.5 354.5 L273.5 351.5 L274.5 348.5 L275.6 345.5 L277.5 342.5 L278.6 339.5 L280.5 336.5 L282.5 333.5 L284.5 330.5 L286.5 327.5 L288.6 324.5 L290.9 321.5 L293.5 318.5 L296.5 315.5 L298.9 312.5 L301.8 309.5 L305.5 306.5 L308.5 303.5 L311.6 300.5 L315.5 297.5 L318.7 294.5 L322.5 291.5 L326.5 288.5 L330.5 285.5 L334.6 282.5 L338.6 279.5 L342.9 276.5 L347.5 273.5 L351.8 270.5 L356.6 267.5 L361.5 264.5 L366.0 261.5 L370.8 258.5 L375.7 255.5 L380.7 252.5 L385.8 249.5 L390.8 246.5 L395.8 243.5 L400.9 240.5 L405.9 237.5 L411.5 234.5 L416.5 231.5 L421.5 228.5 L425.8 225.5 L430.6 222.5 L435.5 219.5 L439.9 216.5 L444.5 213.5 L448.5 210.5 L452.5 207.5 L456.5 204.5 L459.5 201.5 L462.5 198.5 L465.5 195.5 L467.7 192.5 L470.5 189.5 L472.5 186.5 L473.8 183.5 L475.5 180.5 L476.5 177.5 L477.6 174.5 L478.5 171.5 L479.5 168.5 L480.5 165.5 L480.5 162.5 L480.8 159.5 L480.8 156.5 L480.8 153.5 L480.8 150.5 L480.8 147.5 L480.7 144.5 L480.6 141.5 L480.5 138.5 L479.7 135.5 L479.5 132.5 L479.5 129.5 L478.6 126.5 L478.5 123.5 L477.6 120.5 L476.8 117.5 L476.5 114.5 L475.6 111.5 L474.9 108.5 L474.5 105.5 L473.5 102.5 L472.7 99.5 L472.5 96.5 L471.6 93.5 L470.7 90.5 L469.7 87.5 L469.5 84.5 L468.5 81.5 L467.5 78.5 L466.7 75.5 L465.9 72.5 L465.5 69.5 L464.5 66.5 L463.5 63.5 L462.6 60.5 L461.6 57.5 L460.9 54.5 L460.5 51.5 L459.5 48.5 L458.5 45.5 L457.5 42.5 L456.9 39.5 L456.5 36.5 L455.5 33.5 L454.5 30.5 L453.5 27.5 L452.5 24.5 L451.5 21.5 L450.5 18.5 L449.5 15.5 L448.5 12.5 L447.5 9.5 L446.5 6.5 L445.5 3.5 L445.0 0.5 L444.5 3.5 L445.5 6.5 L446.5 9.5 L447.5 12.5 L448.5 15.5 L449.5 18.5 L450.5 21.5 L451.5 24.5 L452.5 27.5 L453.5 30.5 L454.5 33.5 L455.5 36.5 L458.1 39.5 L459.5 42.5 L461.4 45.5 L462.5 48.5 L464.5 51.5 L465.5 54.5 L467.5 57.5 L468.5 60.5 L470.5 63.5 L472.0 66.5 L473.5 69.5 L475.2 72.5 L476.5 75.5 L478.1 78.5 L479.5 81.5 L481.2 84.5 L482.5 87.5 L484.2 90.5 L485.5 93.5 L487.2 96.5 L488.5 99.5 L489.5 102.5 L491.5 105.5 L492.5 108.5 L494.4 111.5 L495.5 114.5 L497.2 117.5 L498.5 120.5 L499.5 123.5 L500.5 126.5 L502.3 129.5 L503.5 132.5 L504.5 135.5 L505.5 138.5 L507.1 141.5 L508.1 144.5 L508.5 147.5 L509.5 150.5 L510.5 153.5 L511.5 156.5 L512.4 159.5 L512.5 162.5 L513.5 165.5 L513.5 168.5 L513.5 171.5 L514.1 174.5 L514.1 177.5 L513.5 180.5 L513.5 183.5 L512.5 186.5 L512.2 189.5 L511.2 192.5 L509.5 195.5 L508.5 198.5 L506.5 201.5 L505.1 204.5 L502.5 207.5 L500.5 210.5 L498.1 213.5 L495.5 216.5 L492.4 219.5 L489.4 222.5 L485.5 225.5 L482.3 228.5 L478.5 231.5 L474.5 234.5 L470.5 237.5 L467.1 240.5 L463.1 243.5 L459.2 246.5 L455.1 249.5 L451.1 252.5 L447.2 255.5 L443.2 258.5 L439.3 261.5 L435.5 264.5 L431.5 267.5 L428.2 270.5 L424.5 273.5 L421.3 276.5 L418.0 279.5 L414.5 282.5 L411.5 285.5 L408.5 288.5 L406.1 291.5 L403.5 294.5 L401.2 297.5 L398.5 300.5 L396.5 303.5 L394.5 306.5 L393.3 309.5 L391.5 312.5 L390.4 315.5 L389.4 318.5 L388.5 321.5 L388.0 324.5 L387.5 327.5 L387.4 330.5 L387.4 333.5 L387.5 336.5 L388.3 339.5 L388.5 342.5 L389.5 345.5 L391.2 348.5 L392.5 351.5 L394.3 354.5 L396.1 357.5 L398.3 360.5 L400.5 363.5 L403.2 366.5 L405.5 369.5 L408.5 372.5 L411.5 375.5 L415.3 378.5 L418.5 381.5 L422.2 384.5 L425.5 387.5 L429.5 390.5 L433.5 393.5 L437.5 396.5 L441.5 399.5 L445.5 402.5 L450.0 405.5 L454.3 408.5 L458.5 411.5 L463.0 414.5 L467.5 417.5 L471.5 420.5 L476.5 423.5 L481.2 426.5 L485.5 429.5 L490.3 432.5 L495.2 435.5 L499.5 438.5 L504.5 441.5 L509.5 444.5 L514.4 447.5 L519.2 450.5 L524.3 453.5 L529.3 456.5 L534.2 459.5 L534.2 463.0 Z";

/**
 * The opening animation's logo. It opens close in on the mountain path being drawn in light, from
 * its foot to the summit, in exactly the shape it has in the logo. The view eases back as the two
 * peaks resolve around it; the light fades and leaves the finished mark, then the wordmark opens.
 */
export function IntroLogo() {
  return (
    <span className="intro-logo" aria-hidden>
      <span className="intro-mark">
        <img className="peak peak-blue" src={peakBlue} alt="" />
        <img className="peak peak-green" src={peakGreen} alt="" />
        <svg className="intro-route" viewBox="0 0 869 463">
          <defs>
            {/* A window that rises from the baseline, so the path is uncovered with a level edge from foot to summit. */}
            <clipPath id="route-reveal">
              <rect className="route-window" x="-40" y="0" width="949" height="463" />
            </clipPath>
          </defs>
          <path className="route-shape" d={LOGO_PATH_SHAPE} clipPath="url(#route-reveal)" />
        </svg>
      </span>
      <span className="intro-word">
        <span>rival</span>
      </span>
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
