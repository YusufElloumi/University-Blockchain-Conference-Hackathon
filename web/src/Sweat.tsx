// Proof of Sweat: a player's own Oura workouts in one challenge, each with its verification receipt.
// Everything here is private to the signed-in player. Points and checks are worked out on the server
// (api/sweat.py); this file only explains them.

import { useCallback, useEffect, useState } from "react";
import {
  Activity,
  Bike,
  ChevronDown,
  CircleAlert,
  CircleCheck,
  CircleDashed,
  CircleMinus,
  Dumbbell,
  Footprints,
  Lock,
  Mountain,
  PersonStanding,
  RefreshCw,
  ShieldCheck,
  Waves,
  type LucideIcon,
} from "lucide-react";
import { ApiError, type Call } from "./api";
import type { Session } from "./App";
import { EmptyState, Eyebrow, Skeleton } from "./ui";

type Result = "passed" | "limited" | "failed" | "pending";
type CheckRow = { code: string; result: Result; reason: string | null };

/** One workout as the server describes it to its owner. */
type Workout = {
  key: number | string;
  activity: string | null;
  provider_activity?: string | null;
  provider_source?: string | null;
  start?: string | null;
  duration_minutes: number;
  result: "verified" | "rejected" | "pending";
  assurance: "strong" | "limited" | null;
  reason: string | null;
  eligible_minutes: number | null;
  points: number | null;
  heart_rate_coverage_pct?: number | null;
  checks: CheckRow[];
  commitment?: string; // final receipts only: the hash listed in the score sheet
};

type FinalReceipt = {
  commitment: string;
  canonical: string;
  receipt: Omit<Workout, "key" | "start" | "commitment"> & { rules_version: string };
};

export type SweatReply = {
  connected: boolean;
  available: boolean;
  last_sync_at: string | null;
  last_sync_error: string | null;
  rules: { version: string; sha256: string | null; summary: string } | null;
  final: boolean;
  eligible_minutes: number | null;
  points: number | null;
  workouts: Workout[];
  receipts: FinalReceipt[];
};

const ICON: Record<string, LucideIcon> = {
  run: PersonStanding,
  walk: Footprints,
  hike: Mountain,
  ride: Bike,
  swim: Waves,
  workout: Dumbbell,
};

const ACTIVITY_NAME: Record<string, string> = {
  run: "Run",
  walk: "Walk",
  hike: "Hike",
  ride: "Ride",
  swim: "Swim",
  workout: "Workout",
};

/** Why a workout was not counted, or why its evidence is limited, in plain words. */
const REASON: Record<string, string> = {
  manual_entry: "It was entered by hand in Oura, so there is no recording to check.",
  unknown_source: "Oura didn't say how this workout was recorded.",
  unauthorized_provider: "It didn't come through your connected Oura account.",
  unsupported_activity: "This type of activity isn't counted yet.",
  missing_time: "Oura sent it without a usable start and end time.",
  ends_before_start: "Its end time is before its start time.",
  too_long: "It runs for more than 24 hours.",
  in_the_future: "It ends in the future.",
  under_minimum: "It is shorter than 10 minutes.",
  under_minimum_in_window: "Fewer than 10 minutes of it fall inside this challenge.",
  invalid_distance: "Its distance isn't a valid number.",
  too_fast: "Its distance and time give a speed that isn't believable for this activity.",
  duplicate_time: "Another workout already covers this whole time.",
  partly_overlapping: "Part of it overlaps another workout. Each minute counts once.",
  removed_at_provider: "It no longer appears in your Oura account.",
  no_heart_rate: "Oura returned no heart-rate measurements for this workout.",
  low_coverage: "Heart-rate measurements were unavailable for much of this workout.",
  background_only: "Only background heart-rate readings were available, none recorded as exercise.",
  heart_rate_unavailable: "Heart-rate measurements couldn't be read from Oura.",
  third_party_source: "Its heart rate came from a third-party device, which we rate cautiously.",
  quality_warning: "Some heart-rate readings were unusable and were left out.",
  no_distance: "No distance was recorded, which is fine.",
};

const worst = (results: (Result | undefined)[]): Result | null => {
  const found = results.filter(Boolean) as Result[];
  if (!found.length) return null;
  for (const level of ["failed", "pending", "limited", "passed"] as Result[]) if (found.includes(level)) return level;
  return null;
};

type Line = { label: string; result: Result | null; detail: string };

/** The eight lines of a receipt, built from the server's check codes. */
function receiptLines(w: Workout): Line[] {
  const by = Object.fromEntries(w.checks.map((c) => [c.code, c])) as Record<string, CheckRow | undefined>;
  const why = (...codes: string[]) => {
    const failed = codes.map((c) => by[c]).find((c) => c && c.result !== "passed" && c.reason);
    return failed?.reason ? (REASON[failed.reason] ?? failed.reason) : null;
  };
  const source = worst([by.provider?.result, by.provenance?.result]);
  const timing = worst([by.timestamps?.result, by.window?.result]);
  const evidence = by.evidence?.result ?? null;
  const coverage = w.heart_rate_coverage_pct;
  return [
    {
      label: "Oura source authenticated",
      result: source,
      detail: why("provider", "provenance") ?? "Fetched through your authorized Oura connection, from a recorded (not hand-entered) workout.",
    },
    {
      label: "Eligible activity type",
      result: by.activity?.result ?? null,
      detail: why("activity") ?? "Its activity type maps to one Rival counts.",
    },
    {
      label: "Challenge time window valid",
      result: timing,
      detail: why("timestamps", "window") ?? "Valid start and end times. Only minutes inside the challenge are counted.",
    },
    {
      label: "Minimum duration passed",
      result: by.window?.reason === "under_minimum_in_window" ? "failed" : (by.duration?.result ?? null),
      detail: why("duration") ?? (by.window?.reason === "under_minimum_in_window" ? REASON.under_minimum_in_window : "At least 10 minutes long."),
    },
    {
      label: "Plausibility checks passed",
      result: by.plausibility?.result ?? null,
      detail:
        by.plausibility?.result === "failed"
          ? (why("plausibility") ?? "Not believable.")
          : by.plausibility?.reason === "no_distance"
            ? "No distance was recorded, so there was no speed to check. That is not held against it."
            : "Distance and time give a believable speed for this activity.",
    },
    {
      label: "Duplicate check passed",
      result: by.duplicate?.result ?? null,
      detail: why("duplicate") ?? "No other workout of yours covers the same time, and it is counted once in this challenge.",
    },
    {
      label: "Physiological evidence assessed",
      result: evidence,
      detail:
        evidence === "passed"
          ? `Heart-rate measurements recorded as exercise cover ${coverage != null ? `${coverage}% of` : "most of"} this workout.` +
            (by.evidence?.reason === "quality_warning" ? ` ${REASON.quality_warning}` : "")
          : evidence === "limited"
            ? `${REASON[by.evidence?.reason ?? ""] ?? "The heart-rate evidence is limited."} The activity remains eligible because its Oura recording and the other required checks passed.`
            : evidence === "pending"
              ? "Waiting to read heart-rate coverage from Oura."
              : "Not assessed, because a required check failed first.",
    },
    {
      label: "Scoring rules applied",
      result: by.scoring?.result ?? (w.result === "rejected" ? "failed" : null),
      detail:
        w.result === "verified"
          ? `${w.eligible_minutes ?? 0} eligible minutes. 1 point per 10 minutes, up to 6 a day across all your workouts.`
          : w.result === "pending"
            ? "Points are added once the checks finish."
            : "No points: a required check did not pass.",
    },
  ];
}

const RESULT_WORD: Record<Result, string> = { passed: "Passed", limited: "Limited evidence", failed: "Failed", pending: "Pending" };

function ResultIcon({ result }: { result: Result | null }) {
  if (result === "passed") return <CircleCheck size={16} aria-hidden />;
  if (result === "limited") return <CircleMinus size={16} aria-hidden />;
  if (result === "failed") return <CircleAlert size={16} aria-hidden />;
  return <CircleDashed size={16} aria-hidden />;
}

function statusOf(w: Workout): { tone: "strong" | "limited" | "rejected" | "pending"; label: string; line: string } {
  if (w.result === "pending") return { tone: "pending", label: "Checking", line: "Checking your activity." };
  if (w.result === "rejected")
    return { tone: "rejected", label: "Not counted", line: REASON[w.reason ?? ""] ?? "A required check did not pass." };
  if (w.assurance === "strong") return { tone: "strong", label: "Verified", line: "Proof of Sweat verified." };
  return { tone: "limited", label: "Verified · limited evidence", line: "Verified. Limited heart-rate evidence." };
}

const when = (iso: string) =>
  new Date(iso).toLocaleString([], { weekday: "short", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });

const ago = (iso: string) => {
  const minutes = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 60000));
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes} min ago`;
  if (minutes < 60 * 24) return `${Math.round(minutes / 60)} h ago`;
  return `${Math.round(minutes / 1440)} d ago`;
};

const SYNC_ERROR: Record<string, string> = {
  reconnect: "Oura needs to be reconnected. Disconnect and connect it again from your dashboard.",
  permission: "Oura refused access to workouts. Reconnect and allow workouts and heart rate.",
  rate_limited: "Oura is busy. The last sync didn't finish; try again in a few minutes.",
  unreachable: "Oura couldn't be reached on the last sync. Your points are unchanged.",
  error: "The last sync didn't finish. Your points are unchanged.",
};

/** One workout row that opens into its receipt. */
function WorkoutReceipt({ w, rulesVersion }: { w: Workout; rulesVersion: string | null }) {
  const [open, setOpen] = useState(false);
  const Icon = ICON[w.activity ?? ""] ?? Activity;
  const status = statusOf(w);
  const name = ACTIVITY_NAME[w.activity ?? ""] ?? w.provider_activity ?? "Activity";
  const lines = receiptLines(w);
  return (
    <div className={`sweat-item ${status.tone}${open ? " open" : ""}`}>
      <button className="sweat-row" onClick={() => setOpen(!open)} aria-expanded={open}>
        <span className="icon-tile icon-tile-sm">
          <Icon size={15} strokeWidth={1.75} aria-hidden />
        </span>
        <span className="sweat-row-main">
          <span className="sweat-row-title">
            <b>{name}</b> · {w.duration_minutes} min
          </span>
          <span className="fine">
            {w.start ? `${when(w.start)} · ` : ""}
            {status.label}
          </span>
        </span>
        <span className="sweat-row-points">
          {w.result === "verified" ? (
            <>
              <b>+{w.points ?? 0}</b>
              <small>pt{w.points === 1 ? "" : "s"}</small>
            </>
          ) : (
            <small>{w.result === "pending" ? "Pending" : "0 pts"}</small>
          )}
        </span>
        <ChevronDown className="sweat-chevron" size={16} aria-hidden />
      </button>

      {open && (
        <div className="sweat-receipt">
          <div className="sweat-receipt-head">
            <span className="sweat-receipt-title">
              <ShieldCheck size={14} aria-hidden /> Proof of Sweat
            </span>
            <span className={`sweat-badge ${status.tone}`}>{status.label}</span>
          </div>
          <p className="sweat-receipt-line">{status.line}</p>
          <dl className="sweat-stats">
            <div>
              <dt>Workout</dt>
              <dd>{name}</dd>
            </div>
            <div>
              <dt>Duration</dt>
              <dd>{w.duration_minutes} min</dd>
            </div>
            <div>
              <dt>Eligible</dt>
              <dd>{w.eligible_minutes ?? 0} min</dd>
            </div>
            <div>
              <dt>Points</dt>
              <dd className="pts">{w.points ?? 0}</dd>
            </div>
          </dl>
          <ul className="sweat-checks">
            {lines.map((line) => (
              <li key={line.label} className={line.result ?? "skipped"}>
                <ResultIcon result={line.result} />
                <details>
                  <summary>
                    <span>{line.label}</span>
                    <em>{line.result ? RESULT_WORD[line.result] : "Not assessed"}</em>
                  </summary>
                  <p>{line.detail}</p>
                </details>
              </li>
            ))}
          </ul>
          <p className="fine sweat-foot">
            {rulesVersion ? `Rules ${rulesVersion}. ` : ""}
            These checks compare what Oura recorded with Rival's published rules. They don't prove a workout happened, and heart rate
            never changes your points.
            {w.commitment && (
              <>
                {" "}
                Receipt fingerprint <code>{w.commitment.slice(0, 16)}…</code> is listed in this challenge's final score sheet.
              </>
            )}
          </p>
        </div>
      )}
    </div>
  );
}

/** The "My workouts" tab of a Proof of Sweat challenge. */
export default function SweatWorkouts(props: {
  session: Session;
  address: string;
  live: boolean; // the challenge is running or waiting for final syncs
  onScored: () => void;
}) {
  const { call, go } = props.session;
  const [data, setData] = useState<SweatReply | null>(null);
  const [syncing, setSyncing] = useState(false);
  const [note, setNote] = useState<{ good: boolean; text: string } | null>(null);

  const load = useCallback(
    () =>
      call<SweatReply>("GET", `/me/sweat?challenge=${props.address}`)
        .then(setData)
        .catch(() => setData(null)),
    [call, props.address],
  );
  useEffect(() => {
    load();
  }, [load]);

  async function sync() {
    setSyncing(true);
    setNote(null);
    try {
      const done = await syncOura(call);
      setNote({ good: true, text: done });
      await load();
      props.onScored();
    } catch (e) {
      setNote({ good: false, text: e instanceof ApiError ? e.message : "Couldn't sync. Try again." });
    } finally {
      setSyncing(false);
    }
  }

  if (data === null) return <Skeleton rows={3} height={64} />;

  const workouts: Workout[] = data.final
    ? data.receipts.map((r, i) => ({ ...r.receipt, key: i, commitment: r.commitment }))
    : data.workouts;
  const counted = workouts.filter((w) => w.result === "verified");

  return (
    <div className="workouts sweat">
      <section className="card sweat-summary">
        <div className="sweat-summary-top">
          <div>
            <Eyebrow>Proof of Sweat</Eyebrow>
            <p className="sweat-rule">{data.rules?.summary}</p>
          </div>
          <span className="icon-tile">
            <ShieldCheck size={18} strokeWidth={1.75} aria-hidden />
          </span>
        </div>
        <div className="sweat-totals">
          <div>
            <b>{data.points ?? 0}</b>
            <span>fitness points</span>
          </div>
          <div>
            <b>{data.eligible_minutes ?? 0}</b>
            <span>verified minutes</span>
          </div>
          <div>
            <b>{counted.length}</b>
            <span>workout{counted.length === 1 ? "" : "s"} counted</span>
          </div>
        </div>

        {data.final ? (
          <p className="fine">Final. These receipts are fixed, and each one's fingerprint is in the settled score sheet.</p>
        ) : !data.connected ? (
          <div className="sweat-connect">
            <p>
              <b>Connect Oura to earn points.</b> This challenge only counts workouts recorded by your Oura Ring. Nothing typed in
              by hand scores.
            </p>
            <button className="btn btn-primary btn-sm" onClick={() => go({ view: "home" })}>
              Connect Oura on your dashboard
            </button>
          </div>
        ) : (
          <div className="sweat-sync">
            <button className="btn btn-quiet btn-sm" onClick={sync} disabled={syncing || !props.live}>
              <RefreshCw size={14} className={syncing ? "spin" : ""} aria-hidden /> {syncing ? "Checking Oura..." : "Sync workouts"}
            </button>
            <span className="fine">
              {data.last_sync_at ? `Last synced ${ago(data.last_sync_at)}.` : "Not synced yet."} New workouts appear after your ring
              syncs with the Oura app.
            </span>
          </div>
        )}
        {note && (
          <p className={`fine ${note.good ? "sweat-ok" : "warn"}`} role="status">
            {note.text}
          </p>
        )}
        {!note && data.connected && data.last_sync_error && !data.final && (
          <p className="fine warn">{SYNC_ERROR[data.last_sync_error] ?? SYNC_ERROR.error}</p>
        )}
      </section>

      <div className="section-head">
        <h2>Your workouts</h2>
        <span className="count with-icon">
          <Lock size={11} aria-hidden /> Only you can see these
        </span>
      </div>
      {workouts.length === 0 ? (
        <EmptyState
          icon={<Footprints size={20} strokeWidth={1.75} />}
          title={data.final ? "No workouts were recorded" : data.connected ? "Waiting for Oura to sync" : "No workouts yet"}
          text={
            data.final
              ? undefined
              : data.connected
                ? "Workouts you record during this challenge show up here once your ring has synced."
                : "Connect Oura and your recorded workouts will appear here with their checks."
          }
        />
      ) : (
        <section className="card sweat-list">
          {workouts.map((w) => (
            <WorkoutReceipt key={w.key} w={w} rulesVersion={data.rules?.version ?? null} />
          ))}
        </section>
      )}
    </div>
  );
}

type SyncSummary = { new: number; updated: number; verified: number; pending: number; rejected: number };

/** Runs a sync and returns a one-line result. Shared with the Oura card. */
export async function syncOura(call: Call): Promise<string> {
  const s = await call<SyncSummary>("POST", "/integrations/oura/sync");
  if (s.new === 0 && s.updated === 0) return s.pending ? "No new workouts. Some are still being checked." : "Up to date. No new workouts.";
  const found = s.new + s.updated;
  return `Workout${found === 1 ? "" : "s"} found: ${found}. ${s.pending ? "Still checking some." : "Checks complete."}`;
}
