// The Proof of Sweat v2 message: the exact bytes the verifier signs and the program reads at payout.
// Shared by the program tests (onchain/tests) and the web app (web/src/proofCheck.ts). The API builds
// the same bytes in Python (api/attest.py, message_v2). All three are checked against one fixture,
// onchain/shared/proof_v2_fixture.json, so the languages cannot drift apart.
//
// Layout (fixed sizes, integers little-endian), also in docs/ARCHITECTURE.md:
//   domain      24 bytes  "rival.proof-of-effort.v2"
//   program     32 bytes
//   challenge   32 bytes
//   rules_hash  32 bytes
//   score_hash  32 bytes
//   count        1 byte   (1 to 8)
//   winners     32 bytes each, in payout order
//   shares       2 bytes each (u16 basis points; 10,000 = 100%), same order
//
// No dependencies, so it runs in the browser and in Node.

export const PROOF_DOMAIN = "rival.proof-of-effort.v2";

export type ProofMessageParts = {
  program: Uint8Array;
  challenge: Uint8Array;
  rulesHash: Uint8Array;
  scoreHash: Uint8Array;
  winners: Uint8Array[];
  sharesBps: number[];
};

export function proofMessageV2(parts: ProofMessageParts): Uint8Array {
  const { program, challenge, rulesHash, scoreHash, winners, sharesBps } = parts;
  for (const key of [program, challenge, rulesHash, scoreHash, ...winners]) {
    if (key.length !== 32) throw new Error("every key and hash must be 32 bytes");
  }
  if (winners.length < 1 || winners.length > 8 || sharesBps.length !== winners.length) {
    throw new Error("need 1 to 8 winners and one share each");
  }
  const domain = new TextEncoder().encode(PROOF_DOMAIN);
  const out = new Uint8Array(domain.length + 32 * 4 + 1 + winners.length * 34);
  let at = 0;
  const put = (bytes: Uint8Array) => {
    out.set(bytes, at);
    at += bytes.length;
  };
  put(domain);
  put(program);
  put(challenge);
  put(rulesHash);
  put(scoreHash);
  out[at++] = winners.length;
  winners.forEach(put);
  for (const share of sharesBps) {
    if (!Number.isInteger(share) || share < 0 || share > 10_000) throw new Error("shares are basis points");
    out[at++] = share & 0xff;
    out[at++] = share >> 8;
  }
  return out;
}

/** Reads a v2 message back into its parts (keys and hashes as bytes). Throws on anything malformed. */
export function parseProofMessageV2(message: Uint8Array): ProofMessageParts {
  const domain = new TextEncoder().encode(PROOF_DOMAIN);
  const fixed = domain.length + 32 * 4 + 1;
  if (message.length <= fixed) throw new Error("message too short");
  for (let i = 0; i < domain.length; i++) if (message[i] !== domain[i]) throw new Error("not a v2 message");
  let at = domain.length;
  const take = (n: number) => message.slice(at, (at += n));
  const program = take(32);
  const challenge = take(32);
  const rulesHash = take(32);
  const scoreHash = take(32);
  const count = take(1)[0];
  if (count < 1 || count > 8 || message.length !== fixed + count * 34) throw new Error("wrong winner count");
  const winners = Array.from({ length: count }, () => take(32));
  const sharesBps = Array.from({ length: count }, () => {
    const b = take(2);
    return b[0] | (b[1] << 8);
  });
  return { program, challenge, rulesHash, scoreHash, winners, sharesBps };
}
