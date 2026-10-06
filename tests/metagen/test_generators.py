"""The shared generators reproduce a consumer's committed output, byte for byte.

``project/`` is a small, synthetic consumer: a model under ``metaobjects/``, the config that
names ``axi_toolkit.metagen`` generators, a committed capture, and the files a regeneration
wrote, with the manifest that tells a hand edit from generated output. Running the toolchain
over a copy of its sources must give back exactly what is committed.

There are two, because one model has one capture and the two say opposite things about it.
``project/`` says nothing the generators did not read before a model could choose: XML
attributes, a capture whose answers are under ``elements``, columns read from the row's own
object. Its committed output is the proof that a model which chooses nothing is generated as
it always was. ``json_project/`` chooses everything: JSON objects, a capture section of
another name that records what a list held, a column read from another object and one that
is a map key.

This needs the ``metagen`` extra, which needs Python 3.11, so on any other interpreter the
whole module skips. A skip must not read as a pass: ``scripts/ci-local.sh --only metagen``
runs it under an interpreter that has the toolchain and fails when it cannot.
"""

from __future__ import annotations

import importlib.util
import json
import os
import runpy
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("metaobjects", reason="the metagen extra (Python 3.11+) is not installed")

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
PROJECTS = ("project", "json_project")
#: The package has no ``__main__``; this is what its console script runs.
_ENTRY = "import sys; from metaobjects.cli import main; sys.exit(main())"
SOURCES = ("metaobjects.config.yaml", "metaobjects", "fixtures")
COMMITTED = (*SOURCES, "generated", ".metaobjects")

both = pytest.mark.parametrize("project", PROJECTS)


def _python(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src"), "PYTHONDONTWRITEBYTECODE": "1"}
    return subprocess.run(
        [sys.executable, *args],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def _run(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    return _python(cwd, "-c", _ENTRY, *args)


def _copy(into: Path, project: str, *names: str) -> Path:
    for name in names:
        source = HERE / project / name
        if source.is_dir():
            shutil.copytree(source, into / name)
        else:
            shutil.copy2(source, into / name)
    return into


def _tree(base: Path) -> dict:
    return {
        str(path.relative_to(base)): path.read_bytes()
        for path in sorted(base.rglob("*"))
        if path.is_file() and "__pycache__" not in path.parts
    }


def _edit(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    assert old in text, f"{old!r} is not in {path.name}"
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def _refusal(call, **given) -> str:
    with pytest.raises(KeyError) as refused:
        call(**given)
    return str(refused.value)


@both
def test_regenerating_from_the_sources_reproduces_the_committed_files(tmp_path, project):
    _copy(tmp_path, project, *SOURCES)
    result = _run(tmp_path, "gen")
    assert result.returncode == 0, result.stdout + result.stderr
    assert _tree(tmp_path / "generated") == _tree(HERE / project / "generated")


@both
def test_the_committed_files_verify_clean(tmp_path, project):
    _copy(tmp_path, project, *COMMITTED)
    result = _run(tmp_path, "verify", "--codegen")
    assert result.returncode == 0, result.stdout + result.stderr


@both
def test_a_hand_edit_to_a_generated_file_fails_verification(tmp_path, project):
    _copy(tmp_path, project, *COMMITTED)
    target = tmp_path / "generated" / "package" / "rows.py"
    target.write_text(target.read_text(encoding="utf-8") + "\n# edited\n", encoding="utf-8")
    assert _run(tmp_path, "verify", "--codegen").returncode != 0


@both
def test_no_project_name_is_stored_in_what_is_emitted(project):
    """Everything the output says about the model came from the model."""
    emitted = "\n".join(
        text.decode("utf-8") for text in _tree(HERE / project / "generated").values()
    ).lower()
    for name in ("plex", "hass", "home assistant"):
        assert name not in emitted


@both
def test_the_generated_capture_check_passes_on_the_committed_capture(tmp_path, project):
    """What is emitted is run, not only compared: the check reads the capture it names."""
    _copy(tmp_path, project, *COMMITTED)
    result = _python(tmp_path, "-m", "pytest", "-q", "-p", "no:cacheprovider", "generated/tests")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "passed" in result.stdout and "skipped" not in result.stdout


def test_a_model_that_names_no_section_reads_the_one_there_always_was():
    contract = (HERE / "project" / "generated" / "tests" / "capture_contract.py").read_text(
        encoding="utf-8"
    )
    assert '["elements"]' in contract
    assert "endswith" not in contract and '"also"' not in contract


def test_what_a_list_held_is_not_reported_as_a_name_the_server_sent(tmp_path):
    _copy(tmp_path, "json_project", *COMMITTED)
    assert '"labels[]"' in (tmp_path / "fixtures" / "capture.json").read_text(encoding="utf-8")
    result = _python(tmp_path, "generated/tests/capture_contract.py")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "[]" not in result.stdout
    assert "not declared: firmware\n" in result.stdout


@pytest.mark.parametrize(
    ("answer", "name", "failure"),
    [
        ("room.list", "name", "device row, example::hub::Room from room.list: ['name']"),
        ("hub.status", "devices", "device row, example::hub::Hub from hub.status: ['devices']"),
        ("device.list", "room_id", "device row, from device.list: ['room_id']"),
    ],
)
def test_a_name_a_row_reads_must_be_in_every_answer_of_the_object_it_is_read_from(
    tmp_path, answer, name, failure
):
    """A column read from another object is held to that object's captures, and a map key
    to the captures of the object that holds the map."""
    _copy(tmp_path, "json_project", *COMMITTED)
    capture = tmp_path / "fixtures" / "capture.json"
    recorded = json.loads(capture.read_text(encoding="utf-8"))
    recorded["objects"][answer].remove(name)
    capture.write_text(json.dumps(recorded), encoding="utf-8")
    result = _python(tmp_path, "generated/tests/capture_contract.py")
    assert result.returncode == 1, result.stdout + result.stderr
    assert f"FAIL {failure} is in no captured answer" in result.stdout


def test_a_name_read_of_another_object_is_excused_by_that_objects_own_reason():
    contract = runpy.run_path(
        str(HERE / "json_project" / "generated" / "tests" / "capture_contract.py")
    )
    assert "floor" in contract["ROWS"]["device"]["also"]["example::hub::Room"]
    assert "floor" in contract["UNOBSERVED"]["room"]
    assert "floor" not in contract["answers"]()["room.list"]
    assert contract["never_read"](contract["answers"]()) == {}


@pytest.mark.parametrize(
    ("project", "builder", "member", "whole"),
    [("project", "lamp", "an attribute", "element"), ("json_project", "room", "a key", "object")],
)
def test_a_builder_refuses_in_the_words_of_its_wire_format(project, builder, member, whole):
    elements = runpy.run_path(str(HERE / project / "generated" / "tests" / "elements.py"))
    build, kind = elements[builder], elements["ELEMENT"][builder]
    assert f"['nope'] is not {member} the model declares" in _refusal(build, nope="x")
    assert f"a real {kind} {whole} always carries" in _refusal(build)


_ROWS, _MODEL = "meta.rows.yaml", "meta.example.yaml"
_ALSO = 'also: { "example::hub::Room": [floor] }'
_KEY_OF = 'key_of: "example::hub::Hub.devices"'


def test_a_model_of_both_wire_formats_words_each_builder_for_its_own(tmp_path):
    _copy(tmp_path, "json_project", *SOURCES)
    _edit(
        tmp_path / "metaobjects" / _MODEL,
        "element: Hub, format: json",
        "element: Hub, format: xml-attributes",
    )
    result = _run(tmp_path, "gen")
    assert result.returncode == 0, result.stdout + result.stderr
    elements = runpy.run_path(str(tmp_path / "generated" / "tests" / "elements.py"))
    assert "a real Hub element always carries ['name']" in _refusal(elements["hub"])
    assert "a real Room object always carries" in _refusal(elements["room"])
    assert elements["hub"](name="example") == {"name": "example"}


def test_an_object_that_names_no_format_is_generated_as_the_first(tmp_path):
    """The default the docstring promises: dropping the name regenerates the same bytes."""
    _copy(tmp_path, "project", *SOURCES)
    _edit(tmp_path / "metaobjects" / _MODEL, ", format: xml-attributes", "")
    result = _run(tmp_path, "gen")
    assert result.returncode == 0, result.stdout + result.stderr
    assert _tree(tmp_path / "generated") == _tree(HERE / "project" / "generated")


def test_a_model_that_names_no_capture_is_refused_by_the_capture_check_alone(tmp_path):
    """The other two generators need no capture, so they cannot refuse a model for lacking
    one, and have written by the time the third does."""
    _copy(tmp_path, "project", *SOURCES)
    _edit(
        tmp_path / "metaobjects" / _MODEL,
        "    - attr.properties: { name: capture, value: { file: fixtures/capture.json } }\n",
        "",
    )
    result = _run(tmp_path, "gen")
    assert result.returncode != 0
    assert "naming its `file`" in result.stdout + result.stderr
    assert not (tmp_path / "generated" / "tests" / "capture_contract.py").exists()


def test_a_column_may_be_a_key_of_a_map_its_own_object_declares(tmp_path):
    """An object nested under a map of its own kind: ``also`` refuses the row's own object,
    and ``key_of`` does not, so the map is held to the answers the row is built from."""
    _copy(tmp_path, "json_project", *SOURCES)
    _edit(
        tmp_path / "metaobjects" / _MODEL,
        "          - field.string: { name: labels, isArray: true }\n",
        "          - field.string: { name: labels, isArray: true }\n"
        '          - field.map: { name: parts, objectRef: "example::hub::Device" }\n',
    )
    _edit(tmp_path / "metaobjects" / _ROWS, _KEY_OF, 'key_of: "example::hub::Device.parts"')
    capture = tmp_path / "fixtures" / "capture.json"
    recorded = json.loads(capture.read_text(encoding="utf-8"))
    recorded["objects"]["device.detail"].append("parts")
    capture.write_text(json.dumps(recorded), encoding="utf-8")
    result = _run(tmp_path, "gen")
    assert result.returncode == 0, result.stdout + result.stderr
    rows = runpy.run_path(str(tmp_path / "generated" / "package" / "rows.py"))
    assert rows["KEY_OF"] == {"device": {"slot": "example::hub::Device.parts"}}
    assert rows["READS"]["device"]["slot"] == ()
    result = _python(tmp_path, "generated/tests/capture_contract.py")
    assert result.returncode == 1, result.stdout + result.stderr
    assert "FAIL device row, from device.list: ['parts'] is in no" in result.stdout


@pytest.mark.parametrize(
    ("project", "file", "edit", "message"),
    [
        ("project", _ROWS, ("reads: [name, colour]", "reads: [name, nowhere]"), "nowhere"),
        (
            "project",
            _ROWS,
            ('extends: "example::service::Lamp.id"', 'extends: "example::service::Lamp.nope"'),
            None,
        ),
        (
            "project",
            _ROWS,
            (
                '{ name: name, extends: "example::rows::LampRow.name" }',
                '{ name: name, extends: "example::service::Lamp.name" }',
            ),
            "no default projection",
        ),
        ("project", _MODEL, ("{ file: fixtures/", "{ path: fixtures/"), "naming its `file`"),
        ("project", _MODEL, ("element: Lamp,", "tag: Lamp,"), "the `wire` bag needs `element`"),
        ("project", _MODEL, ("format: xml-attributes", "format: json-object"), "`wire.format`"),
        ("json_project", _MODEL, ("section: objects", 'section: ""'), "`capture.section`"),
        ("json_project", _MODEL, ('list_suffix: "[]"', 'list_suffix: ""'), "`capture.list_suffix`"),
        ("json_project", _ROWS, (_ALSO, "also: [floor]"), "must map an object"),
        (
            "json_project",
            _ROWS,
            (_ALSO, 'also: { "example::hub::Nowhere": [floor] }'),
            "'example::hub::Nowhere', which declares no `wire`",
        ),
        (
            "json_project",
            _ROWS,
            (_ALSO, 'also: { "example::hub::Device": [name] }'),
            "the row's own object",
        ),
        (
            "json_project",
            _ROWS,
            (_ALSO, 'also: { "example::hub::Room": [nowhere] }'),
            "reads ['nowhere'], which example::hub::Room does not declare",
        ),
        ("json_project", _ROWS, (_ALSO, 'also: { "example::hub::Room": [] }'), "names nothing"),
        ("json_project", _ROWS, (_KEY_OF, "key_of: devices"), "as `Object.field`"),
        (
            "json_project",
            _ROWS,
            (_KEY_OF, 'key_of: "example::hub::Nowhere.devices"'),
            "'example::hub::Nowhere', which declares no `wire`",
        ),
        (
            "json_project",
            _ROWS,
            (_KEY_OF, 'key_of: "example::hub::Hub.name"'),
            "example::hub::Hub.name, which is not a map",
        ),
        ("json_project", _ROWS, (_KEY_OF, "reads: []"), "says nothing about where it is read"),
    ],
)
def test_a_model_that_does_not_hold_together_is_refused_before_anything_is_written(
    tmp_path, project, file, edit, message
):
    _copy(tmp_path, project, *SOURCES)
    _edit(tmp_path / "metaobjects" / file, *edit)
    result = _run(tmp_path, "gen")
    assert result.returncode != 0
    if message:
        assert message in result.stdout + result.stderr
    assert not (tmp_path / "generated").exists()


_CONFIG = "metaobjects.config.yaml"
_READERS = ', "axi_toolkit.metagen:readers"'


def _readers(base: Path):
    """The readers a regeneration wrote, imported as the package that ships them would."""
    name = f"regenerated_readers_{base.name}"
    spec = importlib.util.spec_from_file_location(
        name, base / "generated" / "package" / "readers.py"
    )
    module = importlib.util.module_from_spec(spec)
    # A dataclass looks its own module up by name while it is being made.
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@both
def test_a_consumer_that_names_no_reader_generator_is_generated_as_it_always_was(tmp_path, project):
    """Not one byte of any other file knows whether the readers were asked for."""
    _copy(tmp_path, project, *SOURCES)
    _edit(tmp_path / _CONFIG, _READERS, "")
    result = _run(tmp_path, "gen")
    assert result.returncode == 0, result.stdout + result.stderr
    committed = _tree(HERE / project / "generated")
    assert committed.pop("package/readers.py")
    assert _tree(tmp_path / "generated") == committed


def test_a_nested_object_named_by_its_short_name_is_the_same_reader(tmp_path):
    _copy(tmp_path, "json_project", *SOURCES)
    _edit(
        tmp_path / "metaobjects" / _MODEL,
        '{ name: reading, objectRef: "example::hub::Reading" }',
        "{ name: reading, objectRef: Reading }",
    )
    result = _run(tmp_path, "gen")
    assert result.returncode == 0, result.stdout + result.stderr
    assert _tree(tmp_path / "generated") == _tree(HERE / "json_project" / "generated")


def test_an_object_that_holds_its_own_kind_is_read_through_its_own_reader(tmp_path):
    _copy(tmp_path, "json_project", *SOURCES)
    _edit(
        tmp_path / "metaobjects" / _MODEL,
        "          - field.string: { name: labels, isArray: true }\n",
        "          - field.string: { name: labels, isArray: true }\n"
        '          - field.map: { name: parts, objectRef: "example::hub::Device" }\n',
    )
    result = _run(tmp_path, "gen")
    assert result.returncode == 0, result.stdout + result.stderr
    device = _readers(tmp_path).Device.read(
        {"device_id": "d1", "parts": {"left": {"device_id": "d2", "parts": {}}}}
    )
    assert type(device.parts["left"]) is type(device)
    assert (device.parts["left"].device_id, device.parts["left"].parts) == ("d2", {})


def test_names_the_generated_module_uses_itself_are_spelled_out_of_its_way(tmp_path):
    """An object or a key may be called what the module calls something of its own. Each
    is run here, because the collision is one only running it finds: a key named ``field``
    left as it is makes the class that holds it impossible to define."""
    _copy(tmp_path, "json_project", *SOURCES)
    names = ("field", "raw", "read", "sent", "missing", "classmethod", "dataclass", "1st")
    fields = "".join(f'          - field.string: {{ name: "{name}" }}\n' for name in names)
    (tmp_path / "metaobjects" / "meta.more.yaml").write_text(
        "metadata:\n"
        "  package: example::more\n"
        "  children:\n"
        "    - object.value:\n"
        "        name: Mapping\n"
        "        children:\n"
        "          - attr.properties:\n"
        "              name: wire\n"
        "              value: { key: mapping, element: Mapping, format: json, capture: [room.list] }\n"
        + fields,
        encoding="utf-8",
    )
    result = _run(tmp_path, "gen")
    assert result.returncode == 0, result.stdout + result.stderr
    readers = _readers(tmp_path)
    answer = {name: name.upper() for name in names}
    read = readers.Mapping_.read(answer)
    assert read.raw is answer and read.missing() == ()
    assert (read.field_, read.raw_, read.read_, read.sent_) == ("FIELD", "RAW", "READ", "SENT")
    assert (read.missing_, read.classmethod_) == ("MISSING", "CLASSMETHOD")
    assert (read.dataclass, read._1st) == ("DATACLASS", "1ST")
    assert read.sent("raw") and not read.sent("raw_")
    # The other classes of the module still have what the names stood for.
    assert readers.Room.read({"room_id": "r1"}).missing() == ("name",)


_ANOTHER_ROOM = (
    "metadata:\n"
    "  package: example::annexe\n"
    "  children:\n"
    "    - object.value:\n"
    "        name: Room\n"
    "        children:\n"
    "          - attr.properties:\n"
    "              name: wire\n"
    "              value: { key: annexe_room, element: Room, format: json, capture: [room.list] }\n"
    "          - field.string: { name: name }\n"
)


@pytest.mark.parametrize(
    ("edit", "added", "message"),
    [
        (
            (
                "          - attr.properties:\n"
                "              name: wire\n"
                "              value: { key: reading, element: Reading, format: json, capture: [device.reading] }\n",
                "",
            ),
            None,
            "example::hub::Device.reading: `objectRef` names 'example::hub::Reading', "
            "which declares no `wire`",
        ),
        (
            None,
            _ANOTHER_ROOM,
            "example::annexe::Room and example::hub::Room would both be read by a class named Room",
        ),
        (
            (
                '          - field.string: { name: "time-zone" }\n',
                '          - field.string: { name: "time-zone" }\n'
                "          - field.string: { name: time_zone }\n",
            ),
            None,
            "example::hub::Hub: 'time-zone' and 'time_zone' would both be read into an "
            "attribute named time_zone",
        ),
    ],
)
def test_a_model_no_class_can_be_written_for_is_refused_by_the_reader_generator_alone(
    tmp_path, edit, added, message
):
    """The other generators write no class, so a consumer that names no reader generator
    is not refused for a reason only a reader has."""
    _copy(tmp_path, "json_project", *SOURCES)
    if edit:
        _edit(tmp_path / "metaobjects" / _MODEL, *edit)
    if added:
        (tmp_path / "metaobjects" / "meta.annexe.yaml").write_text(added, encoding="utf-8")
    result = _run(tmp_path, "gen")
    assert result.returncode != 0
    assert message in result.stdout + result.stderr
    assert not (tmp_path / "generated" / "package" / "readers.py").exists()
    _edit(tmp_path / _CONFIG, _READERS, "")
    result = _run(tmp_path, "gen")
    assert result.returncode == 0, result.stdout + result.stderr
