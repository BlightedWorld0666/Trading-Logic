"""Run a watchdog independently of the dashboard and strategy worker."""
import argparse
from pathlib import Path
import threading
from scout.safety import monitor


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--db',type=Path,default=Path('runtime/demo.sqlite'))
    p.add_argument('--alerts-db',type=Path,default=Path('runtime/alerts.sqlite'))
    args=p.parse_args();stop=threading.Event()
    print('Safety watchdog running; alerts queued locally. Discord delivery requires discord_control.py.',flush=True)
    try:
        while True:
            try:monitor(args.db,args.alerts_db)
            except Exception as exc:print('Watchdog check failed:',type(exc).__name__,flush=True)
            stop.wait(5)
    except KeyboardInterrupt:pass

if __name__=='__main__':main()
