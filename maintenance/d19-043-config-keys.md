# D19-043: tolerant unknown-key file admission

Pinned baseline: Odin v4.13.0, `cd7530906e9cfa10a0fa900247d7ce2a8bb33e25`.

Desktop now uses the same warning format as Odin's `load_config` /
`_warn_unknown_config_keys`, then drops unknown top-level keys from the runtime
mapping before migrations and validation. The warning's known-section list is
the actual Desktop schema, not Odin's removed transport schema. Both the startup
loader and the settings service's independent document-reading entry tolerate
these extras. `Config` itself still forbids extras: typed requests and settings
mutations do not silently adopt misspellings.

Known invalid values/types still refuse. All six sections in
`_KNOWN_REMOVED_TOP_LEVEL_CONFIG_KEYS` still refuse before migration writes and
remain excluded from the unknown-key warning. Their diagnostic now explicitly
says `removed top-level configuration fields`, rather than conflating them with
the restored unknown-key case. Removed schema fields are not restored.

## What Odin does on save

Odin v4.13.0's `src/config/persistence.py::submitted_leaves` omits submitted
unknown keys absent from the validated model. `_patch_config_paths` changes only
named leaves in the round-trip YAML document, preserving unsubmitted keys and
comments. Therefore an unknown key already on disk is preserved, not silently
deleted on an unrelated save. Once absent from disk, it is never regenerated
from the validated runtime model. Desktop uses this same leaf-scoped policy.

This fix does not introduce a whole-document rewrite to scrub operator YAML.
`tests/test_desktop_unknown_config_keys.py` covers exact warnings, actual temporary
profile admission/migrations, settings-file admission, invalid values/types,
retired sections, submitted-leaf filtering, preserved pre-existing unknown YAML,
actual settings persistence after operator removal, and rejection of an unknown
settings mutation without a write. All configuration and identity files are
temporary fixtures; no live profile, service, keyring, or desktop is used.

## Local validation

- 549 isolated configuration, settings, migration and D19 gate tests passed,
  with no failures/errors/skips.
- 11 focused new regression cases passed; the new unknown-key filtering helper
  has 100% statement coverage (4/4 statements).
- 38 hermetic Cinnamon/GNOME short-fixture tests passed, with no graphical input.
- `d19.py report` and `inventory.py report`: zero errors.
- `lint_gate.py`: no new findings; ownership-plan checker, touched-file Ruff
  and `git diff --check` passed.

No full qualification, VM run, deployment, service restart, or active-desktop
change. The raw JUnit/coverage receipts are stored outside Git under
`/mnt/storage/odin-desktop-evidence/d19-043-req42fb772d/`, with a SHA-256 manifest.
