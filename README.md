# Trading Logic · 0.6.0

**Start here:** [Windows setup guide](SETUP-WINDOWS.md) — dashboard, training, Ollama, and optional Robinhood quotes in order.

A local stocks-and-crypto research desk with CPU reinforcement learning, an optional Ollama paper agent and a read-only official Robinhood Crypto quote adapter. All trading in this version uses virtual cash. The forward worker can read Robinhood crypto observations, persist a virtual account and monitor it locally. There is no live order placement code.

## Open the desk on Windows

Install Python 3.10 or newer. Download this repository and extract it, then double-click **start-scout.bat**. Open **http://127.0.0.1:8002**. The website and Dark Sector can keep using ports 8000 and 8001.

Or run in a terminal from this folder:

```powershell
python app.py
```

The desk runs without extra Python packages. Keep it on your PC; do not route it through your public Cloudflare tunnel. The server binds to loopback, verifies Host and a per-session request token, and accepts only its explicit static files and API routes.

## What the first version does

- Combines stock and crypto simulations under one cash balance.
- Compares fixed trend, reversion, breakout and cash candidates using the first 70% of timestamps; evaluates the fixed selections on the last 30%.
- Models configurable fees, adverse slippage, entry allocation limits and a shared drawdown halt.
- Displays equity, strategy diagnostics, comparisons and fills; exports the full report as JSON.
- Uses Ollama either to explain a report or propose buy/sell/hold actions during a historical paper replay. The deterministic simulator controls sizing and risk.
- Can fetch a Robinhood Crypto quote snapshot using a locally stored, read-only API credential.

The default dataset is **invented**, including its asset names. Its results are a workflow demonstration, not evidence of profit. The defaults are illustrative assumptions, not investment allocations or verified broker fees. Combining stocks and crypto does not guarantee better performance.

## Import historical data

CSV columns:

```csv
timestamp,symbol,asset_class,open,high,low,close,volume
2024-01-02T21:00:00Z,EXAMPLE,stock,100,102,99,101,100000
```

Use `stock` or `crypto`, timezone-aware ISO timestamps, finite positive USD prices and consistent OHLC bounds. Provide at least 100 distinct timestamps, with at least 40 training and 20 holdout bars per symbol. Include both asset classes for the combined research desk. Limit: 12 symbols, 20,000 rows and 1 MB dashboard uploads. Adjust corporate actions consistently and record where your data came from; the importer cannot verify provenance.

For a report without the dashboard:

```powershell
python app.py --csv data/history.csv --config config.example.json --report reports/study.json
```

Signals use completed bars; fills occur at the next available bar's open. When a market has no bar, it cannot fill an order and its last mark stays stale. Entry caps are not continuous rebalancing limits. The drawdown halt queues exits at available bars; it cannot guarantee a maximum loss through gaps. Final equity deducts estimated closeout costs on open positions, not actual closeout executions.

No taxes, dividends, borrow costs, splits, liquidity, latency or market impact are simulated. Candidate holdout diagnostics are shown for inspection; repeatedly choosing strategies from them contaminates the test. Use a genuinely new period for further evaluation.

## Point paper trading at Ollama

1. Install and start [Ollama](https://ollama.com/), download a local model, and use `ollama list` to copy its exact name.
2. Disable Ollama cloud by setting the Windows user environment variable **OLLAMA_NO_CLOUD=1**, then fully quit and restart Ollama. See the [official local-only configuration](https://docs.ollama.com/faq). Keep Ollama at its default loopback address.
3. The desk's **Local AI** tab can review the current research report.
4. To let the model actually propose simulated actions, run this from the repository folder, replacing `YOUR_LOCAL_MODEL`:

```powershell
python paper.py --model YOUR_LOCAL_MODEL --steps 20 --output reports/paper-001.json
```

For your own data, add `--csv data/history.csv --config config.example.json`.

This is **historical paper replay**, not a continuously running forward paper account. Each step shows Ollama only the completed history available at that step; the next available open fills its proposals. The model can say buy, sell or hold for the supplied symbols. It cannot alter cash, sizes, limits or fees. Malformed responses and connection failures become hold actions; the drawdown halt overrides the model and stops further AI calls. The ledger records decisions, error types and simulated fills. A requested output filename must be new so earlier logs are preserved.

Local requests use `http://127.0.0.1:11434/api/tags`, `/api/show` and `/api/chat`, reject cloud names/remote model metadata, require local weight metadata, reject redirects, and validate structured responses. Disable cloud in Ollama itself as described above; application checks are not a substitute for correct daemon configuration.

A model may have learned facts from a historical replay period during training. AI replay is therefore not an untouched predictive test, even though supplied bars are chronological. First collect forward results on verified data before judging it. The last replay decision has no following bar and may remain unfilled.

The optional AI workflow was tested with mocked Ollama responses; no real model inference has been verified in this development environment. Hardware speed depends on your installed model and Ollama backend.

## Training and reinforcement learning · 0.2.0

The new **Training** tab explains the workflow and opens a saved training `report.json` locally. Training itself runs in the terminal so it cannot block the research server. The original strategy desk keeps its separate 70/30 split; reinforcement training uses **60/20/20**.

Start a reproducible CPU-only training run with invented demo data:

```powershell
python train.py --output models/training-001
```

For verified historical stock/crypto bars:

```powershell
python train.py --csv data/history.csv --config config.example.json --learning-config learning.example.json --output models/training-002
```

This alpha supports **1–4 symbols**, at least **150 distinct timestamps**, and per-symbol minimums of 40 training bars plus 20 validation and 20 test bars. A crypto-only or stock-only training portfolio is supported as well as a combined one. `--episodes 50` and `--seed 123` override the optional learning config. The default is 200 episodes with seed 666. Use a new output folder for each run; existing outputs are preserved. No GPU or extra Python packages are needed.

**What is reinforced:** a joint-action tabular Q-learning policy targets each asset long or flat. The simulator performs next-available-open fills, sizes positions, applies fees/slippage and enforces shared risk limits. Exploration declines linearly from 80% to 5% during training and is disabled for evaluation/replay. States use fixed bins for history readiness, past 10/30 trend, five-bar momentum, held positions, cash fraction and drawdown. An unseen state targets cash. This coarse state representation omits important market information and is not a complete Markov market model.

Reward per transition:

```text
log(next net liquidation equity / previous net liquidation equity)
- drawdown_penalty × increase in maximum marked-equity drawdown
- turnover_penalty × traded notional / starting capital
```

Fees and adverse slippage already affect net equity. Estimated liquidation costs are included in that valuation; turnover is an additional preference penalty, not another broker fee. Default drawdown penalty is 2 and turnover penalty is 0.0005. These choices are experiment settings, not optimized or validated financial advice. Terminal transitions do not bootstrap future reward. If the shared halt prevents further decisions, the last action receives its terminal outcome including delayed exits and final estimated closeout costs.

**Training protocol:** only the earliest 60% updates Q values. Four prespecified checkpoints (25%, 50%, 75%, 100% of episodes) compete with cash on the next 20%, using net return percentage minus 1.5 times maximum drawdown percentage. Cash wins ties. The selected policy is then frozen and evaluated once on the last 20%, alongside fixed cash, trend and buy-and-hold baselines. All periods start with fresh virtual capital and can use earlier completed bars as feature warmup; they do not carry training positions forward.

Each run writes:

| File | Purpose |
| --- | --- |
| `policy.json` | Validation-selected frozen policy; may intentionally be cash |
| `candidate-policy.json` | Best learned Q-policy checkpoint by validation score, preserved for research even if cash won |
| `report.json` | Training progress, checkpoint scores, frozen test fills/metrics and baseline comparisons |
| `experience.jsonl` | Final training episode's state/action/reward/next-state/terminal transitions, labeled with episode and source |

Outputs contain dataset fingerprints, settings, split dates and seed for reproducibility. Repeated episodes replay the **same training prices**; they are not independent samples. Experience logs are not labeled as the selected checkpoint's experiences and are not automatically ingested as language-model training data. Generated outputs stay in ignored `models/` folders on your PC.

Use the selected policy in the existing paper engine:

```powershell
python paper.py --policy models/training-001/policy.json --steps 20 --output reports/policy-paper-001.json
```

Use the same `--csv` and `--config` as training when applicable. The loader requires matching symbols, asset classes, risk settings and costs; it rejects non-finite or incorrectly shaped Q tables. A paper replay cannot update the Q table. You can explicitly choose `candidate-policy.json` for research; that does not mean it beat cash or became eligible for real execution.

**Ollama and this learner are separate:** Ollama remains the local language-model reviewer/proposal generator. This update trains a numerical trading policy; it does not fine-tune or reinforce Ollama's language-model weights. Any future LLM fine-tuning needs a separate trainer and audited dataset, followed by model import for inference; see [Ollama model import](https://docs.ollama.com/import). No automatic feedback loop learns from real account balances or places live orders.

Validation can itself overfit a small dataset. Once you inspect a final test, do not reuse that period as “untouched” while changing parameters. Neither demo nor historical performance promotes a model into live trading: new verified forward paper data, robustness checks and separate execution authorization are still needed. The initial demo selected cash in validation despite improved training returns, which demonstrates why training profit alone is insufficient.

## Robinhood Crypto setup · read-only first

Robinhood has an [official US Crypto API](https://robinhood.com/us/en/support/articles/crypto-api/) with v1/v2 endpoints. This adapter uses the v2 best bid/ask endpoint. API access and available pairs depend on your account and jurisdiction. Quotes exclude order-size effects and fees and are not guaranteed execution prices. This is not an official Robinhood paper-trading account.

The standalone adapter is a **quote snapshot tool**. Version 0.3 also connects it to a persistent forward virtual crypto worker and its dashboard monitor. No live stock feed is attached.

Install its optional signing dependency:

```powershell
python -m pip install -r requirements-robinhood.txt
python robinhood_quotes.py --generate-key
```

This prints only your **public key** and saves the private key into the ignored local `secrets/robinhood.json`. Register the public key through Robinhood's desktop crypto account settings → Add key. Enable **Read crypto quotes** only. Enter the resulting API key directly into the local JSON file's `api_key` field.

```powershell
python robinhood_quotes.py --symbols BTC-USD ETH-USD
```

Keep the private key and API key on your PC. Do not paste them into chat, commit them, or publish the secrets folder. On Windows, restrict access to that file to your Windows user; the POSIX file mode used by the generator alone does not configure Windows ACLs. Key generation refuses to overwrite an existing file.

Requests use Ed25519 signatures over the API key, timestamp, full path including query, GET method and empty body, following the [official API documentation](https://docs.robinhood.com/crypto/trading/). Only a fixed GET quote endpoint is present; no order/cancel routes or AI-generated URLs are accepted. The snapshot records receipt time, not exchange freshness, because this endpoint does not supply an exchange timestamp. Real credentialed access has not been tested here.

## Persistent forward paper account · 0.3.0

This is a new, continuously running **virtual crypto account**, separate from historical `paper.py` replay. It can collect Robinhood read-only quotes, persist positions and pending intents, and survive worker restarts without resetting capital. It never submits a broker order.

Try the invented live demo in one terminal:

```powershell
python forward.py --source demo --db runtime/demo.sqlite --interval 2 --bar-seconds 60
```

Run `python app.py` in another terminal, open port 8002 and select **Forward Paper**. The invented demo source is clearly labeled and uses the pair names only as fictional placeholders. It is not live market data.

After local Robinhood credential setup, use a separate account database:

```powershell
python forward.py --source robinhood --db runtime/crypto.sqlite
python app.py --paper-db runtime/crypto.sqlite
```

Run those in separate terminals. Default symbols are BTC-USD and ETH-USD, subject to your account's available pairs. Default live polling is every 60 seconds; the CLI enforces at least 30 seconds for Robinhood. Default sampled candle size is five minutes. Polling must be at most one quarter of the selected candle size to support sample coverage. `forward.example.json` defines virtual capital and illustrative costs/risk assumptions. It allocates no stock budget; this worker is crypto-only for now.

**Decision providers:** default is a fixed 10/30 trend rule. Use `--strategy cash` to observe without entering positions; `--strategy reversion` or `--strategy breakout` selects another fixed rule. For Ollama, create a separate account with `--model qwen3:4b`. For a frozen learned policy, use `--policy path/to/policy.json`; its symbols, crypto asset classes and risk/cost settings must match. Use `--config` when training and running a policy with the forward settings. Existing accounts pin source, symbols, settings, candle size and provider identity, including a policy file hash. To change those, create a new database; restarting with matching options retains the existing account. No automatic retraining occurs.

The worker waits for **30 consecutive eligible completed sampled candles** for every symbol before proposals, including Ollama. Five-minute candles therefore need approximately 2.5 hours of uninterrupted collection, plus startup alignment; the one-minute demo needs about half an hour. The equity/risk monitor runs on every accepted quote while warming up.

**Receipt freshness:** the Robinhood endpoint does not supply exchange timestamps. The worker checks local receipt age (default 90 seconds), reported request latency (at most 10 seconds), source, all requested symbols and finite uncrossed prices. These cannot detect an upstream cached/stale quote. Nonincreasing receipt timestamps cannot advance the account or repeat a fill. Poll failures cancel pending intents and retain balances; the next accepted quote resumes observation. Gaps longer than the configured collection threshold cancel old intents and invalidate continuity. Paused accounts continue observations and equity marking.

**Sampled candles:** OHLC uses periodically sampled **quote midpoints**, not exchange trades. Volume is explicitly zero/unknown; intrabar extremes can be missed. Building candles survive restarts. Startup/collection-gap candles are excluded from the eligible decision history and CSV export. Eligibility requires at least two samples, first/last observations spanning the outer quarters of a bucket, and no detected collection gap. This is a sampling-quality check, not exchange-bar verification. No missing buckets are interpolated. A rejected candle resets consecutive policy warmup history.

**Virtual execution:** valid proposals create persisted intents; fills occur at a later accepted observation, never the same snapshot. Buys use ask plus adverse extra slippage, sells use bid minus extra slippage, and illustrative fees apply to each. Sizing is cost-inclusive and cash-only, with configured entry exposure caps. No size-based liquidity, partial fills, taxes or real execution latency is modeled. Equity is cash plus positions at estimated bid liquidation after modeled exit costs. The spread is reflected in equity, although the displayed extra-slippage tally excludes that spread. No estimated closeout is actually submitted to Robinhood.

**Risk and controls:** pause cancels pending intents and blocks fills, while retaining positions and collecting data. Resume does not undo a drawdown halt. A halt is sticky across restarts; it blocks entries and queues virtual exits for later fresh observations when unpaused. Gaps can exceed the drawdown threshold. Exits-before-entries and pre/post-fill risk checks share the same account. Slow/in-flight proposals are discarded if controls or observations changed, the bar was already decided, or receipt age expired. Pending intents expire after 900 seconds by default. No automatic equity reset or halt reset exists.

**Persistence:** SQLite transactions save balances, fills, observations and decisions together. A worker lease prevents concurrent workers on the same account and fences a superseded worker. The lease may remain visible briefly after a crash until it expires. A graceful Ctrl+C releases it; a crashed worker may need up to a few minutes before restart. A stopped worker cannot observe markets or execute even virtual exits. Retained pending intents can resume on restart only if fresh, unexpired and uninterrupted by a detected gap. Database/source/provider mismatch and unsupported/corrupt databases fail without resetting funds.

Runtime databases and credentials are git-ignored. Quote snapshots retain the latest 10,000 observations; decision/fill journals and sampled candles persist. For long-running accounts, monitor disk usage and make online backups:

```powershell
python account_control.py --db runtime/crypto.sqlite
python account_control.py --db runtime/crypto.sqlite --pause
python account_control.py --db runtime/crypto.sqlite --resume
python account_control.py --db runtime/crypto.sqlite --backup backups/crypto-001.sqlite
python account_control.py --db runtime/crypto.sqlite --export-csv data/crypto-midpoints.csv
```

Backup and export refuse to overwrite an existing file. The backup API creates a consistent SQLite copy even while the worker is running; copying just the main `.sqlite` file while a WAL worker is active may miss committed changes. Restore by stopping the worker and using a backup under a new `--db` path with the same options. CSV exports retain eligible sampled midpoint OHLC and zero volume; record the Robinhood/source/sampling provenance alongside the CSV. These exports are not verified exchange OHLCV.

The dashboard monitors one account selected through `--paper-db`, refreshes while its tab is visible, and uses the same local Host/token protections for pause/resume. It has no arbitrary browser-selected file path or account key entry. The stock feed, synchronized multi-strategy benchmarking and live order execution remain future work.

Actual Robinhood credentials and live Ollama inference have not been exercised in this development environment. Tests use synthetic/mocked inputs; they establish implementation behavior, not profitability or production broker connectivity.

## Validation and next steps

```powershell
python -m unittest discover -s tests -v
```

Optional UI parser checks, if Node.js is installed: `node tests/test_dashboard.cjs`.

Tests cover reinforcement reward/Bellman updates, terminal accounting, no-learning evaluation, reproducibility, test-tail isolation, frozen-policy loading, next-bar timing, shared cash and costs, drawdown override, chronological AI evidence, hold behavior, failed AI requests, holdout selection isolation, CSV validation, Ollama schema/local checks, Robinhood signing and quote validation, and HTTP isolation/error preservation.

Next work: attach a verified stock feed; add synchronized forward benchmark portfolios and actual execution-cost estimates; model spreads/fees from actual data; compare AI proposals with a fixed baseline; handle missing/stale quotes, outages and restart recovery. A real-money execution adapter would be a separate later feature with explicit account authorization, reconciliation and order limits.

## Independent $20 stock and crypto experiment

Both markets remain in research while crypto is the first forward-feed focus. Run:

```powershell
python experiment.py --output models/small-account-001
```

This trains **two separate hypothetical accounts with $20 each**, not a shared $40 account or a claim that the same $20 is invested twice. It uses the existing 60/20/20 chronological train/validation/test split, four fixed checkpoints, and cash as a candidate. The final test cannot update the policy. The default $2,000 target is a reporting milestone only; it cannot select a model or alter training rewards. $20 to $2,000 requires a 100× balance and 9,900% total gain. No timeframe or daily income is forecast.

Without a CSV, prices are invented and cannot establish profitability. To supply a mixed stock/crypto dataset with the standard CSV columns:

```powershell
python experiment.py --csv data/verified-mixed-bars.csv --config config.example.json --output models/small-account-real-data-001
```

Use up to four symbols **per market**, with at least 150 distinct timestamps and the existing per-symbol split requirements. Document data provenance/stock adjustments; the tool cannot verify a CSV simply because it was supplied. Reusing a test dataset after inspecting it is not a fresh test. `--capital`, `--target`, `--episodes`, and `--seed` are configurable. Capital/market allocation come from the experiment; fees, slippage and risk limits come from the optional config.

The output includes `summary.json`, plus each market's frozen `policy.json`, `candidate-policy.json`, `report.json`, matching `settings.json`, and training experience. Summaries show heldout ending net liquidation equity, losses/gains, drawdown, fills, and cash/trend/buy-and-hold baselines. Checkpoints describe the ending balance, not an invented path through milestones. Existing output folders are never overwritten.

**Small-account execution remains unmodeled:** historical simulations allow unconstrained fractional quantities and proportional costs; minimum orders, quantity increments, liquidity, actual spreads, taxes and stock cash settlement are not modeled. Consequently a $20 simulation is largely a scaled version of a larger one, not evidence those orders could execute in a real account. The software does not claim live readiness or account eligibility, even if a simulation reaches $2,000.

`config.20-crypto.json` and `config.20-stock.json` are illustrative $20 profiles. For an independent $20 crypto **demo forward account**, use a new database:

```powershell
python forward.py --source demo --config config.20-crypto.json --db runtime/crypto20-demo.sqlite --interval 2 --bar-seconds 60
python app.py --paper-db runtime/crypto20-demo.sqlite
```

These fictional forward observations do not measure earnings. For a read-only Robinhood forward experiment after credential setup, replace `--source demo` with `--source robinhood`, remove the accelerated interval/bar options, and choose a **new** database such as `runtime/crypto20-quotes.sqlite`. The balances and orders remain virtual. A frozen policy requires matching symbols, classes and settings; demo symbol policies cannot be applied to real BTC/ETH feeds. The forward account models bid/ask execution estimates, but broker minimums/increments remain unmodeled. No additional deposits or real orders are made.


## Shared agent research board · 0.4.0

Open **07 / Agent Board** in the local dashboard. Post notes in a new or existing discussion. Select an existing thread and ask a short question to start a new research meeting that carries its recent messages forward. The board stores archived report ID, data source, capture time, author, reply references and meeting status. Messages survive restarts in `runtime/board.sqlite`; neither a model response nor a board vote can change the forward account or send orders.

The meeting roles are:

| Role | Research responsibility |
| --- | --- |
| Steady strategy researcher | Evaluate trend, reversion, breakout and cash alternatives; repeatable net performance is the hypothesis. |
| Momentum specialist | Research Ross Cameron-inspired stock momentum setups and identify missing scanner, float, catalyst, volume and execution evidence. |
| Risk reviewer | Challenge preceding proposals, costs, correlated exposure, drawdown and stale observations. |
| Coordinator | Describe disagreement and choose the next research checks, without execution authority. |

Supply the exact downloaded Ollama model name, e.g. `qwen3.5:4b-q4_K_M`, to run four sequential reviews against one frozen evidence snapshot. Later roles read preceding role messages and the selected discussion's recent notes. This uses **one model with separate prompts**, not four independently trained models. Shared agreement is not independent confirmation. Replies are bounded, unverified commentary; model text is displayed as plain text and never executed. Existing local-model checks block cloud/remote models and redirects. Actual Ollama inference still needs to be verified on your host PC.

Leave the model blank to exercise the board using clearly labeled **template** messages. Templates are fixed research reminders, not AI conversation or market analysis. Meetings run in the background; the visible board refreshes every five seconds. One meeting runs per dashboard process at a time. Errors retain earlier messages and mark the meeting failed. Restart marks unfinished meetings interrupted; it does not rerun them or restore a model's private reasoning. Run only **one dashboard process per board database**. Use `--board-db PATH` for a different board. Latest 50 threads and latest 100 messages per thread are displayed; older records remain in SQLite. Retain the runtime directory when updating the project. User notes are local, with no Discord/email posting.

Each meeting includes the current historical report and a read-only snapshot of the configured forward paper account, including recent journal entries. These are archived observations, not a continuously updating trading feed. A forward worker still runs its existing configured provider and risk controls independently. Starting a meeting does not turn its research roles into trading agents. Meetings are manually requested; no autonomous scheduling or stock execution is attached.

### Momentum research sequence

1. Add timestamped stock OHLCV and point-in-time float/catalyst data; prevent future news and survivorship leakage.
2. Specify a bull-flag detector's entry, invalidation and exit rules, then freeze them before unseen evaluation.
3. Add a resistance-breakout candidate and compare each against cash and simpler momentum baselines.
4. Model spreads, latency, partial fills, halts, gaps, minimum orders and session rules before considering broker execution.
5. Evaluate quiet and active market periods separately; preserve a shared capital budget and hard risk controls if execution agents are introduced later.

No Ross-style scanner or setup detector is implemented yet. Existing sampled midpoint crypto candles have unknown volume and cannot validate stock relative-volume, news or Level 2 strategies. Crypto momentum needs its own data and evaluation. Profitability and high-revenue days are not established by this board.


## Safety controls and remote owner access · 0.5.0

The configured **forward virtual account** now has a persistent safety latch. Feed/provider errors, stale receipts, observation gaps, expired/missing workers, and required Discord delivery failures stop all strategies attached to that account. They cancel pending virtual intents, preserve balances/positions, increment the control revision to reject late inference, and block resume. Data may continue arriving while paused to establish recovery. A successful connection does not clear the stop.

**Recovery is two deliberate actions:** acknowledge once a healthy worker and fresh receipts return (plus Discord delivery when configured as required), then resume. Acknowledgement retains pause. The separate sticky drawdown halt is never cleared by acknowledgement or resume. Existing databases get a default safety field without resetting funds or requiring a new schema. Dashboard **08 / Safety & Alerts**, owner-only Discord commands and `account_control.py --kill/--acknowledge/--resume` use the same controls.

This is not liquidation: open positions can lose value during an outage. No actual broker order cancellation, flattening or server-side protective orders are implemented because the project has no real execution adapter. Account controls apply to the **one configured database**, not other databases or external broker accounts. Each additional account needs its own correctly configured services until a multi-account controller is built.

### Independent monitoring and durable alerts

Run `safety_watch.py` separately from the worker/dashboard. The worker checks safety before each feed poll, the dashboard has its own five-second guard, and the independent watchdog detects failure even if either process stops. Quote age uses the account's configured receipt threshold (normally 90 seconds); worker checks use lease expiry; Discord heartbeat expires after 30 seconds. Faults are therefore detected within these bounds plus polling/processing delay, not instantly. Broker receipt freshness still cannot prove upstream quote freshness.

The alerts database stores minimal operational events, a durable delivery queue, delivery attempts and errors. Event IDs deduplicate polling, alerts retain their original time, and local failures never automatically reset either database. Discord delivery retries when connectivity returns. Delivery is at least once: a crash after Discord accepts a message but before its delivery acknowledgement is saved may create a duplicate. Run one Discord delivery process per alerts database. Standalone watchdogs only enqueue; the Discord process delivers. Dashboard shows the latest 100 alerts, queue count and notification health. User notes and model text are not included in automatic alerts.

Once `discord_control.py` starts with a valid configuration, Discord becomes a **required safety dependency** for that alerts database. On startup or reconnection, a stop may be latched while delivery is checked. If the bot crashes, loses its connection, cannot access its configured channel, or fails to send an alert, trading stops and stays stopped. Restore the bot/delivery, review the cause, acknowledge and resume manually. Do not delete the runtime directory to bypass this requirement. All services must use identical account and alert paths. A failed alert database also stops the monitored account when that account can still be written.

A complete host power/internet outage cannot send a message through the same host during the outage. Local alerts queue for catch-up; an external heartbeat monitor is still needed for immediate notification of a completely offline host. Windows boot services, external monitoring, credentials, server permissions and live fault drills remain host setup work.

### Owner-only Discord controls

Install `requirements-control.txt`, copy `discord.example.json` to ignored `secrets/discord.json`, and enter the bot token and exact owner/server/private alert-channel IDs **locally**. Never commit real credentials. Start `discord_control.py` with matching `--db`, `--alerts-db` and `--board-db` paths. The bot registers guild slash commands and requires both the exact owner user ID and configured guild on every interaction, including reads. It uses no message-content intent, sends control replies ephemerally, and only allows the owner mention in automatic alerts.

- `/trading_status`: virtual balances, positions, safety, receipt/worker health and queued alerts.
- `/trading_control action:kill|acknowledge|pause|resume`: persistent account controls.
- `/agent_board`: recent messages from the latest research discussion.
- `/agent_note`: add a local note, optionally to an existing discussion.

The bot does not expose real orders, arbitrary shell commands, secret changes or model-generated control actions. Research remains manually requested from the dashboard. Discord connectivity and credential-backed command registration still require testing in your private server; local tests construct the actual command tree and check authorization without connecting or posting.

### Private site dashboard

Local-only access remains the default. The optional `--access-config secrets/access.json` mode allows one configured remote hostname and validates Cloudflare Access JWT signatures, RS256, issuer, audience, expiry, token type and the exact owner email on **every HTML and API request**. Merely sending an email header is insufficient. Missing/bad tokens fail closed, including requests to localhost when remote mode is enabled. POST requests still require the per-process dashboard token and reject cross-site requests. The server remains bound to `127.0.0.1`.

Use a separate protected hostname such as `trading.blighted.world` routed through your Cloudflare Tunnel to port 8002. Create an owner-only Access application for it before routing the dashboard. Copy `access.example.json` into `secrets/access.json`, supplying the real team domain, application AUD, hostname and owner email. Install the optional dependencies before enabling this mode. The public portfolio stays separate. No DNS, tunnel, Access policy or Discord application has been provisioned by this commit; actual remote login and host configuration still need testing. See SETUP-WINDOWS.md for exact commands.


## Server manager, guided setup and research operations · 0.6.0

Install `requirements-control.txt`, copy `deployment.example.json` to ignored `deployment.json`, and launch **start-manager.bat** (or `python server_manager.py`). Stop manually started copies of the worker, watchdog, Discord bot and dashboard first. The manager runs independently from the browser and launches the fixed services in order: optional Ollama, watchdog, worker, optional Discord, dashboard. It uses the same configured account/alerts/board paths throughout. New and existing accounts are safety-stopped at manager startup; observations can warm up while paused. Acknowledgement/resume remain separate owner actions.

The manager binds to **127.0.0.1:8004** only. The dashboard and Discord proxy fixed service actions using an ignored, generated local token file. RPC calls cannot provide executable names, shell commands, log filenames or arbitrary restore paths. Never route port 8004 through Cloudflare or expose it publicly. Process launch uses argument arrays without a shell. Only manager-owned processes are stopped. An externally running Ollama server is reported and left untouched; an existing worker lease prevents duplicate workers.

Services have bounded crash recovery: exponential delay, at most three recorded exits within ten minutes before automatic restart is blocked. An explicit start/restart clears the retry block. Restarts do not resume account execution. Child process IDs, creation times and exact command lines are persisted privately, so a restarted manager can safely clean up its previously owned processes before rebuilding its service set. Reused PIDs or changed process identities are skipped. When a host process listing cannot verify a newly spawned child, that PID is not recorded and no descendant lookup is trusted; current services still use their actual Popen handles, but forced manager-crash recovery is marked as needing a host drill. Setup flags an uninspectable process namespace as not ready. The manager uses psutil for identity checks and descendant cleanup; permission failures require inspection rather than killing an unverified process. Window-specific behavior and live connections still require a host drill. Configuration is loaded at manager startup; saving new setup choices does not reconfigure running services.

### Dashboard additions

- **09 / Server & Setup:** start/stop/restart fixed services, view bounded log excerpts, check dependencies and local files, save validated deployment choices, inspect readiness, create backups and verify/stage restores, and preview a recap.
- **10 / Trade Journal:** chronological paged events including decision proposals/reasons, discarded plans, fills and their decision IDs, faults and controls. No private model reasoning is exposed. Warmup without a proposal does not invent a skipped-trade reason.
- **11 / Scoreboard:** current historical study's portfolio comparisons with cash and buy-and-hold, plus per-symbol candidate diagnostics on the same holdout. This is not a forward strategy leaderboard or proof of an edge. Fills are not completed trades, so no misleading fill-based win rate is displayed.

Setup validates paths, source/provider choices, switches and risk settings. Credentials are entered in ignored local files, never through model messages or setup form fields. Keep existing account options when resuming; use a new database for different settings/source/provider. The readiness view separately reports configuration and current paper observation health. Funded-trading readiness is permanently false until the missing order adapter, broker execution constraints, unseen/forward performance and host drills are implemented and validated. A profitable demo does not unlock real orders.

### Recaps and backups

The manager queues one daily recap after a configured **UTC** hour. It persists the day and uses a deduplication key across restarts. Missed days are not backfilled. The initial run can queue that day's recap immediately if the scheduled hour has passed. Recaps label lifetime net/equity/costs and last-24-hour event counts separately, show worker/quote health and stops, and remain paper-only. The existing Discord alert sender delivers the recap; without Discord it remains locally queued. Recaps currently do not reconstruct calendar-day P&L or completed-trade win rates.

Daily backups run once per UTC day when an account exists and `backup_daily` is true; manual backups use the same implementation. Files go to `runtime/backups/ID`, with SHA-256 checksums, SQLite integrity checks, deployment/risk settings, individually consistent account/board/alerts databases, version and frozen policies. Policy source paths are recorded in the manifest. Credentials, manager tokens, large training logs and model weights are excluded: keep a separate secure credential copy. Backups are on this PC, so copying verified backups off-device remains necessary to protect against drive loss. There is no automatic deletion/retention policy yet.

**Restore is non-destructive staging.** Select a backup and verify/stage it. Checks reject corrupt files and traversal. Recovered copies go to `runtime/restores/ID-SUFFIX`; the recovered account is explicitly safety-paused. Active files are never overwritten. Stop all services before manually configuring recovered account/board/alerts paths; inspect balances, account identity and journal, restore any frozen policy mapping, and re-enter credentials separately. Backup SQLite snapshots are individually consistent, not an atomic snapshot across all components.

Discord adds owner-only `/server_status`, `/server_control` (fixed service/action choices), `/paper_recap`, and `/backup_now`. Stopping/restarting Discord itself may interrupt the command reply; its status and log remain visible in the dashboard. Existing guild/user authorization applies to these commands too.

### Windows startup and validation

`install-startup.ps1` explicitly installs a user sign-in Scheduled Task with bounded manager restart attempts. It does not run before sign-in, does not enable automatic Windows login, and has not been executed on this Linux development host. Host policy may require additional permissions. `remove-startup.ps1` removes the task without changing already running services. A true unattended pre-login Windows service and external host heartbeat monitor remain deployment work.

Validation includes Python unit/HTTP tests, actual Discord command-tree authorization checks without connecting, signed Access token tests, Node dashboard logic checks, and an isolated POSIX real-process smoke (`python tests/smoke_manager.py`). This development sandbox exposes a different process namespace, so the real PID-recovery integration test is skipped here; identity-mismatch boundaries are tested with controlled process records. The smoke starts managed services, reads dashboard APIs, creates/verifies/stages a backup, stops the worker with its safety latch intact, and confirms child cleanup. Windows scheduling, live Discord/Cloudflare login, Ollama inference and full browser visuals still require testing on the host PC.
