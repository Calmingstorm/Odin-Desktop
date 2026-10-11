"""Cross-host Windows archive refusals and no-write preflight evidence."""
import importlib.util
import io
from pathlib import Path
import stat
import struct
import tarfile
import warnings
import zipfile
import pytest

MODULE = Path(__file__).resolve().parents[1] / "python/windows_archive.py"
spec = importlib.util.spec_from_file_location("windows_archive_tested", MODULE)
archive = importlib.util.module_from_spec(spec)
spec.loader.exec_module(archive)


def make_archive(tmp_path, kind, entries):
    path = tmp_path / ("fixture.zip" if kind == "zip" else "fixture.tar.gz")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        if kind == "zip":
            with zipfile.ZipFile(path, "w") as output:
                for name in entries:
                    output.writestr(name, b"payload")
        else:
            with tarfile.open(path, "w:gz") as output:
                for name in entries:
                    info = tarfile.TarInfo(name)
                    info.size = 7
                    output.addfile(info, io.BytesIO(b"payload"))
    return path


@pytest.mark.parametrize("kind", ["zip", "tar"])
@pytest.mark.parametrize("bad", [
    "C:/root/file", "C:relative", "\\\\server\\share\\file", "/absolute", "\\rooted",
    "root/../escape", "root/./file", "root//file", "root\\..\\file", "root/file:stream",
    "root/NUL.txt", "root/con", "root/COM1.dll", "root/lpt9", "root/COM¹.txt",
    "root/CONIN$.txt", "root/NUL .txt", "root/file.", "root/dir /file", "root/file ",
    "root/file?", "root/file\x01", "root/file<", "root/file|", "root/file*",
])
def test_unsafe_member_refuses_before_any_write(tmp_path, kind, bad):
    source = make_archive(tmp_path, kind, ["root/good", bad])
    destination = tmp_path / "stage"
    with pytest.raises(archive.ArchiveSafetyError) as caught:
        archive.extract_archive(source, destination, package="test-package")
    assert not destination.exists()
    error = caught.value
    assert isinstance(error, ValueError)
    assert error.package == "test-package" and error.path == bad
    assert error.as_dict() == {"code": error.code, "package": "test-package", "path": bad,
                               "message": str(error)}


@pytest.mark.parametrize("kind", ["zip", "tar"])
@pytest.mark.parametrize("names,code", [
    (["root/file", "root/file"], "duplicate_destination"),
    (["root/file", "root/FILE"], "case_collision"),
    (["root/a/file", "root/A/other"], "case_collision"),
    (["root/straße", "root/STRASSE"], "case_collision"),
    (["root/a\\file", "root/a/file"], "duplicate_destination"),
    (["root/a", "root/a/file"], "destination_conflict"),
    (["root/a/file", "root/a"], "destination_conflict"),
])
def test_duplicate_alias_and_directory_conflicts(tmp_path, kind, names, code):
    source = make_archive(tmp_path, kind, names)
    with pytest.raises(archive.ArchiveSafetyError) as caught:
        archive.extract_archive(source, tmp_path / "stage")
    assert caught.value.code == code
    assert not (tmp_path / "stage").exists()


@pytest.mark.parametrize("kind", ["zip", "tar"])
def test_plain_archive_and_expected_root(tmp_path, kind):
    source = make_archive(tmp_path, kind, ["python/bin/python.exe", "python/lib/data.txt"])
    assert archive.preflight_archive(source, expected_root="python") == (
        "python/bin/python.exe", "python/lib/data.txt")
    destination = tmp_path / "stage"
    assert archive.extract_archive(source, destination, expected_root="python") == (
        "python/bin/python.exe", "python/lib/data.txt")
    assert (destination / "python/bin/python.exe").read_bytes() == b"payload"
    with pytest.raises(archive.ArchiveSafetyError, match="outside expected root"):
        archive.extract_archive(source, tmp_path / "wrong-stage", expected_root="other")
    assert not (tmp_path / "wrong-stage").exists()


@pytest.mark.parametrize("typecode", [tarfile.SYMTYPE, tarfile.LNKTYPE, tarfile.CHRTYPE,
                                       tarfile.BLKTYPE, tarfile.FIFOTYPE, tarfile.GNUTYPE_SPARSE])
def test_tar_links_and_specials(tmp_path, typecode):
    source = tmp_path / "fixture.tar.gz"
    with tarfile.open(source, "w:gz") as output:
        output.addfile(tarfile.TarInfo("root/good"))
        info = tarfile.TarInfo("root/bad")
        info.type = typecode
        info.linkname = "root/good" if typecode in (tarfile.SYMTYPE, tarfile.LNKTYPE) else ""
        output.addfile(info)
    with pytest.raises(archive.ArchiveSafetyError) as caught:
        archive.extract_archive(source, tmp_path / "stage")
    assert caught.value.code in {"link_or_special", "archive_format"}
    assert not (tmp_path / "stage").exists()


@pytest.mark.parametrize("mode", [stat.S_IFLNK, stat.S_IFIFO, stat.S_IFCHR, stat.S_IFBLK, stat.S_IFSOCK])
def test_zip_unix_links_and_specials(tmp_path, mode):
    source = tmp_path / "fixture.zip"
    with zipfile.ZipFile(source, "w") as output:
        info = zipfile.ZipInfo("root/bad")
        info.create_system = 3
        info.external_attr = (mode | 0o777) << 16
        output.writestr(info, b"target")
    with pytest.raises(archive.ArchiveSafetyError) as caught:
        archive.extract_archive(source, tmp_path / "stage")
    assert caught.value.code == "link_or_special"
    assert not (tmp_path / "stage").exists()


def test_zip_reparse_attribute(tmp_path):
    source = tmp_path / "fixture.zip"
    with zipfile.ZipFile(source, "w") as output:
        info = zipfile.ZipInfo("root/bad")
        info.create_system = 0
        info.external_attr = 0x400
        output.writestr(info, b"target")
    with pytest.raises(archive.ArchiveSafetyError) as caught:
        archive.preflight_archive(source)
    assert caught.value.code == "reparse_point"


def test_empty_stage_only_and_no_link_ancestors(tmp_path):
    source = make_archive(tmp_path, "zip", ["root/file"])
    stage = tmp_path / "stage"
    stage.mkdir()
    (stage / "existing").write_text("keep")
    with pytest.raises(archive.ArchiveSafetyError) as caught:
        archive.extract_archive(source, stage)
    assert caught.value.code == "destination_not_empty"
    assert list(stage.iterdir()) == [stage / "existing"]
    outside = tmp_path / "outside"
    outside.mkdir()
    link = tmp_path / "link"
    link.symlink_to(outside, target_is_directory=True)
    with pytest.raises(archive.ArchiveSafetyError) as caught:
        archive.extract_archive(source, link / "new")
    assert caught.value.code == "destination_reparse"
    assert list(outside.iterdir()) == []


def test_explicit_directories_and_empty_expected_root(tmp_path):
    source = tmp_path / "fixture.zip"
    with zipfile.ZipFile(source, "w") as output:
        output.writestr("python/", b"")
        output.writestr("python/data", b"yes")
    assert archive.extract_archive(source, tmp_path / "stage", expected_root="python") == ("python/data",)
    with zipfile.ZipFile(source, "w"):
        pass
    with pytest.raises(archive.ArchiveSafetyError) as caught:
        archive.preflight_archive(source, expected_root="python")
    assert caught.value.code == "unexpected_layout"


def test_backslash_normalization_and_invalid_format(tmp_path):
    assert archive.validate_windows_path("root\\sub\\file") == "root/sub/file"
    source = tmp_path / "not-an-archive"
    source.write_bytes(b"bad")
    with pytest.raises(archive.ArchiveSafetyError) as caught:
        archive.extract_archive(source, tmp_path / "stage")
    assert caught.value.code == "archive_format"
    assert not (tmp_path / "stage").exists()


@pytest.mark.parametrize("extra", [
    struct.pack("<HH", 0x000D, 16) + b"\0" * 12 + b"link",
    struct.pack("<HHIH IHH", 0x756E, 14, 0, stat.S_IFLNK | 0o777, 0, 0, 0),
])
def test_zip_extra_only_link_encoding(tmp_path, extra):
    source = tmp_path / "fixture.zip"
    with zipfile.ZipFile(source, "w") as output:
        info = zipfile.ZipInfo("looks-ordinary")
        info.extra = extra
        output.writestr(info, b"content")
    with pytest.raises(archive.ArchiveSafetyError) as caught:
        archive.extract_archive(source, tmp_path / "stage")
    assert caught.value.code == "link_or_special"
    assert not (tmp_path / "stage").exists()


def test_native_reparse_destination_metadata(tmp_path, monkeypatch):
    from types import SimpleNamespace
    source = make_archive(tmp_path, "zip", ["root/file"])
    stage = tmp_path / "stage"
    stage.mkdir()
    original = Path.lstat

    def lstat(path, *args, **kwargs):
        result = original(path, *args, **kwargs)
        if path == stage:
            return SimpleNamespace(st_mode=result.st_mode, st_file_attributes=0x400)
        return result

    monkeypatch.setattr(Path, "lstat", lstat)
    with pytest.raises(archive.ArchiveSafetyError) as caught:
        archive.extract_archive(source, stage)
    assert caught.value.code == "destination_reparse"
    assert list(stage.iterdir()) == []


def test_zip_local_header_drift_refused_before_good_file_write(tmp_path):
    source = make_archive(tmp_path, "zip", ["root/good", "root/bad"])
    data = source.read_bytes()
    # Corrupt only the local filename; the central directory remains valid.
    data = data.replace(b"root/bad", b"root/../", 1)
    source.write_bytes(data)
    with pytest.raises(archive.ArchiveSafetyError) as caught:
        archive.extract_archive(source, tmp_path / "stage")
    assert caught.value.code == "archive_format"
    assert not (tmp_path / "stage").exists()


def test_a_failed_write_is_reported_with_its_path_not_as_a_bad_archive(tmp_path, monkeypatch):
    import errno

    source = make_archive(tmp_path, "zip", ["root/file"])
    original = Path.open

    def refuse(path, mode="r", *args, **kwargs):
        if "x" in mode:
            raise OSError(errno.ENAMETOOLONG, "The filename or extension is too long")
        return original(path, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", refuse)
    with pytest.raises(archive.ArchiveSafetyError) as caught:
        archive.extract_archive(source, tmp_path / "stage")
    target = tmp_path / "stage" / "root" / "file"
    assert caught.value.code == "extract_io"
    assert caught.value.path == "root/file"
    assert f"{target} ({len(str(target))} characters)" in str(caught.value)
    assert "too long" in str(caught.value)


def test_content_addressed_tar_cache_without_archive_suffix(tmp_path):
    source = make_archive(tmp_path, "tar", ["python/file"])
    hashed = source.with_name("a" * 64)
    source.rename(hashed)
    stage = tmp_path / "stage"
    assert archive.extract_archive(hashed, stage, expected_root="python") == ("python/file",)
    assert (stage / "python/file").is_file()
