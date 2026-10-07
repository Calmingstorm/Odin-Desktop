# D14 computer-use helper bundle

Build API: `stage_helpers(bundle_root: Path, cache_dir: Path) -> dict` in
`helpers.py`. Call after the noneditable engine wheel has been installed by the
Python stager. This never starts a backend, opens a graphical session, grants
input authority, activates a plugin, or writes outside the chosen bundle/cache.
It makes no network request and installs no host packages.

Verifier API: `prove_helpers(bundle_root: Path, metadata: dict | None = None)
-> dict`. With no metadata argument it reads `helpers/metadata.json`. This
verifies SHA256 inventory closure, imports actual package resources using the
bundled interpreter in isolated mode, imports the runtime's real
`wayland_probe._ASSETS` resolver and reads config data. It invokes each native
helper with **no arguments**, proving loader availability and its pre-input
usage refusal only. It additionally checks `ldd` resolves inventoried DSOs
inside the selected bundle and measures the helper/DSO GLIBC symbol floor.
`ldd` and `readelf` are build/qualification tools, not an engine first-run
download or Python dependency.

## Inventory

- Engine-consumed configs, Python probes and C source stay at
  `python/lib/python3.12/site-packages/src/computer/runtime/assets`. The stager
  refuses missing/drifted wheel assets rather than quietly creating a parallel
  resource directory that the engine never reads.
- `helpers/bin`: EI owned-input guardian, Hyprland owned-input guardian and
  Hyprland capture helper. Built from existing production C sources only.
- `helpers/lib`: hash-pinned Ubuntu 24.04 x86-64 libei, libxkbcommon,
  libwayland-client and transitive libffi. No system installation changes.
  Embedded `$ORIGIN/../lib` RPATH keeps the selected closure relocatable,
  including the libwayland transitive libffi lookup. glibc/loader remain target
  platform requirements, not quietly bundled workstation copies.
- `helpers/source`: explicit Hyprland C/XML/plugin/header and KWin source
  allowlist. No lab fixtures or runtime-qualified tuple registry is copied.
- `helpers/generated`: exact Wayland scanner C/header outputs with hashes and
  protocol notice references.
- `helpers/licenses`: preserved upstream MIT notice, extracted original XML
  protocol notices, and full installed package copyright notices for DSOs.
- `helpers/metadata.json`: every resource size/hash/source/license reference,
  build arguments, compiler/scanner/linker identities, dependency versions,
  offline loading evidence and honest deferred gates. Top-level bundle inventory
  is owned by the parent integration and also covers this metadata file.

## Build constraints and observed evidence

The current source's EI helper ignores several `write()` return values. Adding
`_FORTIFY_SOURCE=2` while retaining `-Werror` exposed those warnings and failed
the build. EI alone therefore uses `-U_FORTIFY_SOURCE`, matching its original
build's non-FORTIFY policy. Stack protection, RELRO/NOW and strict warnings
remain; the other two helpers retain FORTIFY. No ownership or receipt code was
modified to make packaging pass. This limitation is visible in build metadata.

On 2026-10-05 the actual staged bundle imported/read engine assets and loaded
all three native executables in a disconnected network and isolated PID/mount
namespace, without DISPLAY, WAYLAND_DISPLAY, DBUS_SESSION_BUS_ADDRESS or
XDG_RUNTIME_DIR. The same proof passed after copying the Python/helpers trees
to a new directory containing spaces, still disconnected from network access.
The helper/DSO GLIBC symbol floor measured **2.38** (not a promise that every
remaining product component has that floor). Exit codes were 64, 64 and 2
respectively. These are usage
refusals **before** connecting to a compositor or opening an input backend,
not proof of delivery, release, compositor admission, native focus or GUI work.
Focused behaviour tests exercise input-digest rejection, symlink refusal,
missing/drifted engine data, unsafe manifest paths, corrupt resource detection
and noninheritance of graphical/loader environment variables.

## Explicitly not qualified

Existing guardian trust checks require root-owned non-writable ancestors and
absolute configured native paths. They are unchanged. A user-owned AppImage
does not become trusted because it carries these files. Phase 2 native backend
admission, install-path binding and immutable-install trust policy must be
reviewed before invoking them for real work. There is no new environment
variable that bypasses admission or changes a helper path to a writable bundle.

Exact Hyprland/KWin compositor plugin ABI builds, new plugin qualification,
X11 sandbox system binaries, GI/AT-SPI closure, xkb data and isolated native
session qualification remain deferred. Hyprland/KWin plugin sources are shipped,
but no plugin binary or inherited upstream runtime approval is invented.
The Desktop product is MIT-licensed (`LICENSE`), like Odin; upstream notices
are still preserved. This helper subtask is therefore partial
D14 packaging evidence, not P4.1 or native computer-use acceptance.
