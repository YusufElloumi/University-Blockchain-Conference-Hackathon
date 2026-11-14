// Quick local check of filter.js. Run from the repo root:  node streams/test_filter.js
const fs = require("fs");
const path = require("path");
const assert = require("assert");

const main = new Function(fs.readFileSync(path.join(__dirname, "filter.js"), "utf8") + "; return main;")();
const PROGRAM = "FeCj36zk7YNkdfKZXjfjSmftqpJv9C68uBNSvtRt3ssC";

const ours = { signature: "a", slot: 1, blockTime: 2, success: true, programInvocations: [{ programId: PROGRAM }], logs: ["x"] };
const failed = { ...ours, signature: "b", success: false };
const other = { signature: "c", slot: 1, success: true, programInvocations: [{ programId: "Other" }], logs: [] };
const byLog = { signature: "d", slot: 1, success: true, logs: ["Program " + PROGRAM + " invoke [1]"] };

const result = main({ data: [[ours, failed, other, byLog]] });
assert.deepStrictEqual(result.transactions.map((t) => t.signature), ["a", "d"]);
assert.deepStrictEqual(result.transactions[0], { signature: "a", slot: 1, blockTime: 2, logs: ["x"] });
assert.strictEqual(main({ data: [[other]] }), null);
assert.strictEqual(main({ data: [] }), null);
console.log("filter.js: all checks passed");
