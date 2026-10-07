"""Consistent per-database backups and verified, non-destructive restore staging."""
from contextlib import closing
import hashlib
import json
from pathlib import Path
import re
import secrets
import shutil
import sqlite3
from datetime import datetime, timezone
from .operations import inside
from .account import Account
from .board import Board
from .safety import Alerts


def backup(root,config):
    root=Path(root);base=root/'runtime/backups';base.mkdir(parents=True,exist_ok=True)
    identity=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+secrets.token_hex(4)
    dest=base/identity;dest.mkdir();manifest={'id':identity,'created':datetime.now(timezone.utc).isoformat(),'files':[],'policy_sources':{},'note':'Database snapshots are individually consistent, not a cross-database atomic snapshot. Credentials and model weights are excluded.'}
    try:
        for name,key,validator in [('account.sqlite','account_db',Account),('board.sqlite','board_db',Board),('alerts.sqlite','alerts_db',Alerts)]:
            source=inside(root,config[key])
            if not source.is_file():continue
            instance=validator(source)
            if name=='board.sqlite':instance.snapshot()
            if name=='alerts.sqlite':instance.snapshot()
            with closing(sqlite3.connect(source.resolve().as_uri()+'?mode=ro',uri=True)) as src,closing(sqlite3.connect(dest/name)) as target:
                src.backup(target)
                target.execute('PRAGMA journal_mode=DELETE')
                if target.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise ValueError('Backup integrity check failed.')
        (dest/'deployment.json').write_text(json.dumps(config,indent=2))
        shutil.copyfile(inside(root,config['settings']),dest/'settings.json')
        if (root/'VERSION.txt').is_file():shutil.copyfile(root/'VERSION.txt',dest/'VERSION.txt')
        # Preserve frozen policies without copying large training logs or model weights.
        for source in (root/'models').glob('**/policy.json'):
            if source.is_symlink() or not source.resolve().is_relative_to(root.resolve()) or source.stat().st_size>20000000:continue
            relative=hashlib.sha256(str(source.relative_to(root)).encode()).hexdigest()[:16]+'.json'
            manifest['policy_sources']['policies/'+relative]=str(source.relative_to(root))
            folder=dest/'policies';folder.mkdir(exist_ok=True);shutil.copyfile(source,folder/relative)
        for file in sorted(dest.rglob('*')):
            if file.is_file():manifest['files'].append({'path':str(file.relative_to(dest)).replace('\\','/'),'bytes':file.stat().st_size,'sha256':hashlib.sha256(file.read_bytes()).hexdigest()})
        (dest/'manifest.json').write_text(json.dumps(manifest,indent=2));return manifest
    except Exception:
        shutil.rmtree(dest);raise

def allowed(name):return name in ('account.sqlite','board.sqlite','alerts.sqlite','deployment.json','settings.json','VERSION.txt') or bool(re.fullmatch(r'policies/[0-9a-f]{16}\.json',name))

def verify(root,identity):
    if not isinstance(identity,str) or not re.fullmatch(r'\d{8}T\d{6}Z-[0-9a-f]{8}',identity):raise ValueError('Choose an existing backup ID.')
    source=Path(root)/'runtime/backups'/identity
    if source.is_symlink():raise ValueError('Symlink backups are not accepted.')
    manifest=json.loads((source/'manifest.json').read_text())
    if manifest.get('id')!=identity or not isinstance(manifest.get('files'),list) or len(manifest['files'])>1000:raise ValueError('Invalid backup manifest.')
    names=set()
    for entry in manifest['files']:
        name=entry.get('path')
        if not isinstance(name,str) or not allowed(name) or name in names:raise ValueError('Invalid backup filename.')
        names.add(name);file=source/name
        if file.is_symlink() or not file.resolve().is_relative_to(source.resolve()) or file.stat().st_size!=entry['bytes'] or hashlib.sha256(file.read_bytes()).hexdigest()!=entry['sha256']:raise ValueError('Backup checksum mismatch.')
        if name.endswith('.sqlite'):
            with closing(sqlite3.connect(file.resolve().as_uri()+'?mode=ro',uri=True)) as db:
                if db.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise ValueError('Backup database failed verification.')
    return source,manifest

def stage_restore(root,identity):
    source,manifest=verify(root,identity)
    dest=Path(root)/'runtime/restores'/(identity+'-'+secrets.token_hex(4));dest.mkdir(parents=True)
    for entry in manifest['files']:
        file=dest/entry['path'];file.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source/entry['path'],file)
    if (dest/'account.sqlite').is_file():Account(dest/'account.sqlite').trip()
    (dest/'RESTORE.txt').write_text('Verified restore staging only. Active files have NOT been overwritten. Stop the manager and all account services before manually switching database paths to these recovered files. Retain the safety pause and confirm account identity, balances and journal before resuming. Re-enter credentials from your separate secure copy.\n')
    return {'backup_id':identity,'staged_path':str(dest.relative_to(Path(root))),'active_files_replaced':False}

def listing(root):
    result=[]
    for path in sorted((Path(root)/'runtime/backups').glob('*/manifest.json'),reverse=True)[:50]:
        try:
            manifest=json.loads(path.read_text());result.append({'id':manifest['id'],'created':manifest['created'],'files':len(manifest['files'])})
        except Exception:continue
    return result
