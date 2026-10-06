# CPython runtime lane

`runtime.py` uses build-time Python 3.12 stdlib only. Import it with importlib
and call `stage_runtime(runtime_root: Path, cache_root: Path) -> dict`.
For this candidate the roots are `/home/odin/desktop-p41-stage/runtime` and
`/home/odin/desktop-p41-cache`. Returned paths are relative to runtime_root.
No writes to the checkout except the owned implementation, lock and tests.

## Inputs and installed layout

- `app/packaging/runtime-lock.json`: hash-pinned python-build-standalone
  CPython 3.12.15, release 20261003, Linux x86-64 install_only archive.
- The initial 3.12.11/20250918 trial was rejected: `os.pidfd_open` is absent,
  causing real core shutdown to fail. 3.12.15 exports both `os.pidfd_open`
  and `signal.pidfd_send_signal`; staging opens and closes a real pidfd.
  This preserves the existing safety primitive, rather than adding a fallback.
- Hash-pinned uv 0.11.26 is build-only. Frozen uv export selects production
  dependencies, not the project/dev/pdf extras. There is no lock resolution/update.
- Bootstrap pip from the pinned interpreter downloads wheel-only requirements
  with `--require-hashes`. Every downloaded wheel hash is cross-checked against
  uv.lock. Local offline `pip install --target` installs the production wheels without
  dependency resolution or compilation. pip/ensurepip and build-path console
  scripts are removed from the finished runtime.
- Locked setuptools 84.0.0 builds the engine in a private temporary directory
  with SOURCE_DATE_EPOCH=1704067200. Source allowlist is tracked src files plus
  new `.py` modules (for parallel adapters before commit), excluding caches.
  Assets are carried by the project's package-data rules. The purelib engine
  wheel is extracted noneditable into `python/lib/python3.12/site-packages`.
- Runtime entry point is absolute `python/bin/python3` (relative symlink to
  python3.12), `-I -B -m src`. No checkout, PYTHONPATH or PATH lookup.

## Refresh and metadata

Re-running `stage_runtime` on an existing tree validates the runtime and uv.lock
inputs then rebuilds the engine. Changed runtime/dependency pins require a fresh
root. `refresh_engine(runtime_root, cache_root)` rebuilds engine-only and updates
`python/engine-source.json` and the engine field in `python/runtime-metadata.json`.
The integrator should use stage_runtime after rebasing to regenerate full lane
metadata, then rewrite the outer runtime-inputs-python.json from its return.

Metadata includes Python/uv provenance and download hashes, uv.lock and exported
requirements hashes, each dependency wheel URL/hash/version, SPDX expressions
and declared license classifiers/text, license-file hashes, engine source-file
hash inventory and wheel hash, and every ELF's imported GLIBC versions. Cache
artifacts are content-addressed and rehashed on every use. Tar input is fully
preflighted before writes; traversal, external links, hardlinks, special files,
duplicate entries and writes through symlink parents are rejected.

`python/licenses/` includes the upstream MIT notice from
maintenance/UPSTREAM-LICENSE and 21 separately hash-pinned standalone component
license/notice files at the release's source commit. This is an inventory, not
a legal compatibility opinion. The Desktop product has no license declaration;
metadata deliberately says NOASSERTION pending the owner's decision. PyMuPDF/MuPDF
is not distributed: its wheel, native libraries and license staging are excluded.
The optional PDF extra is downloaded into user data on first use using the
immutable `runtime/pdf.lock.json` pin; see `PDF.md`.

## Historical pre-review measured evidence

The lock/requirements hashes below describe the original bundled-PDF trial, not
the new first-use candidates. Their production closure is regenerated and must be
qualified independently after the PDF removal.

- Initial and replacement production stages both completed successfully.
- Replacement Python executable SHA256:
  `0f6e9c5804211e0bbff2d403f0e84d5dd5a30ea214f250cd1657bbba27a62498`.
- Replacement archive SHA256:
  `f937814031eab4698ca6d07ec606ede1825768f3f3e99af76d9db3900bee03c5`.
- uv.lock SHA256:
  `9e1c13678e301e199aafe2abc54ab2afe6791a14faf7800270c8f820a6fbdc44`.
- Exported requirements SHA256:
  `45bfdaefa770693596fb031cea883f69188b0dc93e0b8fc51f8f3a57ad72381c`.
- Static GLIBC import floor **2.28**, measured via readelf version-needs sections
  of every ELF in python. Maximum imports arise from ONNX Runtime, Playwright's
  Node binary and py_rust_stemmers. This is not oldest-distro execution proof.
- `tests/test_packaging_runtime.py`: 13 real behaviour cases, run with:
  `sudo -n unshare --mount --pid --fork --mount-proc --kill-child sudo -u odin env -u DBUS_SESSION_BUS_ADDRESS -u XDG_RUNTIME_DIR /home/odin/odin-dev/.venv/bin/python -m pytest -q tests/test_packaging_runtime.py`
- The qualification worker independently reached the packaged real core's
  handshake/status/events/ping and clean shutdown with replacement 3.12.15 in
  a private PID/network/filesystem sandbox, system Python masked and no checkout.
  Candidate package acceptance remains the integrator's gate, not this lane.

No hosted CI, commits, pushes, live-service or desktop actions performed.
