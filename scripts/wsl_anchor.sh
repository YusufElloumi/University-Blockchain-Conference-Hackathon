#!/usr/bin/env bash
# Runs an Anchor command for onchain/ inside WSL.
#
# Anchor builds are very slow on the OneDrive/Windows path, so this copies onchain/ into a
# build folder in the WSL home directory, runs the command there, and copies the results
# (IDL, TypeScript types, lock files) back into the repo.
#
# From the repo root in PowerShell:
#   wsl -d Ubuntu -- bash -l scripts/wsl_anchor.sh build
#   wsl -d Ubuntu -- bash -l scripts/wsl_anchor.sh test --validator legacy
#   wsl -d Ubuntu -- bash -l scripts/wsl_anchor.sh deploy --provider.cluster devnet
#   wsl -d Ubuntu -- bash -l scripts/wsl_anchor.sh smoke        (devnet smoke test)
#   wsl -d Ubuntu -- bash -l scripts/wsl_anchor.sh create-challenge   (open devnet challenge for the web app)

[ -s "$HOME/.nvm/nvm.sh" ] && source "$HOME/.nvm/nvm.sh"
SRC="$(cd "$(dirname "$0")/.." && pwd)/onchain"
DST="${ONCHAIN_BUILD_DIR:-$HOME/dev/loser-buys/onchain}"
KEYS="$HOME/.config/solana/loser-buys"
EXCLUDES=(--exclude target --exclude node_modules --exclude .anchor --exclude test-ledger --exclude Cargo.lock)

mkdir -p "$DST" "$KEYS"
rsync -a --delete "${EXCLUDES[@]}" "$SRC/" "$DST/"
cd "$DST" || exit 1

# The program keypair decides the program ID. Keep it out of the repo, restore it if target/ was wiped.
if [ -f "$KEYS/program-keypair.json" ]; then
  mkdir -p target/deploy
  cp -n "$KEYS/program-keypair.json" target/deploy/loser_buys-keypair.json
elif [ -f target/deploy/loser_buys-keypair.json ]; then
  cp target/deploy/loser_buys-keypair.json "$KEYS/program-keypair.json"
  chmod 600 "$KEYS/program-keypair.json"
fi

yarn install --silent || exit 1

CMD="${1:-build}"
shift || true
if [ "$CMD" = "smoke" ]; then
  node scripts/devnet_smoke.js "$@"
  code=$?
elif [ "$CMD" = "create-challenge" ]; then
  node scripts/create_challenge.js "$@"
  code=$?
else
  anchor "$CMD" "$@"
  code=$?
fi

# Copy build results back so the web app and API can use them without building.
if [ -f target/idl/loser_buys.json ]; then
  mkdir -p "$SRC/idl"
  cp target/idl/loser_buys.json "$SRC/idl/loser_buys.json"
  cp target/types/loser_buys.ts "$SRC/idl/loser_buys.ts"
fi
[ -f Cargo.lock ] && cp Cargo.lock "$SRC/Cargo.lock"
[ -f yarn.lock ] && cp yarn.lock "$SRC/yarn.lock"
exit $code
