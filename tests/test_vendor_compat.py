"""Guard: the vendored interpreter must stay importable on our minimum Python.

The runtime target (the docker-aprsd image) is Python 3.11, so no vendored or
plugin source may use 3.12+ syntax (e.g. PEP 695 ``class Foo[T]`` generics).
This compiles every source file so such a regression fails a test rather than
only surfacing at deploy time.
"""

import pathlib

import pytest

PACKAGE_ROOT = pathlib.Path(__file__).resolve().parent.parent / "aprsd_lurkinghorror_plugin"


@pytest.mark.parametrize(
    "py_file",
    sorted(PACKAGE_ROOT.rglob("*.py")),
    ids=lambda p: str(p.relative_to(PACKAGE_ROOT)),
)
def test_source_compiles(py_file):
    import py_compile

    # doraise=True turns a syntax error into an exception (test failure).
    py_compile.compile(str(py_file), doraise=True)
