"""Ollama-directed historical paper replay; virtual cash only, never broker orders."""
import argparse
from dataclasses import asdict
import json
from pathlib import Path
from scout.ai import paper_decision
from scout.core import Settings, simulate
from scout.data import demo_bars, parse_csv
from scout.learning import load_policy


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode=parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--policy', type=Path, help='Frozen policy.json from train.py; no learning or exploration during replay.')
    mode.add_argument('--model', help='Exact downloaded local model name from ollama list.')
    parser.add_argument('--csv', type=Path)
    parser.add_argument('--config', type=Path)
    parser.add_argument('--steps', type=int, default=20, help='Last N observed timestamps to replay; 1–100.')
    parser.add_argument('--output', type=Path, default=Path('reports/ollama-paper.json'))
    args = parser.parse_args()
    if not 1 <= args.steps <= 100:
        parser.error('--steps must be between 1 and 100.')
    if args.output.exists():
        parser.error('Output already exists. Choose a new --output filename to preserve earlier paper logs.')
    bars = parse_csv(args.csv.read_text(encoding='utf-8-sig')) if args.csv else demo_bars()
    settings = Settings(**(json.loads(args.config.read_text()) if args.config else {})).validate()
    times = sorted({b.timestamp for b in bars})
    start = times[max(0, len(times) - args.steps)]
    symbols = sorted({b.symbol for b in bars})
    def decide(evidence, names):
        print('Paper decision:', evidence['timestamp'], flush=True)
        evidence['source'] = 'uploaded_csv' if args.csv else 'synthetic_demo'
        evidence['settings'] = asdict(settings)
        return paper_decision(args.model, evidence, names)
    provider=decide
    policy_value=None
    if args.policy:
        if args.policy.stat().st_size>20000000:parser.error('Policy file is too large.')
        policy_value=json.loads(args.policy.read_text())
        kinds={s:next(b.asset_class for b in bars if b.symbol==s) for s in symbols}
        provider=load_policy(policy_value,symbols,kinds,settings)
    result = simulate(bars, {s: 'cash' for s in symbols}, settings, start, provider)
    report = {'mode': 'historical_policy_paper_replay' if args.policy else 'historical_ollama_paper_replay', 'model': args.model,
              'policy': {'algorithm': policy_value['algorithm'], 'training_dataset_sha256': policy_value['dataset_sha256'],
                         'selected_episode': policy_value['selected_episode'], 'role':policy_value.get('role','selected_on_validation')} if policy_value else None,
              'source': 'uploaded_csv' if args.csv else 'synthetic_demo', 'settings': asdict(settings),
              'limitations': ['Virtual cash only. No real orders.',
                  'Historical replay, not live forward paper trading. Model training may include the replay period.',
                  'Demo data are invented; imported data provenance is unverified.',
                  'Next available open fills are estimates. Fees and slippage are illustrative settings.',
                  'Provider errors produce hold actions. Shared drawdown protection overrides all providers.',
                  'A trained policy is frozen here. Replaying training/validation/test prices is not new forward evidence.',
                  'Entry exposure caps can drift; missing bars leave stale marks. No liquidity or corporate actions modeled.'],
              'result': result}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, allow_nan=False), encoding='utf-8')
    failures = sum('error_type' in d for d in result['decisions'])
    if failures:
        print(f'{failures} Provider decisions failed and became holds. Inspect error_type in the log before evaluating results.')
    print('Paper log:', args.output, '/ net simulation result:', round(result['net_profit'], 2))

if __name__ == '__main__':
    main()
