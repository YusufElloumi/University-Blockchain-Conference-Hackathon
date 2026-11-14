// QuickNode Stream filter for Loser Buys.
//
// Stream settings: network Solana Devnet, dataset "Programs + Logs", destination webhook
// POST <API URL>/webhooks/quicknode. Paste this whole file into the Stream's filter editor.
//
// What it does: out of every transaction on devnet, keep only the successful ones that called
// our program, and send just the signature, slot, block time, and log lines. The program writes
// its events (PlayerJoined, ChallengeSettled, ...) into those log lines; the API decodes them.
// Returning null means "nothing for us in this batch", and nothing is delivered.

const PROGRAM_ID = "FeCj36zk7YNkdfKZXjfjSmftqpJv9C68uBNSvtRt3ssC";

function main(stream) {
  const data = stream && stream.data !== undefined ? stream.data : stream;
  const transactions = [];

  // The dataset arrives as a list of blocks, each a list of transactions. Flatten whatever depth we get.
  const visit = (item) => {
    if (Array.isArray(item)) {
      item.forEach(visit);
      return;
    }
    if (!item || typeof item !== "object" || !item.signature) return;
    if (item.success === false) return;

    const logs = Array.isArray(item.logs) ? item.logs : [];
    const invoked =
      (Array.isArray(item.programInvocations) &&
        item.programInvocations.some((p) => p && p.programId === PROGRAM_ID)) ||
      logs.some((line) => typeof line === "string" && line.startsWith("Program " + PROGRAM_ID + " invoke"));
    if (!invoked) return;

    transactions.push({
      signature: item.signature,
      slot: item.slot,
      blockTime: item.blockTime,
      logs: logs,
    });
  };
  visit(data);

  return transactions.length > 0 ? { transactions: transactions } : null;
}
