/** "What activities count?" on the create screen. The server owns the rule (api/activities.py);
 * this file only holds the words. Ids must match the server's choices. */

export type ActivityChoice = "all" | "running" | "walking" | "hiking" | "cycling" | "strength";

export const ACTIVITY_CHOICES: { id: ActivityChoice; label: string; line: string }[] = [
  {
    id: "all",
    label: "All exercise",
    line: "Every supported activity counts: runs, walks, hikes, rides, swims, gym sessions and more.",
  },
  { id: "running", label: "Running", line: "Only workouts Oura records as running earn points." },
  { id: "walking", label: "Walking", line: "Only workouts Oura records as walking earn points." },
  { id: "hiking", label: "Hiking", line: "Only workouts Oura records as hiking earn points." },
  { id: "cycling", label: "Cycling", line: "Only workouts Oura records as cycling earn points." },
  {
    id: "strength",
    label: "Strength training",
    line: "Only workouts Oura records as strength training earn points. No distance needed.",
  },
];

/** What a challenge reports about its locked choice (GET /challenges/.../state). */
export type ActivitiesView = { selection: string; label: string; restricted: boolean };

/** "Running" for a one-sport event, null when all exercise counts. */
export const sportLabel = (a: ActivitiesView | null | undefined): string | null => (a?.restricted ? a.label : null);
