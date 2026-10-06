"""Frozen step 6A computer corpus, with no native desktop effects."""

import json

from scripts.maintenance.fixture_corpus import digest
from tests.desktop_adapters.step8_6a_computer import PROOFS, RECORD, adapt, load

load(globals())


def test_step8_6a_computer_whole_tree_corpus_and_reverse_replay():
    record = json.loads(RECORD.read_text())
    for row in record['suites']:
        adapt(row['path'].rsplit('/', 1)[1][:-3])
        proof = PROOFS[row['path']]
        assert proof['whole_tree_reverse_replay']
        assert row['proof_sha256'] == digest(json.dumps(proof, sort_keys=True).encode())
        assert row['source_sha256'] == proof['source_sha256']
    for key, proof in PROOFS.items():
        if proof['helper_only']:
            assert record['helper_proofs'][key] == digest(
                json.dumps(proof, sort_keys=True).encode()
            )
