"""Inspect, pause/resume, back up or export a local virtual account."""
import argparse
import json
from pathlib import Path
from scout.account import Account


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--db',type=Path,default=Path('runtime/demo.sqlite'))
    mode=p.add_mutually_exclusive_group()
    mode.add_argument('--pause',action='store_true');mode.add_argument('--resume',action='store_true')
    mode.add_argument('--export-csv',type=Path);mode.add_argument('--backup',type=Path)
    args=p.parse_args()
    try:
        a=Account(args.db)
        if args.pause or args.resume:a.control(args.pause)
        if args.export_csv:print('Sampled midpoint CSV:',a.export_csv(args.export_csv))
        elif args.backup:print('SQLite backup:',a.backup(args.backup))
        else:
            r=a.snapshot();s=r['state']
            print(json.dumps({'source':s['config']['source'],'cash':s['cash'],'equity':s['equity'],
                              'positions':s['positions'],'pending':s['pending'],'paused':s['paused'],
                              'halted':s['halted'],'health':s['health'],'worker_active':r['worker_active'],
                              'receipt_fresh':r['receipt_fresh'],'receipt_age_seconds':r['receipt_age_seconds'],
                              'completed_candles':r['completed_candles']},indent=2))
    except (ValueError,OSError) as exc:p.exit(1,'Account operation failed: '+str(exc)+'\n')

if __name__=='__main__':main()
