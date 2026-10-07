"""Train stock and crypto policies separately with $20 each; hypothetical target, no real orders."""
import argparse
import json
from pathlib import Path
from scout.core import Settings
from scout.data import demo_bars, parse_csv
from scout.experiments import train_markets
from scout.learning import LearningConfig


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--csv', type=Path, help='Mixed stock/crypto OHLCV CSV. Without it, uses invented demo prices.')
    parser.add_argument('--config', type=Path, help='Risk/cost settings; capital and allocations are set by the experiment.')
    parser.add_argument('--capital', type=float, default=20)
    parser.add_argument('--target', type=float, default=2000, help='Research milestone only; not a target used to select policies.')
    parser.add_argument('--episodes', type=int, default=200)
    parser.add_argument('--seed', type=int, default=666)
    parser.add_argument('--output', type=Path, default=Path('models/small-account-001'))
    args = parser.parse_args()
    if args.output.exists():
        parser.error('Output folder already exists. Choose a new run name; prior runs are never overwritten.')
    try:
        bars = parse_csv(args.csv.read_text(encoding='utf-8-sig')) if args.csv else demo_bars()
        settings = Settings(**(json.loads(args.config.read_text()) if args.config else {})).validate()
        source = 'uploaded_csv' if args.csv else 'synthetic_demo'
        def progress(kind, row):
            print(f"{kind}: episode {row['episode']}/{args.episodes} | training net {row['net_return_pct']:.2f}%", flush=True)
        runs, summary = train_markets(bars, args.capital, args.target,
                                     LearningConfig(episodes=args.episodes, seed=args.seed), settings, source, progress)
        args.output.mkdir(parents=True, exist_ok=False)
        def save(path, value):
            path.write_text(json.dumps(value, indent=2, allow_nan=False), encoding='utf-8')
        save(args.output/'summary.json', summary)
        for kind, run in runs.items():
            folder = args.output/kind
            folder.mkdir()
            save(folder/'policy.json', run['policy'])
            save(folder/'candidate-policy.json', run['candidate'])
            save(folder/'report.json', run['report'])
            save(folder/'settings.json', run['report']['settings'])
            with (folder/'experience.jsonl').open('w', encoding='utf-8') as stream:
                for row in run['experience']:
                    stream.write(json.dumps({'source': source, 'dataset_sha256': run['report']['dataset_sha256'],
                                             'episode': args.episodes, **row}, allow_nan=False)+'\n')
            goal = summary['markets'][kind]['goal']
            print(f"{kind}: heldout ending balance ${goal['heldout_ending_net_liquidation_equity']:.2f} | {run['report']['status']}")
        print('Saved:', args.output)
        print('Two independent hypothetical accounts; do not add their balances. No live trading readiness established.')
        if source == 'synthetic_demo':
            print('Invented prices: this demonstrates the workflow, not potential earnings.')
    except (ValueError, TypeError, OSError) as exc:
        parser.exit(1, 'Experiment failed: '+str(exc)+'\n')


if __name__ == '__main__':
    main()
