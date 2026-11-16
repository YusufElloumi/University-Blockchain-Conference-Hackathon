# Setting up your computer

Step-by-step setup for teammates, on macOS or Windows. About 45 minutes, most of it waiting for one slow install.

You will end up with the whole app running on your own computer: the web app at http://localhost:5173 and the API server at http://localhost:8000. Both talk to our program, which is already deployed on Solana's devnet (the free test network). Everything uses test tokens. No real money is involved anywhere.

**You do not need Rust, Solana, Anchor, or WSL** to run the app. Those are only for changing the onchain program (see [Part 2](#part-2-optional-working-on-the-onchain-program)).

## Part 1: run the app

### 1. Install the tools

You need three things: **Git**, **Python 3.13**, and **Node 22**.

**macOS** (in Terminal). If you do not have Homebrew, install it first from https://brew.sh.

```bash
xcode-select --install          # gives you Git; skip if already installed
brew install python@3.13 node@22
brew link --overwrite --force node@22
```

**Windows** (in PowerShell):

```powershell
winget install Git.Git
winget install Python.Python.3.13
```

Then install Node 22 from https://nodejs.org/en/download (pick version **22**, not the newest). Close and reopen PowerShell afterwards so the new commands are found.

**Check it worked** (both systems):

| Command | Should print |
|---|---|
| `git --version` | any version |
| `node --version` | `v22.` something |
| `python3.13 --version` (macOS) or `py -3.13 --version` (Windows) | `Python 3.13.` something |

### 2. Get the code

```
git clone https://github.com/YusufElloumi/University-Blockchain-Conference-Hackathon.git loser-buys
cd loser-buys
```

Windows: do **not** put the folder inside OneDrive (Desktop and Documents often are). Syncing makes installs very slow. Somewhere like `C:\dev\loser-buys` is fine.

### 3. Add the settings file (`.env`)

The app reads its settings and keys from one file named `.env` in the top folder of the repo. It is never stored in git, so cloning does not give it to you.

**Ask Yusuf for the team `.env` file** and save it as `.env` in the `loser-buys` folder, next to `README.md`. With that file you share the team's Privy app (login), treasury (test funds), and oracle (the key that reports results), so you need no accounts of your own.

Rules for this file:

- Never commit it, paste it in a public channel, or screenshot it. It holds keys. They are devnet-only, but anyone holding them can drain our test funds before the demo.
- Leave `DATABASE_URL` empty. Empty means "use a small local database file" (`api/loser_buys.db`). Filling it in would point your computer at the live database.

Starting without the team file (for example, to run your own separate copy)? Copy `.env.example` to `.env` and follow the settings table in the [README](../README.md#run-it-locally).

<details>
<summary>For Yusuf: how to make the team <code>.env</code></summary>

Your own `.env` points at keypair files inside your WSL, which do not exist on anyone else's computer. Make a copy of it for the team and change these lines, so the keys travel inside the file and it works the same on macOS and Windows:

```
ORACLE_KEYPAIR_PATH=
TREASURY_KEYPAIR_PATH=
ORACLE_KEYPAIR=<the contents of oracle.json: one line, [12,34,...]>
TREASURY_KEYPAIR=<the contents of treasury.json>
DATABASE_URL=
WEB_ORIGIN=http://localhost:5173
VITE_API_URL=http://localhost:8000
```

Print each file's contents in WSL with `cat ~/.config/solana/loser-buys/oracle.json` (and `treasury.json`). The API uses `ORACLE_KEYPAIR` / `TREASURY_KEYPAIR` when they are set (`load_keypair` in `api/chain.py`).

Also clear `QUICKNODE_STREAM_SECURITY_TOKEN` and `QUICKNODE_STREAM_ID` unless the teammate is setting up their own Stream (step 7). Send the file privately (direct message or a password manager), not through git.

</details>

### 4. Start the API server

Open a terminal in the `loser-buys` folder.

**macOS:**

```bash
cd api
python3.13 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m uvicorn main:app --reload
```

**Windows:**

```powershell
cd api
py -3.13 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe -m uvicorn main:app --reload
```

The first two commands are one-time setup. They create a "virtual environment" (`.venv`), a private folder of Python packages just for this project. From then on, only the last line is needed.

It is working when you see `Uvicorn running on http://127.0.0.1:8000`. Leave this terminal open.

### 5. Start the web app

Open a **second** terminal in the `loser-buys` folder. The commands are the same on both systems:

```
cd web
npm install
npm run dev
```

`npm install` is one-time, and **it can take around 20 minutes** the first time (the login library pulls in a very large number of packages). It has not frozen.

Then open **http://localhost:5173** in your browser. Use exactly that address: the login wallet only works on `localhost` or HTTPS, so opening it from your phone over Wi-Fi will not work.

### 6. Check that it works

1. Sign in with your email (you get a code by email).
2. Tap **Add test funds**.
3. Start a challenge and join it.
4. To be a second player, open a private/incognito window and sign in with a different email.

You can also run the API's automated tests, from the `api` folder:

- macOS: `.venv/bin/python -m pytest`
- Windows: `.venv\Scripts\python.exe -m pytest`

### 7. Optional: live events on your computer (QuickNode Stream)

The feed and the "Deposit confirmed" message come from a QuickNode Stream, a service that pushes our program's onchain events to the API. A Stream delivers to one address only, and the team's Stream is not pointed at your computer. So when you run locally without your own Stream:

- Joining still happens onchain, but the screen stays on "Deposit sent. Waiting for confirmation..." and the feed stays empty.
- Events are filled in after a challenge is settled or refunded.

That is fine for most work. If you need the live feed locally, make a free QuickNode account and your own Stream by following step 4 of "Run it locally" in the [README](../README.md#run-it-locally). Pause the Stream in the QuickNode dashboard whenever your API or tunnel is off, because it stops itself after 3 failed deliveries.

### Day to day

After the first setup, starting work is two terminals:

| Terminal | macOS | Windows |
|---|---|---|
| 1, in `api/` | `.venv/bin/python -m uvicorn main:app --reload` | `.venv\Scripts\python.exe -m uvicorn main:app --reload` |
| 2, in `web/` | `npm run dev` | `npm run dev` |

After `git pull`, rerun the `pip install -r requirements.txt` line if `api/requirements.txt` changed, and `npm install` if `web/package.json` changed.

### If something goes wrong

| What you see | What to do |
|---|---|
| `python3.13` or `py` is "not found" | Close and reopen the terminal. On Windows, `python --version` may work instead; if it prints 3.13, use `python` in place of `py -3.13` |
| `node --version` prints something other than `v22` | Install Node 22 (step 1). On macOS, rerun the `brew link` line |
| The API stops at start with "Set ORACLE_KEYPAIR_PATH..." or a missing-file error | Your `.env` is missing, in the wrong folder (it belongs in the top `loser-buys` folder, not `api/`), or still has keypair file paths from someone else's computer |
| The web page shows a setup message instead of the login | `VITE_PRIVY_APP_ID` is missing from `.env`. After editing `.env`, stop `npm run dev` (Ctrl+C) and start it again |
| The web app says it cannot reach the server | The API terminal is not running, or `VITE_API_URL` in `.env` is not `http://localhost:8000` |
| "Add test funds" fails | The shared treasury may be out of test tokens. Tell Yusuf; it is refilled at https://faucet.solana.com (SOL) and https://faucet.circle.com (USDC, choose Solana Devnet) |
| Errors mentioning `429` or "Too Many Requests" | The free public Solana connection is limiting us. Wait a minute and try again |
| "Address already in use" / port 8000 or 5173 is taken | Another copy is still running in an old terminal. Close it |
| `npm install` fails with "no space left" | Free up disk space and run it again |

## Part 2 (optional): working on the onchain program

Skip this unless you are changing the Rust code in `onchain/`. The program is already deployed, and its interface file (the IDL, `onchain/idl/loser_buys.json`) is in the repo, which is all the app needs.

Things to know first:

- **Only Yusuf's deploy wallet can update the deployed program.** You can build and test locally, then hand the change over through git.
- The program's address comes from a "program keypair" file that is not in git. To build and test against the real address you need that file from Yusuf.

### Versions we use

| Tool | Version |
|---|---|
| Rust | installed with `rustup`; the program's own version (1.89.0) is picked automatically from `onchain/rust-toolchain.toml` |
| Solana CLI (Agave) | 4.3.2 |
| Anchor CLI | 1.2.2, installed through `avm` (Anchor's version manager) |
| Node | 22 (Node 26 breaks Anchor's test runner) |
| Yarn | 1.22 |

Install them by following the official guide, https://solana.com/docs/intro/installation, then pin Anchor:

```bash
avm install 1.2.2
avm use 1.2.2
solana config set --url devnet
```

- **macOS:** install everything directly in Terminal.
- **Windows:** these tools do not run on Windows itself. Install WSL first (a Linux system inside Windows): run `wsl --install -d Ubuntu` in PowerShell as administrator, restart, then follow the guide **inside the Ubuntu terminal**. If WSL refuses to start, "virtualization" is probably switched off in your computer's BIOS settings.

### Build and test

**macOS**, from the `onchain` folder. Put the program keypair from Yusuf at `onchain/target/deploy/loser_buys-keypair.json` first (the `target` folder is ignored by git).

```bash
yarn install
anchor build
anchor test --validator legacy
```

If you changed the program, copy `target/idl/loser_buys.json` and `target/types/loser_buys.ts` into `onchain/idl/` and commit them, so the web app and API see the new interface.

**Windows**, from the repo root in PowerShell. Put the program keypair from Yusuf at `~/.config/solana/loser-buys/program-keypair.json` inside Ubuntu first.

```powershell
wsl -d Ubuntu -- bash -l scripts/wsl_anchor.sh build
wsl -d Ubuntu -- bash -l scripts/wsl_anchor.sh test --validator legacy
```

The script copies `onchain/` into a folder inside WSL (builds on the Windows drive are very slow), runs the command there, and copies the IDL back for you. Do not run `anchor` directly on the Windows path.

The macOS steps and the fresh-WSL steps have not yet been tried on a clean computer. If a step is wrong, fix it here.
