#!/usr/bin/env python3
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / 'python'))
from manifest import verify

print(json.dumps(verify(Path(sys.argv[1])), indent=2))
