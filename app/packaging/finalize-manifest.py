#!/usr/bin/env python3
"""Builder hook: seal the actual packaged resources, not just the source stage."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / 'python'))
from manifest import inventory, verify

resources = Path(sys.argv[1])
manifest_path = resources / 'bundle-manifest.json'
manifest = json.loads(manifest_path.read_text())
manifest['files'] = inventory(resources, prefix='', exclude=('bundle-manifest.json',))
manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + '\n')
print(json.dumps(verify(resources)))
