# Trading Logic · 0.3.1

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
