#!/usr/bin/env python3
"""Export the V2 analysis contract without opening a database or fetching prices."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))


def export_schema():
    from fastapi import FastAPI
    from kurafolio.web_v2.analysis import install_routes
    from kurafolio.web_v2.api import ERROR_STATUSES
    from kurafolio.web_v2.schemas import Error

    def no_service(_request):
        raise RuntimeError('The schema export does not handle requests')

    app = FastAPI(title='Kurafolio V2 identity API', version='2')
    install_routes(app, no_service, {status: {'model': Error} for status in ERROR_STATUSES})
    return app.openapi()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(export_schema(), indent=2, sort_keys=True) + '\n',
                           encoding='utf-8')


if __name__ == '__main__':
    main()
