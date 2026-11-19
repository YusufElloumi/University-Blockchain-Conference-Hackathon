// Building blocks for the public website: the cinematic hero video, photography, the live product
// preview and the numbered "how it works" steps. Footage and stills are from Mixkit clips under the
// Mixkit Stock Video Free License (see web/src/assets/media/CREDITS.md).

import { useEffect, useRef, useState, type ReactNode } from "react";
import { Footprints } from "lucide-react";
import type { PlayerRow } from "./api";
import Leaderboard from "./Leaderboard";
import { hero1080, hero2160, hero480, hero720, heroPoster, type Picture } from "./media";
import { prefersReducedMotion, Reveal } from "./ui";

/** The three chapters of the hero loop and when each one ends (seconds). Six shots: hand wraps and
 *  shoes; a runner, a barbell and a basketball; then two people running side by side. */
const CHAPTERS = [
  { label: "Lace up", end: 3.6 },
  { label: "Show up", end: 11.2 },
  { label: "Find your rival", end: 14.6 },
];

/**
 * The hero film: a short, silent loop of people getting ready and getting after it. Shown in black and white under a dark shade
 * so the headline stays readable. People who prefer reduced motion get the still poster instead.
 */
export function HeroVideo() {
  const ref = useRef<HTMLVideoElement>(null);
  const still = prefersReducedMotion();
  const [time, setTime] = useState(0);

  useEffect(() => {
    const video = ref.current;
    if (!video || still) return;
    video.muted = true; // some browsers only autoplay when this is set from script
    video.play().catch(() => undefined); // autoplay refused (battery saver): the poster stays
    let frame = 0;
    const tick = () => {
      setTime(video.currentTime);
      frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [still]);

  return (
    <>
      <div className="film">
        {still ? (
          <img src={heroPoster} alt="" />
        ) : (
          <video ref={ref} poster={heroPoster} autoPlay muted loop playsInline preload="auto" aria-hidden tabIndex={-1}>
            {/* The browser takes the first file whose rule matches, so small screens never download the big ones. */}
            <source src={hero480} type="video/mp4" media="(max-width: 720px)" />
            <source src={hero720} type="video/mp4" media="(max-width: 1280px)" />
            <source src={hero1080} type="video/mp4" media="(max-width: 2400px)" />
            <source src={hero2160} type="video/mp4" />
          </video>
        )}
      </div>
      {!still && (
        <ol className="chapters" aria-hidden>
          {CHAPTERS.map((chapter, i) => {
            const start = i === 0 ? 0 : CHAPTERS[i - 1].end;
            const done = Math.min(1, Math.max(0, (time - start) / (chapter.end - start)));
            return (
              <li key={chapter.label} className={done > 0 && done < 1 ? "on" : ""}>
                <span>
                  <b>0{i + 1}</b> {chapter.label}
                </span>
                <i>
                  <u style={{ transform: `scaleX(${done})` }} />
                </i>
              </li>
            );
          })}
        </ol>
      )}
    </>
  );
}

/** A photograph in the site's treatment: black and white, deep contrast, a little grain. */
export function Photo(props: { photo: Picture; className?: string; eager?: boolean; sizes?: string; children?: ReactNode }) {
  const { photo } = props;
  return (
    <figure className={`photo ${props.className ?? ""}`}>
      <img
        src={photo.src}
        srcSet={photo.src4k ? `${photo.src} 1920w, ${photo.src4k} 3840w` : undefined}
        sizes={photo.src4k ? (props.sizes ?? "100vw") : undefined}
        alt={photo.alt}
        loading={props.eager ? "eager" : "lazy"}
        decoding="async"
      />
      {props.children}
    </figure>
  );
}

/** A thin "lane line" with a lane number: the site's divider. */
export function Lane({ n, label }: { n: string; label?: string }) {
  return (
    <div className="lane" aria-hidden={!label}>
      <b>{n}</b>
      {label && <span>{label}</span>}
      <i />
    </div>
  );
}

export const STEPS = [
  {
    title: "Start a challenge",
    text: "Name it, pick an entry fee and a length, from a quick fifteen minutes to a full week.",
  },
  {
    title: "Bring your people",
    text: "Share a six-letter code or a link. Friends, your office, your whole run club: up to eight players.",
  },
  {
    title: "Move, and earn points",
    text: "Each minute your Oura Ring records earns about a Sweat Point, weighted by effort. A day's first hour counts in full and then tapers, so showing up all week beats one big effort.",
  },
  {
    title: "Win the week",
    text: "A live leaderboard keeps score. When time's up, the prize pool is paid out automatically.",
  },
];

/** The numbered steps as an editorial list, not a row of cards. */
export function StepList({ compact = false }: { compact?: boolean }) {
  return (
    <ol className={`step-list${compact ? " compact" : ""}`}>
      {STEPS.map((step, i) => (
        <Reveal as="li" key={step.title} delay={i * 70}>
          <span className="step-list-n">0{i + 1}</span>
          <div>
            <h3>{step.title}</h3>
            <p>{step.text}</p>
          </div>
        </Reveal>
      ))}
    </ol>
  );
}

/* ---------- The animated product preview (sample data, labelled as such) ---------- */

const SAMPLE: { name: string; you?: boolean; ticks: boolean[]; points: number[] }[] = [
  { name: "Maya", ticks: [true, true, false, true, true, true, true], points: [11, 11, 11] },
  { name: "Jordan", ticks: [true, false, true, true, true, false, true], points: [9, 9, 10] },
  { name: "You", you: true, ticks: [true, true, true, false, true, true, true], points: [8, 10, 12] },
  { name: "Sam", ticks: [false, true, true, false, true, false, true], points: [6, 6, 7] },
  { name: "Priya", ticks: [true, false, false, true, false, true, false], points: [4, 5, 5] },
];

export function ProductPreview() {
  const still = prefersReducedMotion();
  const [frame, setFrame] = useState(still ? 2 : 0);
  useEffect(() => {
    if (still) return;
    // Three scores, then a pause on the last one before starting over.
    const timer = setInterval(() => setFrame((f) => (f + 1) % 4), 2600);
    return () => clearInterval(timer);
  }, [still]);
  const at = Math.min(frame, 2);

  const players: PlayerRow[] = SAMPLE.map((p) => ({ ...p, score: p.points[at] }))
    .sort((a, b) => b.score - a.score)
    .map((p, i) => ({
      rank: i + 1,
      name: p.name,
      points: p.score,
      base_points: p.score,
      pick_points: 0,
      team: null,
      projected_share: 0,
      goal_progress: null,
      ticks: p.ticks,
      is_you: !!p.you,
    }));

  return (
    <div className="preview" aria-label="A preview of a Rival challenge, with sample data">
      <div className="preview-card">
        <div className="preview-top">
          <div>
            <div className="eyebrow">Private game</div>
            <div className="preview-title">Sunday Run Club</div>
          </div>
          <span className="status-pill live">
            <span className="live-dot" /> Live
          </span>
        </div>
        <div className="preview-stats">
          <div>
            <small>Prize pool</small>
            <b>$25.00</b>
          </div>
          <div>
            <small>Players</small>
            <b>5</b>
          </div>
          <div>
            <small>Time left</small>
            <b>2d 14h</b>
          </div>
        </div>
        <Leaderboard players={players} form picks={false} compact />
      </div>
      <div className={`preview-toast${at > 0 ? " show" : ""}`} key={at}>
        <span className="preview-toast-icon">
          <Footprints size={16} aria-hidden />
        </span>
        <span>
          <b>{at === 2 ? "Evening run · 5 km" : "Morning run · 5 km"}</b>
          <small>You earned +2 points</small>
        </span>
      </div>
      <div className="preview-caption">Preview with sample data</div>
    </div>
  );
}
