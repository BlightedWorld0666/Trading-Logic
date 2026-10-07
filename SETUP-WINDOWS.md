# Trading Logic · Windows setup for when you're home

Start with the dashboard and demo training. Add Ollama after those work, then optionally set up read-only Robinhood crypto quotes. Your website and Dark Sector can keep running on their existing ports.

## 1. Download the latest project

1. Open [Trading-Logic on GitHub](https://github.com/BlightedWorld0666/Trading-Logic). Sign in if the repository asks you to.
2. Select **Code → Download ZIP**.
3. Right-click the ZIP → **Extract All**. Pick a permanent folder you can find again.
4. Open the extracted folder that contains `app.py`, `train.py`, and `start-scout.bat`. Avoid running files from inside the ZIP.
5. To open a terminal in this folder, click File Explorer's address bar, type `powershell`, and press Enter.

All commands below run from that project folder. You don't need VS Code, Git, Node.js, or a Cloudflare change to start.

Already have a Git checkout? Run `git pull --ff-only` from that checkout instead of downloading again. Keep your existing `models`, `reports`, `runtime`, and `secrets` folders when updating.

## 2. Check Python

You already installed Python for your website. Verify it:

```powershell
py -3 --version
```

Use **Python 3.10 or newer**. If Windows does not recognize `py`, try `python --version` and replace `py -3` with `python` throughout this guide. If neither works, install Python from [python.org](https://www.python.org/downloads/windows/), then close and reopen the terminal.

Check the project:

```powershell
py -3 -m unittest discover -s tests -v
```

Expected: the checks finish with **OK**. The simulator, training, and Ollama connection use only Python's standard library, so there is no pip install needed at this stage.

## 3. Open the dashboard

Double-click **start-scout.bat**, or run:

```powershell
py -3 app.py
```

Open [http://127.0.0.1:8002](http://127.0.0.1:8002) in your browser. Leave that server terminal open; closing it stops the desk. Use a **second** terminal in the project folder for the remaining commands.

You should see Portfolio, Strategies, Fills, Local AI, and Training tabs. Initial assets/prices are invented demo data. This desk stays local on port 8002; it does not need to be published through your website's tunnel.

## 4. Run your first training session

In the second terminal:

```powershell
py -3 train.py --output models/training-001
```

This runs 200 episodes on the invented demo dataset using your CPU. It does not require Ollama, GPU setup, a broker account, or real money. Progress prints in the terminal; wait for **Saved training run**.

It creates:

| File | What it contains |
| --- | --- |
| `models/training-001/policy.json` | Frozen policy selected by validation; it can select cash |
| `models/training-001/candidate-policy.json` | Learned candidate retained for research |
| `models/training-001/report.json` | Training progress, validation scores, final test results |
| `models/training-001/experience.jsonl` | State/action/reward transitions from the final training episode |

Open the dashboard's **Training** tab, select **Open a saved training report.json**, and choose that report.

Practice paper replay with the selected policy:

```powershell
py -3 paper.py --policy models/training-001/policy.json --steps 20 --output reports/policy-paper-001.json
```

Use new names such as `training-002` and `policy-paper-002.json` for later runs; the commands preserve existing outputs. Demo results do not establish profitability. A cash result is valid and may produce zero fills.

This learning policy is separate from Ollama. It learns a Q table; it does not change the language model's weights.

## 5. Install and connect Ollama

1. Install [Ollama for Windows](https://ollama.com/download/windows).
2. Set it to run local models only. In PowerShell:

```powershell
[Environment]::SetEnvironmentVariable('OLLAMA_NO_CLOUD', '1', 'User')
$env:OLLAMA_NO_CLOUD = '1'
```

3. Fully **quit Ollama** using its tray icon, then start it again. A running daemon must restart to pick up the setting. If it does not pick up the new user setting, sign out of Windows and back in, then start Ollama. The [official FAQ](https://docs.ollama.com/faq) also documents `disable_ollama_cloud` in Ollama's server configuration.
4. Open a new PowerShell window in the project folder. Download a small local starting model:

```powershell
ollama pull qwen3:4b
ollama list
```

`qwen3:4b` is an [available local model](https://ollama.com/library/qwen3:4b). It is a starting choice for testing the connection, not a trading specialist or a validated profitable model. We have not tested its inference speed or response quality on your PC.

5. In the dashboard's **Local AI** tab, enter **qwen3:4b** and click **Review locally**.

To let Ollama propose paper actions, start with a small replay:

```powershell
py -3 paper.py --model qwen3:4b --steps 5 --output reports/ollama-paper-001.json
```

After that works, use `--steps 20` and a new output filename. No Python Ollama package is required. The app uses the local HTTP API at `127.0.0.1:11434`. It checks for downloaded local models and rejects cloud/remote models.

`--model` runs the Ollama proposer; `--policy` runs a saved numerical policy. Choose one per replay. These commands do not automatically merge their decisions.

If the replay reports provider failures, inspect `error_type` in its JSON log. Failed proposals become hold actions; a completed command alone does not prove that model inference succeeded. The first model load may be slow. Use `ollama ps` to inspect the running model; GPU acceleration is not required for this initial setup, and support for your Radeon 6700 XT depends on the installed Ollama backend.

## 6. Optional: Robinhood crypto quotes

First test a **read-only quote snapshot**. Version 0.3 can then use those observations in a persistent forward virtual account (next section). It cannot place real orders, and historical replay remains separate.

Install the optional signing dependency and generate a local key pair:

```powershell
py -3 -m pip install -r requirements-robinhood.txt
py -3 robinhood_quotes.py --generate-key
```

The generator prints the **public key** and saves the private key to `secrets/robinhood.json`. It refuses to overwrite an existing key.

1. Sign into Robinhood's desktop website and open your **crypto account settings**.
2. In API credentials, select **Add key** and register the public key printed by the generator.
3. Enable **Read crypto quotes** only. Leave order-placement permissions disabled.
4. Copy the API key Robinhood gives you.
5. Open the local credential file:

```powershell
notepad .\secrets\robinhood.json
```

6. Replace only `REPLACE_LOCALLY` in the `api_key` value. Leave `private_key_base64` unchanged, keep the surrounding quotes, and save the file.
7. Fetch a snapshot:

```powershell
py -3 robinhood_quotes.py --symbols BTC-USD ETH-USD
```

Expected: JSON containing bid and ask prices. Pair availability and API access depend on your account. See [Robinhood's API setup guide](https://robinhood.com/us/en/support/articles/crypto-api/).

Keep that credential file on your PC; do not paste it into chat, commit it, or put it on your public website. On Windows, use the file's **Properties → Security** to restrict access appropriately to your user and system administrators. The generator's POSIX file mode does not configure Windows file permissions.

## 7. Start the persistent forward paper account

To check the monitor before connecting a broker feed, use a demo worker in a second terminal:

```powershell
py -3 forward.py --source demo --db runtime/demo.sqlite --interval 2 --bar-seconds 60
```

Keep your existing dashboard running with `py -3 app.py`. Open **Forward Paper**; it detects the default demo database once created. Prices are invented. After about 30–31 minutes of uninterrupted one-minute sampled candles, the fixed trend provider can start proposing virtual trades.

For Robinhood observations, after completing the read-only key setup:

```powershell
py -3 forward.py --source robinhood --db runtime/crypto.sqlite
```

In your dashboard terminal, press Ctrl+C to stop the old desk, then run:

```powershell
py -3 app.py --paper-db runtime/crypto.sqlite
```

Open port 8002 → **Forward Paper**. Leave **both terminals open**. The worker polls every minute and builds five-minute sampled candles. It waits for 30 consecutive eligible candles (about 2.5 hours plus startup alignment) before proposals. Until then it collects observations and monitors virtual equity.

Default decisions use a fixed trend rule, without Ollama. To use Ollama instead, create a **new** account:

```powershell
py -3 forward.py --source robinhood --db runtime/crypto-ollama.sqlite --model qwen3:4b
```

Point the dashboard at `runtime/crypto-ollama.sqlite` with `--paper-db`. You can use `--strategy cash` on a new account to collect observations without entries. These accounts use the illustrative virtual settings in `forward.example.json`; no brokerage balance is imported.

**Pause paper trading** cancels virtual orders and retains positions; collection continues. Resume keeps any drawdown halt active. Stop a worker with Ctrl+C and resume later using the **same command**: cash, positions, sampled history and valid pending intents are preserved. A long outage cancels old intents and restarts candle warmup. A crash can leave the worker lease occupied for a few minutes; wait for it to expire rather than deleting the database.

Inspect, back up or export in a third terminal:

```powershell
py -3 account_control.py --db runtime/crypto.sqlite
py -3 account_control.py --db runtime/crypto.sqlite --backup backups/crypto-001.sqlite
py -3 account_control.py --db runtime/crypto.sqlite --export-csv data/crypto-midpoints.csv
```

Use the backup command instead of copying an active database file. Generated CSV uses sampled midpoint candles with unknown volume set to zero, not exchange trade candles. It is labeled as unverified imported data if you later train from it.

The live stock feed is still pending. Read-only Robinhood access needs to be tested with your own credentials locally; no real orders are supported.

## 8. Real historical data comes next

Once the demo workflow works, put a verified USD OHLCV CSV in a local `data` folder. Training supports 1–4 symbols and needs at least 150 distinct timestamps, including at least 40 training and 20 validation/test bars per symbol. See [README.md](README.md#import-historical-data) for the CSV format and data requirements.

```powershell
py -3 train.py --csv data/history.csv --config config.example.json --learning-config learning.example.json --output models/training-real-001
py -3 paper.py --csv data/history.csv --config config.example.json --policy models/training-real-001/policy.json --steps 20 --output reports/real-policy-paper-001.json
```

Use the same risk/cost settings and symbols for training and policy replay. Costs in the example config are illustrative; replace them with verified assumptions for your dataset.

Training uses 60% of timestamps to learn, 20% to select a checkpoint, and 20% for a frozen final test. Replaying those prices again is not new forward evidence. Version 0.3 can continuously collect Robinhood crypto quote observations for its forward virtual account. A live stock feed and real Robinhood trades are not implemented.

## Quick fixes

| What you see | What to do |
| --- | --- |
| Can't find `app.py` or `train.py` | Open PowerShell inside the extracted project folder |
| `py` is not recognized | Use `python` if it works, or install Python and reopen the terminal |
| Dashboard doesn't open | Keep its server terminal running and use `http://127.0.0.1:8002` |
| Port 8002 is already in use | Stop the older desk, or run `py -3 app.py --port 8003` and open port 8003 |
| `ollama` is not recognized | Finish installing Ollama and reopen PowerShell |
| Local AI unavailable | Start Ollama, run `ollama list`, and use the exact installed model name |
| Model blocked as remote/cloud | Disable Ollama cloud, restart it, and use a downloaded local model |
| Output already exists | Pick a new run folder or report filename |
| Policy settings/symbols differ | Supply the same CSV symbols and risk/cost config used to train that policy |
| Robinhood request fails | Check quote-read permission, the locally entered API key, your PC clock and connection |
| No paper trades | Check whether cash won, states were unseen, or the log contains provider errors |

For your first evening, finishing **steps 1–5** is enough to test the whole local workflow. Robinhood quotes can be added afterward.

## 8. Train both markets with hypothetical $20 accounts

```powershell
py -3 experiment.py --output models/small-account-001
```

This runs stock and crypto training separately with $20 **each**, using invented demo prices unless you provide a mixed `--csv`. Open `models/small-account-001/summary.json` for the two heldout ending balances, baselines and limitations. Each market also gets its own policy, matching settings, report and experience log. Use a new output folder for each run. Replaying the same training prices is not additional evidence.

The $2,000 milestone is not a profit forecast or a rule forcing trades. The simulation does not model minimum orders, quantity increments, stock cash settlement or actual broker costs, so a real $20 account may not be able to execute its proposed trades. Stocks remain historical research; crypto has the first forward observation feed. See the README's independent $20 experiment section for data and forward-account commands. Existing $1,000 research/demo accounts are left intact.


## 9. Open the shared research message board

Restart `app.py` after updating, open the dashboard, then select **07 / Agent Board**. Post a note, or enter a question up to 160 characters and click **Run research meeting**. Select an existing discussion to include its recent messages. Enter `qwen3.5:4b-q4_K_M` only after it is downloaded and Ollama is running. Leave the model blank for a template-only workflow check.

The four roles run sequentially, share their preceding messages, and post concerns and next checks. Read the archived source/date on each meeting: invented demo prices remain invented. Discussions are saved in `runtime/board.sqlite`; keep that directory when replacing source files. One dashboard per board database. Meetings cannot trade, change account risk settings, or contact Discord. The Ross-inspired role is research-only until appropriate stock data and executable, tested setup rules are added.


## 10. Run safety monitoring and Discord controls

Keep all services on the same account/alerts paths. For the default demo account, open separate PowerShell terminals in the project folder:

```powershell
py -3 safety_watch.py --db runtime/demo.sqlite --alerts-db runtime/alerts.sqlite
py -3 forward.py --source demo --db runtime/demo.sqlite --alerts-db runtime/alerts.sqlite
py -3 app.py --paper-db runtime/demo.sqlite --alerts-db runtime/alerts.sqlite
```

The watchdog can start first and record a missing-account notice; the worker creates that account. Monitor **08 / Safety & Alerts**. Once worker/data failures latch a stop, keep the worker running so fresh observations can return. Click **Acknowledge restored connection**, then **Resume paper trading**. Acknowledgement requires a healthy worker and fresh receipts; a drawdown halt remains. Emergency stop retains positions and cancels pending virtual intents.

For Discord, install the optional packages and make a local config:

```powershell
py -3 -m pip install -r requirements-control.txt
New-Item -ItemType Directory -Force secrets
Copy-Item discord.example.json secrets/discord.json
notepad secrets/discord.json
```

Create a Discord application/bot in the Developer Portal. Enter its token locally, enable Discord Developer Mode to copy your user ID, private server ID and private alert channel ID, then fill the config. Install the bot with `bot` and `applications.commands` scopes. Give it View Channel and Send Messages in that private channel; administrator permission and message-content intent are unnecessary. Restrict the channel to you and the bot. Start:

```powershell
py -3 discord_control.py --db runtime/demo.sqlite --alerts-db runtime/alerts.sqlite --board-db runtime/board.sqlite
```

Starting the configured Discord service makes it a required dependency. Wait for connection/delivery to recover, then acknowledge and resume if startup latched the account. Slash commands are owner-only and restricted to your configured server. Do a demo drill: emergency-stop; verify no fills and your alert; try resume before acknowledgement (should reject); restore healthy services; acknowledge; verify still paused; resume. Test disconnects using demo money only. Queued alerts deliver after connectivity returns. Do not send the token to chat or commit the config.

For the independent $20 crypto account, change **every** `--db`/`--paper-db` to `runtime/crypto20-demo.sqlite` and supply `--config config.20-crypto.json` to the worker. Preserve existing account/provider/candle options when resuming. This release monitors one configured account per service set.

## 11. Access the dashboard privately from your site

Use a dedicated hostname, for example **trading.blighted.world**. In Cloudflare Zero Trust, create a self-hosted Access application for that exact hostname and an Allow policy for only your sign-in email. Note your team domain and application AUD. Use a short session duration you are comfortable with.

```powershell
Copy-Item access.example.json secrets/access.json
notepad secrets/access.json
py -3 app.py --paper-db runtime/demo.sqlite --alerts-db runtime/alerts.sqlite --access-config secrets/access.json
```

Fill `host`, `team`, `audience` and `email` with your actual values. Route the protected hostname in your existing Cloudflare Tunnel to `http://localhost:8002`; preserve the external Host header. Open the hostname over HTTPS and sign in through Access. With remote mode on, opening localhost without a signed Access assertion returns 403 too; restart without `--access-config` for local-only use. Do not expose port 8002 directly or route the plain local-only mode onto the public website. Origin verification rejects bad/missing signed assertions even if an Access policy is accidentally weakened. An owner email change requires editing the local config and restarting.

This prepares code and instructions; your Discord app, credentials, Access policy and tunnel hostname are not connected yet. No real orders exist. Arrange automatic startup for the worker/watchdog/Discord services before relying on unattended operation, and use an external heartbeat service if you want notification while the entire host is offline.


## 12. Switch to one server manager

Stop manually started service terminals first. Install the shared optional dependencies, create the deployment file, and launch:

```powershell
py -3 -m pip install -r requirements-control.txt
Copy-Item deployment.example.json deployment.json
notepad deployment.json
py -3 server_manager.py
```

Or double-click **start-manager.bat**. Keep its terminal open. The browser can be closed without stopping supervision. Default dashboard: `http://127.0.0.1:8002`. Manager RPC port 8004 is private loopback only; never publish it through your tunnel. Open **09 / Server & Setup** to inspect checks and fixed-service controls. Saving deployment changes requires stopping/restarting the manager. Stop/restart of the dashboard or Discord itself interrupts that interface; use the other interface or the manager terminal as needed.

Enable `discord_enabled`/`remote_enabled` only after completing the local secret files in steps 10–11. Add `discord` to `auto_start` when enabling it (the guided form handles this). Add `ollama` only if you want the manager to launch it and another Ollama service is not already running. A frozen-policy worker is not selectable through this first manager version; use the existing manual worker workflow for policy testing.

For $20 demo paper trading, use `account_db: runtime/crypto20-demo.sqlite` and `settings: config.20-crypto.json`. Keep all other options identical to an existing account or select a fresh database. New manager startup keeps paper trading safety-stopped: wait for healthy observations and optional required Discord delivery, acknowledge, then resume manually. No real orders are supported.

View **10 / Trade Journal** and **11 / Scoreboard**. Candidate scoreboard results are historical diagnostics, not live recommendations. The readiness panel must never show funded trading available. Daily recap hour uses UTC; preview shows lifetime balances and costs with separate last-24-hour event counts. Recaps are queued by the manager and delivered by Discord if configured.

Backups are under `runtime/backups`. A staged restore goes under `runtime/restores` and remains paused. Do not overwrite a running account. Stop the manager and all services before changing paths to recovered databases; keep credentials separately and copy verified backups to another device for drive-loss protection.

To opt into automatic manager startup when **you sign into Windows**, run locally:

```powershell
.\install-startup.ps1
```

If your Windows policy blocks local scripts or task creation, review that host policy before proceeding; this installer does not bypass it. It is sign-in startup, not pre-login service hosting. To remove it:

```powershell
.
emove-startup.ps1
```

Before leaving it unattended, test a demo worker crash, manager restart, Discord outage, feed interruption, backup/staged restore and Windows reboot. Confirm only the expected owned processes are restarted, retry blocks are visible, and no restart clears the account stop. Windows task installation and your actual connections remain untested until you perform this host drill.
