# Windows runtime assembly contract

`windows_runtime.stage_windows_runtime(repo, dest, cache_dir)` returns the
runtime provenance dictionary. `dest` is the bundle runtime root, not its Python
directory. Publication creates `dest/python` once; an existing Python stage is
refused, never refreshed or combined. All downloads, wheel spread, engine build,
DLL audit and native loads complete in private temporary trees before rename.
`stage_runtime(dest, cache_dir)` is the local-repository wrapper.

The executable is `python/python.exe`, and the site directory is
`python/Lib/site-packages`. Runtime invocations use `-I -B`. Build-time
setuptools is a locked, verified wheel isolated outside that tree. uv's exact
Windows archive is verified as provenance but is not used to resolve anything.
Production extras intentionally equal `[]`: development and first-use PDF
extras are excluded. `windows_closure.production_closure` evaluates the complete
reachable uv.lock graph against explicit Windows CPython 3.12.15 markers and
matches root requirements against pyproject.toml. Wheel METADATA dependency
sets and version constraints must match the selected graph.

Downloads enforce HTTPS, SHA-256 and exact size on every cache use. Windows
archive preflight validates the complete entry list before extraction. Wheel
validation checks filename identity, ABI/platform compatibility, WHEEL tags,
METADATA, licenses and every RECORD hash and size. Payload spread accepts only
site-package schemes. C headers are omitted and named in dependency records;
unknown scripts/data schemes fail. The exact selected artifact list is recorded.

Named foreign-platform omissions are recorded with hashes: pip's x86/ARM
distlib development launchers, Playwright's shell installation scripts, and
the engine's Linux-only computer-session asset subtree. The x64 pip launchers
remain. The Linux pinned-pip exception retains its exact wheel payload,
including inert launcher data, and has a separate strict output comparison.

DLL resolution uses the interpreter root, importer directory, `DLLs`, and the
NumPy wheel's explicit `numpy.libs` registration. It never discovers a DLL via
PATH or a development machine's installed redistributable. An allowlisted
Windows 11 inbox DLL is not evidence that a third-party runtime is installed.
Native isolated subprocesses load cryptography, ONNX Runtime, SQLite and
sqlite-vec and check that Python paths stay install-relative.

## Observed supplier blocker, 2026-10-11

All 72 selected Windows wheels were downloaded and their locked sizes and
SHA-256 hashes verified. 71 passed the strict METADATA/WHEEL/RECORD/license and
selected dependency checks. The pinned
`playwright-1.63.0-py3-none-win_amd64.whl` has `Tag: py3-none-any` in its WHEEL
metadata, inconsistent with its filename. The stager refuses this as
`wheel_tag_mismatch`, naming the package and artifact. This is not a passing
native stage and must not be hidden with a generic tag exception. A reviewed
supplier correction or explicit changed acceptance contract is needed.

Independent archive/layout probing spread all 72 payloads safely (not an
admitted stage); greenlet's sole `.data` payload is its header `greenlet.h`.
Actual PE imports also exposed ONNX Runtime's need for `msvcp140.dll` and
`msvcp140_1.dll`, which standalone CPython does not ship. The Microsoft app-local
CRT pin/helper is separate and carries its redistribution-license prerequisite.
With those two exactly pinned DLLs app-local, all 112 actual runtime PE images
passed the static recursive import audit (49 distinct explicit OS imports).
This was an offline Linux inspection of Windows bytes, not Windows execution.
All temporary spread/audit trees were deleted by their temporary-directory
contexts; the small content-addressed downloaded input cache was retained.
Linux pure tests do not substitute for the hosted Windows and Legion native
load/consumer acceptance evidence.
