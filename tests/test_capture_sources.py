"""A capture that cannot read a source tool says which tool, and what it looked for.

The capture reads two other repositories, and they move. One renamed its package and
its command, and the read that followed failed on a bare ``RuntimeError`` in one place
and would have succeeded silently in another: recovery lines are parsed under the
tool's command name, so a capture run with the old name records every line as prose
and looks whole. These tests build small stand-in checkouts and state what each of
those failures has to say instead.

No message may carry a local path. They are read in pull request bodies as often as
in a terminal, and this repository is public.
"""

from __future__ import annotations

import sys
import textwrap

import pytest

from conformance import projections
from conformance.projections import SourceError

needs_toml = pytest.mark.skipif(
    sys.version_info < (3, 11),
    reason="the command check reads pyproject.toml with tomllib, like the rest of the capture",
)


@pytest.fixture
def checkout(tmp_path, monkeypatch):
    """A stand-in checkout builder for the Home Assistant tool's variable."""
    projections._verified_root.cache_clear()
    before = set(sys.modules)
    path_before = list(sys.path)

    def build(package="hass_axi", command="hass-axi", modules=None):
        root = tmp_path / "checkout"
        root.mkdir()
        if package:
            (root / "src" / package).mkdir(parents=True)
            (root / "src" / package / "__init__.py").write_text("")
            for name, text in (modules or {}).items():
                (root / "src" / package / f"{name}.py").write_text(textwrap.dedent(text))
        if command is not None:
            (root / "pyproject.toml").write_text(
                f'[project]\nname = "example"\n\n[project.scripts]\n{command} = "example:main"\n'
            )
        monkeypatch.setenv("AXI_TOOLKIT_SOURCE_HA", str(root))
        return root

    yield build
    projections._verified_root.cache_clear()
    sys.path[:] = path_before
    for name in set(sys.modules) - before:
        del sys.modules[name]


def refusal(call, *args) -> str:
    with pytest.raises(SourceError) as caught:
        call(*args)
    return str(caught.value)


def test_an_unset_variable_is_named(monkeypatch):
    monkeypatch.delenv("AXI_TOOLKIT_SOURCE_HA", raising=False)
    assert "AXI_TOOLKIT_SOURCE_HA is not set" in refusal(projections.source_root, "ha")


def test_a_renamed_package_is_named_beside_what_the_checkout_holds(checkout):
    root = checkout(package="some_other_axi")
    message = refusal(projections.source_root, "ha")
    assert "no `hass_axi` package" in message
    assert "src/ holds: some_other_axi" in message
    assert "`_PACKAGE`" in message
    assert str(root) not in message


def test_a_checkout_with_no_package_at_all_says_so(checkout):
    checkout(package=None)
    assert "src/ holds: no package" in refusal(projections.source_root, "ha")


@needs_toml
def test_a_renamed_command_is_named_beside_what_the_checkout_declares(checkout):
    """The failure that used to be silent: the package is there and the name is not."""
    root = checkout(command="some-other-axi")
    message = refusal(projections.source_root, "ha")
    assert "declares no `hass-axi` command" in message
    assert "declares: some-other-axi" in message
    assert "`_TOOL_NAME`" in message
    assert str(root) not in message


@needs_toml
def test_a_checkout_with_no_project_file_cannot_confirm_its_command(checkout):
    root = checkout(command=None)
    message = refusal(projections.source_root, "ha")
    assert "pyproject.toml cannot be read" in message
    assert str(root) not in message


@needs_toml
def test_a_checkout_with_the_package_and_the_command_is_accepted(checkout):
    root = checkout()
    assert projections.source_root("ha") == (root / "src" / "hass_axi").resolve()


@needs_toml
def test_a_module_the_capture_reads_and_the_tool_no_longer_has_is_named(checkout):
    root = checkout()
    message = refusal(projections.source_file, "ha", "output")
    assert "`hass_axi/output.py`" in message
    assert str(root) not in message


@needs_toml
def test_a_module_the_capture_imports_and_cannot_is_named(checkout):
    root = checkout()
    message = refusal(projections.source_module, "ha", "output")
    assert "`hass_axi.output`" in message
    assert "ModuleNotFoundError" in message
    assert str(root) not in message


# ------------------------------------------------- reading the redaction rules


@needs_toml
def test_the_rules_are_read_in_the_order_redact_applies_them(checkout):
    """Applied order, not the order the patterns happen to be defined in."""
    checkout(
        modules={
            "output": """
            import re

            _LAST = re.compile(r"last-[a-z]+")
            _FIRST = re.compile(r"(first=)[a-z]+")
            _UNUSED = re.compile(r"never applied")


            def redact(text):
                text = _FIRST.sub(lambda m: m.group(1) + "x", text)
                return _LAST.sub("x", text)
            """
        }
    )
    assert projections._redaction_rules("ha") == [r"(first=)[a-z]+", r"last-[a-z]+"]


@needs_toml
def test_nested_calls_are_read_in_the_order_they_run_not_the_order_they_are_written(checkout):
    """In ``B.sub(x, A.sub(y, text))`` it is ``A`` that runs first."""
    checkout(
        modules={
            "output": """
            import re

            _INNER = re.compile(r"inner-[a-z]+")
            _OUTER = re.compile(r"outer-[a-z]+")


            def redact(text):
                return _OUTER.sub("x", _INNER.sub("x", text))
            """
        }
    )
    assert projections._redaction_rules("ha") == [r"inner-[a-z]+", r"outer-[a-z]+"]


@needs_toml
def test_a_redact_that_applies_nothing_itself_is_a_refusal(checkout):
    """Delegated to a helper, the rules are somewhere this reader is not looking."""
    checkout(
        modules={
            "output": """
            def redact(text):
                return _clean(text)
            """
        }
    )
    assert "calls no `<PATTERN>.sub(...)`" in refusal(projections._redaction_rules, "ha")


@needs_toml
def test_a_rule_the_capture_cannot_read_is_a_refusal_not_a_shorter_list(checkout):
    """A pattern built some other way would be applied by the tool and never recorded."""
    checkout(
        modules={
            "output": """
            import re

            _READ = re.compile(r"read-[a-z]+")
            _BUILT = re.compile("built-" + "[a-z]+")


            def redact(text):
                return _BUILT.sub("x", _READ.sub("x", text))
            """
        }
    )
    message = refusal(projections._redaction_rules, "ha")
    assert "applies _BUILT" in message
    assert "recorded short" in message


@needs_toml
def test_a_module_with_no_redact_function_is_a_refusal(checkout):
    checkout(modules={"output": "import re\n"})
    assert "defines no `redact` function" in refusal(projections._redaction_rules, "ha")
