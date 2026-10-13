"""Native checks for the macOS feasibility spike (phase 1); run them under the staged or signed
interpreter.

  RUNTIME/python/bin/python3.12 native_checks.py --runtime RUNTIME --work DIR
      [--control PYTHON] [--report FILE]

Checks: every installed top-level module imports; a ctypes callback; one embedding with the bundled
search model, loaded the way the engine loads it; sqlite-vec in SQLite with a nearest-neighbour
query; a small compiled wheel installed after signing (the skills path); the first-use PDF reader
opening a generated PDF. With --control (an interpreter signed WITHOUT the library-validation
exception), the skills-path load must fail there, which shows the exception is what makes it work.
Exit status 0 only when every check passes.
"""

from __future__ import annotations

import argparse
import ctypes
import importlib
import importlib.metadata as metadata
import json
import math
import sqlite3
import struct
import subprocess
import sys
import tempfile
import traceback
from pathlib import Path

LOCK = json.loads((Path(__file__).resolve().parent / "runtime-lock.json").read_text())
SKIPPED_IMPORTS = {
    "Xlib": "Linux X11 client; engine dependency without a platform marker yet",
    "dbus_next": "Linux D-Bus client; engine dependency without a platform marker yet",
}


def imports() -> dict:
    failures, imported = {}, set()
    for distribution in metadata.distributions():
        top_level = distribution.read_text("top_level.txt")
        names = (
            top_level.split()
            if top_level
            else sorted(
                {
                    Path(str(file)).parts[0].removesuffix(".py")
                    for file in distribution.files or []
                    if str(file).endswith(".py")
                    and not Path(str(file)).parts[0].endswith((".dist-info", ".data"))
                }
            )
        )
        for name in names:
            if (
                not name.isidentifier()
                or name.startswith("_")
                or name in imported
                or name in SKIPPED_IMPORTS
            ):
                continue
            imported.add(name)
            try:
                importlib.import_module(name)
            except Exception as error:  # noqa: BLE001 - every failure is reported, not raised
                failures[name] = f"{type(error).__name__}: {error}"
    if failures:
        raise RuntimeError(json.dumps(failures, indent=1))
    return {"imported": len(imported), "skipped": SKIPPED_IMPORTS}


def ctypes_callback() -> dict:
    libc = ctypes.CDLL("/usr/lib/libSystem.B.dylib")
    compare = ctypes.CFUNCTYPE(
        ctypes.c_int, ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int)
    )
    values = (ctypes.c_int * 6)(5, 1, 4, 2, 6, 3)
    libc.qsort(values, len(values), ctypes.sizeof(ctypes.c_int), compare(lambda a, b: a[0] - b[0]))
    if list(values) != [1, 2, 3, 4, 5, 6]:
        raise AssertionError(list(values))
    return {"sorted": list(values)}


def embedding(runtime: Path) -> dict:
    from fastembed import TextEmbedding

    root = (runtime / "models" / "bge-small-en-v1.5").resolve(strict=True)
    model = TextEmbedding(
        "BAAI/bge-small-en-v1.5",
        specific_model_path=str(root),
        cache_dir=str(root),
        local_files_only=True,
        cuda=False,
    )
    vector = list(next(iter(model.embed(["Odin Desktop on macOS"]))))
    if len(vector) != 384 or not all(math.isfinite(value) for value in vector):
        raise AssertionError(f"unexpected embedding: {len(vector)} values")
    return {"dimensions": len(vector)}


def sqlite_vec() -> dict:
    import sqlite_vec as extension

    database = sqlite3.connect(":memory:")
    database.enable_load_extension(True)
    extension.load(database)
    database.enable_load_extension(False)
    database.execute("create virtual table items using vec0(embedding float[3])")
    rows = {1: (1.0, 0.0, 0.0), 2: (0.0, 1.0, 0.0), 3: (0.0, 0.0, 1.0)}
    for rowid, vector in rows.items():
        database.execute(
            "insert into items(rowid, embedding) values (?, ?)", (rowid, struct.pack("3f", *vector))
        )
    nearest = database.execute(
        "select rowid from items where embedding match ? order by distance limit 1",
        (struct.pack("3f", 0.1, 0.9, 0.0),),
    ).fetchone()[0]
    if nearest != 2:
        raise AssertionError(nearest)
    return {"version": database.execute("select vec_version()").fetchone()[0], "nearest": nearest}


def _install(pin: dict, target: Path) -> None:
    requirements = target.parent / f"{target.name}.txt"
    requirements.write_text(f"{pin['requirement']} --hash=sha256:{pin['sha256']}\n")
    subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "--no-deps",
            "--only-binary=:all:",
            "--require-hashes",
            "--target",
            str(target),
            "-r",
            str(requirements),
        ],
        check=True,
        capture_output=True,
        text=True,
    )


def _load(interpreter: str, target: Path, code: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [interpreter, "-c", f"import sys; sys.path.insert(0, {str(target)!r}); {code}"],
        capture_output=True,
        text=True,
        timeout=120,
    )


def skill_wheel(work: Path, control: str | None) -> dict:
    target = work / "skill-packages"
    _install(LOCK["native_checks"]["skill_wheel"], target)
    loaded = _load(sys.executable, target, "import ujson; print(ujson.dumps({'ok': 1}))")
    if loaded.returncode or loaded.stdout.strip() != '{"ok":1}':
        raise RuntimeError(loaded.stderr.strip() or loaded.stdout.strip())
    result = {"loaded": loaded.stdout.strip()}
    if control:
        refused = _load(control, target, "import ujson")
        result["control_refused"] = refused.returncode != 0
        result["control_error"] = refused.stderr.strip().splitlines()[-1:] if refused.stderr else []
        if not result["control_refused"]:
            raise AssertionError("the control interpreter loaded the package without the exception")
    return result


def pdf_first_use(work: Path) -> dict:
    target = work / "pdf-reader"
    _install(LOCK["native_checks"]["pdf_wheel"], target)
    code = (
        "import pymupdf; d = pymupdf.open(); p = d.new_page(); "
        "p.insert_text((72, 72), 'Odin Desktop macOS'); "
        "r = pymupdf.open('pdf', d.tobytes()); print(r[0].get_text().strip())"
    )
    loaded = _load(sys.executable, target, code)
    if loaded.returncode or loaded.stdout.strip() != "Odin Desktop macOS":
        raise RuntimeError(loaded.stderr.strip() or loaded.stdout.strip())
    return {"text": loaded.stdout.strip()}


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--work", type=Path)
    parser.add_argument("--control")
    parser.add_argument("--report", type=Path)
    options = parser.parse_args()
    work = options.work or Path(tempfile.mkdtemp(prefix="native-checks-"))
    work.mkdir(parents=True, exist_ok=True)
    checks = {
        "imports": imports,
        "ctypes_callback": ctypes_callback,
        "embedding": lambda: embedding(options.runtime),
        "sqlite_vec": sqlite_vec,
        "skill_wheel": lambda: skill_wheel(work, options.control),
        "pdf_first_use": lambda: pdf_first_use(work),
    }
    report = {"interpreter": sys.executable, "version": sys.version}
    for name, check in checks.items():
        try:
            report[name] = {"ok": True, "detail": check()}
        except Exception as error:  # noqa: BLE001 - every failure is reported
            report[name] = {
                "ok": False,
                "error": f"{type(error).__name__}: {error}",
                "trace": traceback.format_exc(limit=4),
            }
    text = json.dumps(report, indent=2, default=str)
    if options.report:
        options.report.write_text(text + "\n")
    print(text)
    return 0 if all(value.get("ok") for value in report.values() if isinstance(value, dict)) else 1


if __name__ == "__main__":
    sys.exit(main())
