"""Synthetic PE fixtures verify static audit without Windows or extra libraries."""
import importlib.util
from pathlib import Path
import struct
import pytest

MODULE = Path(__file__).resolve().parents[1] / "python/windows_dll.py"
spec = importlib.util.spec_from_file_location("windows_dll_tested", MODULE)
dll = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dll)


def pe_bytes(imports=(), delay=(), *, machine=0x8664, legacy_delay=False):
    data = bytearray(0x2200)
    data[:2] = b"MZ"
    struct.pack_into("<I", data, 0x3C, 0x80)
    data[0x80:0x84] = b"PE\0\0"
    opt_size = 240 if machine != 0x14C else 224
    struct.pack_into("<HHIIIHH", data, 0x84, machine, 1, 0, 0, 0, opt_size, 0x2022)
    opt = 0x98
    x64 = machine != 0x14C
    struct.pack_into("<H", data, opt, 0x20B if x64 else 0x10B)
    image_base = 0x10000000
    struct.pack_into("<Q" if x64 else "<I", data, opt + (24 if x64 else 28), image_base)
    struct.pack_into("<I", data, opt + 60, 0x200)
    struct.pack_into("<I", data, opt + (108 if x64 else 92), 16)
    dd = opt + (112 if x64 else 96)
    section = opt + opt_size
    data[section:section + 8] = b".rdata\0\0"
    struct.pack_into("<IIII", data, section + 8, 0x2000, 0x1000, 0x2000, 0x200)
    name_offset = 0x1000
    for names, index, descriptor_offset, width in [(imports, 1, 0x200, 20), (delay, 13, 0x600, 32)]:
        if not names:
            continue
        struct.pack_into("<II", data, dd + index * 8, 0x1000 + descriptor_offset - 0x200,
                         (len(names) + 1) * width)
        for number, name in enumerate(names):
            encoded = name.encode("ascii") + b"\0"
            data[name_offset:name_offset + len(encoded)] = encoded
            name_rva = 0x1000 + name_offset - 0x200
            descriptor = descriptor_offset + number * width
            if index == 1:
                struct.pack_into("<IIIII", data, descriptor, 0, 0, 0, name_rva, 0)
            else:
                struct.pack_into("<IIIIIIII", data, descriptor, 0 if legacy_delay else 1,
                                 name_rva + image_base if legacy_delay else name_rva, 0, 0, 0, 0, 0, 0)
            name_offset += len(encoded)
    return bytes(data)


def write_pe(root, name, **kwargs):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(pe_bytes(**kwargs))
    return path


@pytest.mark.parametrize("legacy", [False, True])
def test_normal_and_delay_import_parser(tmp_path, legacy):
    path = write_pe(tmp_path, "app.exe", imports=["KERNEL32.dll", "other.dll"],
                    delay=["late.dll"], legacy_delay=legacy)
    assert dll.read_pe_imports(path) == {"machine": "AMD64", "imports": ["kernel32.dll", "other.dll"],
                                        "delay_imports": ["late.dll"]}


def test_recursive_closure_case_insensitive_and_cycle(tmp_path):
    write_pe(tmp_path, "app.exe", imports=["FIRST.dll", "kernel32.dll"], delay=["LATE.dll"])
    write_pe(tmp_path, "First.DLL", imports=["second.dll"])
    write_pe(tmp_path, "second.dll", imports=["FIRST.dll", "api-ms-win-crt-runtime-l1-1-0.dll"])
    write_pe(tmp_path, "late.dll", imports=["user32.dll"])
    report = dll.audit_dll_dependencies(tmp_path, roots=["app.exe"], package="fixture")
    assert [entry["path"] for entry in report["files"]] == ["app.exe", "First.DLL", "late.dll", "second.dll"]
    assert report["os_imports"] == ["api-ms-win-crt-runtime-l1-1-0.dll", "kernel32.dll", "user32.dll"]
    assert report["machine"] == "AMD64"


@pytest.mark.parametrize("missing", ["vcruntime140.dll", "msvcp140.dll", "msvcp140_1.dll", "libcrypto.dll", "api-ms-win-invented-l1-1-0.dll"])
@pytest.mark.parametrize("delay", [False, True])
def test_non_os_and_unknown_api_contract_refused(tmp_path, missing, delay):
    write_pe(tmp_path, "app.exe", **{("delay" if delay else "imports"): [missing]})
    with pytest.raises(dll.DLLAuditError) as caught:
        dll.audit_dll_dependencies(tmp_path, package="fixture")
    error = caught.value
    assert isinstance(error, ValueError)
    assert error.code == "unresolved_import" and error.package == "fixture"
    assert error.path == str(tmp_path / "app.exe") and missing in str(error)
    assert error.as_dict() == {"code": error.code, "package": "fixture", "path": error.path, "message": str(error)}


def test_no_path_or_unrelated_nested_dll_resolution(tmp_path, monkeypatch):
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    write_pe(bundle, "app.exe", imports=["external.dll"])
    write_pe(tmp_path, "developer/external.dll")
    write_pe(bundle, "unrelated/external.dll")
    monkeypatch.setenv("PATH", str(tmp_path / "developer"))
    with pytest.raises(dll.DLLAuditError) as caught:
        dll.audit_dll_dependencies(bundle)
    assert caught.value.code == "unresolved_import"
    assert len(dll.audit_dll_dependencies(bundle, search_dirs=["unrelated"])["files"]) == 2


@pytest.mark.parametrize("machine", [0x14C, 0xAA64])
def test_wrong_machine_on_recursive_dependency(tmp_path, machine):
    write_pe(tmp_path, "app.exe", imports=["bad.dll"])
    write_pe(tmp_path, "bad.dll", machine=machine)
    with pytest.raises(dll.DLLAuditError) as caught:
        dll.audit_dll_dependencies(tmp_path, roots=["app.exe"])
    assert caught.value.code == "wrong_machine" and caught.value.path.endswith("bad.dll")


def test_audit_all_native_files_even_unreferenced(tmp_path):
    write_pe(tmp_path, "app.exe")
    write_pe(tmp_path, "unused.pyd", machine=0x14C)
    with pytest.raises(dll.DLLAuditError) as caught:
        dll.audit_dll_dependencies(tmp_path)
    assert caught.value.code == "wrong_machine"


@pytest.mark.parametrize("name", ["../escape.dll", "C:drive.dll", "\\\\host\\share.dll", "bad.dll ", "bad\x01.dll"])
def test_import_names_must_be_plain_basenames(tmp_path, name):
    path = write_pe(tmp_path, "app.exe", imports=[name])
    with pytest.raises(dll.DLLAuditError) as caught:
        dll.read_pe_imports(path)
    assert caught.value.code == "unsafe_import"


@pytest.mark.parametrize("data", [b"", b"not-PE", b"MZ", pe_bytes()[:0x180]])
def test_truncated_or_non_pe_refused(tmp_path, data):
    path = tmp_path / "bad.dll"
    path.write_bytes(data)
    with pytest.raises(dll.DLLAuditError) as caught:
        dll.read_pe_imports(path)
    assert caught.value.code == "malformed_pe"


@pytest.mark.parametrize("mutation", ["unbacked", "unterminated", "delay_attrs", "dir_count", "section_overlap"])
def test_malformed_rvas_and_tables_fail_closed(tmp_path, mutation):
    data = bytearray(pe_bytes(imports=["ok.dll"], delay=["late.dll"]))
    if mutation == "unbacked":
        struct.pack_into("<I", data, 0x200 + 12, 0xFF0000)
    elif mutation == "unterminated":
        struct.pack_into("<I", data, 0x98 + 112 + 8 + 4, 20)
    elif mutation == "delay_attrs":
        struct.pack_into("<I", data, 0x600, 2)
    elif mutation == "dir_count":
        struct.pack_into("<I", data, 0x98 + 108, 100)
    elif mutation == "section_overlap":
        struct.pack_into("<H", data, 0x84 + 2, 2)
        section = 0x98 + 240
        data[section + 40:section + 80] = data[section:section + 40]
    path = tmp_path / "bad.dll"
    path.write_bytes(data)
    with pytest.raises(dll.DLLAuditError) as caught:
        dll.read_pe_imports(path)
    assert caught.value.code == "malformed_pe"


def test_bundle_link_and_ambiguous_search_candidates(tmp_path):
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    write_pe(bundle, "app.exe", imports=["other.dll"])
    outside = write_pe(tmp_path, "outside.dll")
    link = bundle / "other.dll"
    link.symlink_to(outside)
    with pytest.raises(dll.DLLAuditError) as caught:
        dll.audit_dll_dependencies(bundle)
    assert caught.value.code == "bundle_reparse"
    link.unlink()
    write_pe(bundle, "other.dll")
    write_pe(bundle, "another/other.dll", imports=["kernel32.dll"])
    with pytest.raises(dll.DLLAuditError) as caught:
        dll.audit_dll_dependencies(bundle, search_dirs=["another"])
    assert caught.value.code == "ambiguous_import"
    with pytest.raises(dll.DLLAuditError) as caught:
        dll.audit_dll_dependencies(bundle, search_dirs=["../"])
    assert caught.value.code == "outside_bundle"


def test_casefold_bundle_collision(tmp_path):
    write_pe(tmp_path, "name.dll")
    write_pe(tmp_path, "NAME.dll")
    if len(list(tmp_path.iterdir())) < 2:
        pytest.skip("Fixture requires a case-sensitive host filesystem")
    with pytest.raises(dll.DLLAuditError) as caught:
        dll.audit_dll_dependencies(tmp_path)
    assert caught.value.code == "case_collision"


def test_invalid_target_architecture_is_structured(tmp_path):
    path = write_pe(tmp_path, "app.exe")
    for operation in (lambda: dll.read_pe_imports(path, expected_machine="unknown"),
                      lambda: dll.audit_dll_dependencies(tmp_path, expected_machine=0)):
        with pytest.raises(dll.DLLAuditError) as caught:
            operation()
        assert caught.value.code == "wrong_machine"


def test_chromium_control_panel_dll_and_media_baseline(tmp_path):
    path = write_pe(tmp_path, "browser.exe", imports=["DWrite.dll"],
                    delay=["bthprops.cpl", "MFPlat.dll", "api-ms-win-core-realtime-l1-1-1.dll"])
    result = dll.audit_dll_dependencies(tmp_path)
    assert dll.read_pe_imports(path)["delay_imports"][0] == "bthprops.cpl"
    assert set(result["os_imports"]) == {"dwrite.dll", "bthprops.cpl", "mfplat.dll",
                                        "api-ms-win-core-realtime-l1-1-1.dll"}


def test_cpython_msi_inbox_contract(tmp_path):
    write_pe(tmp_path, "_msi.pyd", imports=["msi.dll", "combase.dll"])
    assert dll.audit_dll_dependencies(tmp_path)["os_imports"] == ["combase.dll", "msi.dll"]


def test_empty_native_bundle_is_not_a_pass(tmp_path):
    (tmp_path / "data.txt").write_text("not native")
    with pytest.raises(dll.DLLAuditError) as caught:
        dll.audit_dll_dependencies(tmp_path)
    assert caught.value.code == "empty_native_bundle"


def test_incomplete_directory_enumeration_cannot_pass(tmp_path, monkeypatch):
    write_pe(tmp_path, "app.exe")

    def broken_walk(root, *, followlinks, onerror):
        onerror(PermissionError(13, "refused", str(root / "hidden")))
        return iter(())

    monkeypatch.setattr(dll.os, "walk", broken_walk)
    with pytest.raises(dll.DLLAuditError) as caught:
        dll.audit_dll_dependencies(tmp_path)
    assert caught.value.code == "bundle_io"
