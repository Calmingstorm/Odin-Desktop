#!/usr/bin/env python3
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / 'python'))
from manifest import verify
from pdf import assert_no_pdf_payload

root = Path(sys.argv[1])
result = verify(root)
result['pdf_policy'] = assert_no_pdf_payload(root)
print(json.dumps(result, indent=2))
