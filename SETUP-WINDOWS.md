# Trading Logic · Windows setup for when you're home

Start with the dashboard and demo training. Add Ollama after those work, then optionally set up read-only Robinhood crypto quotes. Your website and Dark Sector can keep running on their existing ports.

## 1. Download the latest project

1. Open [Trading-Logic on GitHub](https://github.com/BlightedWorld0666/Trading-Logic). Sign in if the repository asks you to.
2. Select **Code → Download ZIP**.
3. Right-click the ZIP → **Extract All**. Pick a permanent folder you can find again.
4. Open the extracted folder that contains `app.py`, `train.py`, and `start-scout.bat`. Avoid running files from inside the ZIP.
5. To open a terminal in this folder, click File Explorer's address bar, type `powershell`, and press Enter.

All commands below run from that project folder. You don't need VS Code, Git, Node.js, or a Cloudflare change to start.

Already have a Git checkout? Run `git pull --ff-only` from that checkout instead of downloading again. Keep your existing `models`, `reports`, and `secrets` folders when updating.

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

This feature currently fetches **read-only quote snapshots**. It is separate from the dashboard and paper engine. It cannot place an order or turn the replay into a live paper account.

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

## 7. Real historical data comes next

Once the demo workflow works, put a verified USD OHLCV CSV in a local `data` folder. Training supports 1–4 symbols and needs at least 150 distinct timestamps, including at least 40 training and 20 validation/test bars per symbol. See [README.md](README.md#import-historical-data) for the CSV format and data requirements.

```powershell
py -3 train.py --csv data/history.csv --config config.example.json --learning-config learning.example.json --output models/training-real-001
py -3 paper.py --csv data/history.csv --config config.example.json --policy models/training-real-001/policy.json --steps 20 --output reports/real-policy-paper-001.json
```

Use the same risk/cost settings and symbols for training and policy replay. Costs in the example config are illustrative; replace them with verified assumptions for your dataset.

Training uses 60% of timestamps to learn, 20% to select a checkpoint, and 20% for a frozen final test. Replaying those prices again is not new forward evidence. This version does not continuously collect live stock/crypto data or place Robinhood trades.

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
