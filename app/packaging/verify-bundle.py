#!/usr/bin/env python3
import argparse
import importlib.util
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / 'python'))
from pdf import assert_no_pdf_payload

spec = importlib.util.spec_from_file_location(
    'bundle_sealing', Path(__file__).with_name('finalize-manifest.py'))
sealing = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sealing)

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('resources', type=Path)
    parser.add_argument('--release', action='store_true')
    options = parser.parse_args()
    root = options.resources
    result = sealing.verify_resources(root, release=options.release)
    result['pdf_policy'] = assert_no_pdf_payload(root)
    print(json.dumps(result, indent=2))
