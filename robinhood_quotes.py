"""Generate local credentials or fetch a read-only quote snapshot; never place orders."""
import argparse
import base64
import json
import os
from pathlib import Path
from scout.robinhood import quotes


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--generate-key', action='store_true')
    p.add_argument('--credentials', type=Path, default=Path('secrets/robinhood.json'))
    p.add_argument('--symbols', nargs='+', default=['BTC-USD','ETH-USD'])
    args=p.parse_args()
    try:
        if args.generate_key:
            from nacl.signing import SigningKey
            key=SigningKey.generate()
            args.credentials.parent.mkdir(parents=True,exist_ok=True)
            # Exclusive creation preserves existing keys. POSIX mode; Windows also needs local access controls.
            descriptor=os.open(args.credentials,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
            with os.fdopen(descriptor,'w',encoding='utf-8') as f:
                json.dump({'api_key':'REPLACE_LOCALLY','private_key_base64':base64.b64encode(bytes(key)).decode()},f,indent=2)
            print('Public key to register with Robinhood:',base64.b64encode(bytes(key.verify_key)).decode())
            print('Private key saved locally. Edit api_key in:',args.credentials)
        else:
            value=quotes(json.loads(args.credentials.read_text()),args.symbols)
            print(json.dumps(value,indent=2))
    except ImportError:
        p.exit(1,'Install optional signing dependency: python -m pip install -r requirements-robinhood.txt\n')
    except (ValueError,OSError,KeyError):
        p.exit(1,'Could not complete quote setup/request. Check local credentials, permissions, connection and PC clock. No orders sent.\n')

if __name__=='__main__':main()
