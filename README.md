# Trading Logic · 0.2.0

A local stocks-and-crypto research desk with CPU reinforcement learning, an optional Ollama paper agent and a read-only official Robinhood Crypto quote adapter. All trading in this version uses virtual cash. There is no live order placement code.

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

The adapter is a separate **quote snapshot tool** in this version. It is not yet connected to the historical paper engine or dashboard, and there is no stock feed attached.

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

## Validation and next steps

```powershell
python -m unittest discover -s tests -v
```

Optional UI parser checks, if Node.js is installed: `node tests/test_dashboard.cjs`.

Tests cover reinforcement reward/Bellman updates, terminal accounting, no-learning evaluation, reproducibility, test-tail isolation, frozen-policy loading, next-bar timing, shared cash and costs, drawdown override, chronological AI evidence, hold behavior, failed AI requests, holdout selection isolation, CSV validation, Ollama schema/local checks, Robinhood signing and quote validation, and HTTP isolation/error preservation.

Next work: persist forward paper portfolios; gather verified stock bars and Robinhood crypto observations; model spreads/fees from actual data; compare AI proposals with a fixed baseline; handle missing/stale quotes, outages and restart recovery. A real-money execution adapter would be a separate later feature with explicit account authorization, reconciliation and order limits.
