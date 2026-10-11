"""The supervisor worker's argument parser never echoes arguments, on any Python 3.12.

`main()` parses with `exit_on_error=False`. On Python 3.12.3 a missing required argument still
reaches `QuietParser.error`. On 3.12.15, the bundled runtime's version, argparse raises
`ArgumentError` first and `main()` returns 2 without calling it. Either way nothing the worker
was given reaches its output.
"""
from __future__ import annotations

import pytest

from src.tools import local_supervisor_worker as w


def test_the_parser_error_never_echoes_its_message():
    with pytest.raises(ValueError) as raised:
        w.QuietParser(add_help=False).error("unrecognized arguments: --command private-value")
    assert str(raised.value) == "invalid worker arguments"


@pytest.mark.parametrize("argv", [[], ["--control-fd", "no", "--command", "private-value"]])
def test_bad_arguments_return_2_and_print_nothing(monkeypatch, capsys, argv):
    monkeypatch.setattr("sys.argv", ["worker", *argv])
    assert w.main() == 2
    printed = capsys.readouterr()
    assert printed.out == "" and printed.err == ""
