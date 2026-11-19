// Checks that the browser's Proof of Sweat arithmetic (src/sweatMath.ts) gives the server's answers.
// Run with `npm run check:sweat` (Node 22.18 or newer). The expected answers come from the real
// scoring code: `python sweat_sample.py write` in api/.

import { readFileSync } from "node:fs";
import { isDeepStrictEqual } from "node:util";
import { RULES_SHA256, RULES_VERSION, scoreSample } from "../src/sweatMath.ts";

const vectors = JSON.parse(readFileSync(new URL("./sweat-vectors.json", import.meta.url), "utf8"));
const fail = (message) => {
  console.error(`check:sweat FAILED: ${message}`);
  process.exit(1);
};

if (vectors.rules_sha256 !== RULES_SHA256 || vectors.rules_version !== RULES_VERSION)
  fail("sweatRules.json and sweat-vectors.json come from different rules. Run `python sweat_sample.py write` in api/.");

const input = ([activity, minutes, intensity, heartPct, distanceKm, hrMinutes, quarters]) => ({
  activity, minutes, intensity, heartPct, distanceKm, hrMinutes, quarters,
});
const plain = (value) => JSON.parse(JSON.stringify(value));
const digest = ({ evidence, score }) => [
  evidence.index, evidence.label, evidence.parts.map((p) => p.points), score.band_minutes, score.base_points,
  ["provider", "heart", "movement"].map((k) => [score.factors[k].value, score.factors[k].state, score.factors[k].reason, score.factors[k].bonus]),
  score.multiplier, score.potential_bonus, score.reliability, score.adjusted_bonus, score.contribution,
];

for (const { in: given, out } of vectors.full) {
  const got = plain(scoreSample(input(given)));
  if (!isDeepStrictEqual(got, out)) fail(`full breakdown differs for ${JSON.stringify(given)}\n browser ${JSON.stringify(got)}\n server  ${JSON.stringify(out)}`);
}
for (const [given, expected] of vectors.cases) {
  const got = plain(digest(scoreSample(input(given))));
  if (!isDeepStrictEqual(got, expected)) fail(`${JSON.stringify(given)}\n browser ${JSON.stringify(got)}\n server  ${JSON.stringify(expected)}`);
}
console.log(`check:sweat ok: ${vectors.cases.length} made-up workouts and ${vectors.full.length} full receipts match the server (${RULES_VERSION}, ${RULES_SHA256.slice(0, 12)}...)`);
