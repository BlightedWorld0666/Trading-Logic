"""Train a CPU-only virtual-portfolio policy, freeze it, and evaluate an untouched final period."""
import argparse
import json
from pathlib import Path
from scout.core import Settings
from scout.data import demo_bars, parse_csv
from scout.learning import LearningConfig, train


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--csv',type=Path)
    parser.add_argument('--config',type=Path)
    parser.add_argument('--learning-config',type=Path,help='Learning parameters JSON; see learning.example.json.')
    parser.add_argument('--episodes',type=int)
    parser.add_argument('--seed',type=int)
    parser.add_argument('--output',type=Path,default=Path('models/training-001'))
    args=parser.parse_args()
    if args.output.exists():parser.error('Output folder already exists. Use a new run name to preserve previous training.')
    try:
        bars=parse_csv(args.csv.read_text(encoding='utf-8-sig')) if args.csv else demo_bars()
        settings=Settings(**(json.loads(args.config.read_text()) if args.config else {})).validate()
        learning=json.loads(args.learning_config.read_text()) if args.learning_config else {}
        if not isinstance(learning,dict):raise ValueError('Learning config must be an object.')
        if args.episodes is not None:learning['episodes']=args.episodes
        if args.seed is not None:learning['seed']=args.seed
        config=LearningConfig(**learning).validate()
        def progress(row):
            print(f"Episode {row['episode']}/{config.episodes} | reward {row['reward']:.5f} | net {row['net_return_pct']:.2f}% | states {row['states']}",flush=True)
        source='uploaded_csv' if args.csv else 'synthetic_demo'
        policy,report,experiences,candidate=train(bars,settings,config,source,progress)
        args.output.mkdir(parents=True,exist_ok=False)
        (args.output/'policy.json').write_text(json.dumps(policy,indent=2,allow_nan=False),encoding='utf-8')
        (args.output/'candidate-policy.json').write_text(json.dumps(candidate,indent=2,allow_nan=False),encoding='utf-8')
        (args.output/'report.json').write_text(json.dumps(report,indent=2,allow_nan=False),encoding='utf-8')
        with (args.output/'experience.jsonl').open('w',encoding='utf-8') as stream:
            for row in experiences:
                stream.write(json.dumps({'source':source,'dataset_sha256':report['dataset_sha256'],
                                         'episode':config.episodes,**row},allow_nan=False)+'\n')
        print('Saved training run:',args.output)
        print('Selected:',policy['algorithm'],'/ checkpoint:',report['selected_episode'])
        print('Untouched test net:',round(report['test']['net_return_pct'],2),'% / status:',report['status'])
        if source=='synthetic_demo':print('Invented demo data: these results provide no evidence of profit.')
    except (ValueError,OSError,TypeError) as exc:
        parser.exit(1,'Training failed: '+str(exc)+'\n')

if __name__=='__main__':main()
