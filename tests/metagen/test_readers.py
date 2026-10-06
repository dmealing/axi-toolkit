"""The generated readers read: the committed ones are imported and given answers.

Nothing here needs the toolchain. A reader is standard-library Python that a consuming
package ships and runs on its own floor, so this module runs wherever the suite does, down
to Python 3.9, against the files ``test_generators`` proves a regeneration writes.

Every answer a test reads is shaped as the committed capture recorded it: ``_answer``
refuses one that carries a name the capture does not, or lacks one it does. So a reader is
shown what a real server sends, the names the model never declared among them, and a test
that wants a name absent says so by taking it out.
"""

from __future__ import annotations

import ast
import dataclasses
import importlib.util
import json
import runpy
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
PROJECTS = ("project", "json_project")
#: Where each project's capture keeps its answers, and how it marks what a list held.
SECTION = {"project": ("elements", None), "json_project": ("objects", "[]")}

#: The declared names Python cannot have as an attribute, and what each is spelled as.
SPELLED = {"class": "class_", "time-zone": "time_zone"}
#: Two names long enough that the line reading each is broken, one plain and one nested.
ADDRESS, LATEST = "address_the_hub_was_last_reached_at", "device_most_recently_heard_from"

both = pytest.mark.parametrize("project", PROJECTS)


def _path(project: str) -> Path:
    return HERE / project / "generated" / "package" / "readers.py"


def _load(project: str):
    """The committed module, imported as a consumer imports it: by name, from a file."""
    name = f"metagen_{project}_readers"
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(name, _path(project))
        module = importlib.util.module_from_spec(spec)
        # A dataclass looks its own module up by name while it is being made.
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return sys.modules[name]


def _elements(project: str) -> dict:
    return runpy.run_path(str(HERE / project / "generated" / "tests" / "elements.py"))


def _answer(project: str, answer: str, carried: dict) -> dict:
    """One answer, held to the names the capture recorded for it: all of them, no other."""
    section, list_suffix = SECTION[project]
    capture = json.loads((HERE / project / "fixtures" / "capture.json").read_text("utf-8"))
    recorded = {
        one for one in capture[section][answer] if not (list_suffix and one.endswith(list_suffix))
    }
    assert set(carried) == recorded, f"{answer} is not shaped as the capture recorded it"
    return carried


def _without(answer: dict, *names: str) -> dict:
    assert set(names) <= set(answer)
    return {name: value for name, value in answer.items() if name not in names}


def _room(**changed) -> dict:
    carried = {"room_id": "r1", "name": "Example Room", "icon": "sofa"}
    carried.update(changed)
    return _answer("json_project", "room.list", carried)


def _reading(**changed) -> dict:
    carried = {"value": 21.5, "unit": "C", "at": 1700000000, "quality": "good"}
    carried.update(changed)
    return _answer("json_project", "device.reading", carried)


def _device(device_id: str = "d1", **changed) -> dict:
    carried = {
        "device_id": device_id,
        "name": "Example Sensor",
        "room_id": "r1",
        "labels": ["upstairs", "example"],
        "class": "sensor",
        "online": True,
        "settings": {"interval": 30, "limits": {"low": [1, 2]}},
        "reading": _reading(),
        "history": [_reading(value=20.0), _reading(value=21.0)],
        "firmware": "1.2.3",
    }
    carried.update(changed)
    return _answer("json_project", "device.detail", carried)


def _hub(**changed) -> dict:
    carried = {
        "name": "Example Hub",
        "devices": {"slot-1": _device("d1"), "slot-2": _device("d2")},
        "counts": {"online": 2, "offline": 0},
        "time-zone": "Example/Zone",
        ADDRESS: "hub.example.com",
        LATEST: _device("d2"),
        "uptime": 12345,
    }
    carried.update(changed)
    return _answer("json_project", "hub.status", carried)


def _beacon(**changed) -> dict:
    """Attributes, so every one is text: that is all an element can carry."""
    carried = {
        "id": "b1",
        "strength": "-42",
        "ratio": "0.75",
        "secure": "1",
        "seen": "1700000000",
        "vendor": "Example",
        "channel": "6",
    }
    carried.update(changed)
    return _answer("json_project", "beacon.scan", carried)


def _lamp(**changed) -> dict:
    carried = {"id": "7", "name": "Example Lamp", "brightness": "80", "colour": "warm"}
    carried.update(changed)
    return _answer("project", "lamp.row", carried)


def test_a_json_answer_is_read_by_name_and_handed_over_as_it_was_parsed():
    readers = _load("json_project")
    room = readers.Room.read(_room())
    assert (room.room_id, room.name, room.floor) == ("r1", "Example Room", None)
    # A key is taken as it was parsed: nothing is made of a number that arrived as text.
    reading = readers.Reading.read(_reading(value="21.5", unit=3, at=None))
    assert (reading.value, reading.unit, reading.at) == ("21.5", 3, None)


def test_xml_attributes_are_read_as_what_the_model_declares_them_to_be():
    beacon = _load("json_project").Beacon.read(_beacon())
    assert (beacon.id, beacon.vendor) == ("b1", "Example")
    assert (beacon.strength, beacon.ratio, beacon.seen) == (-42, 0.75, 1700000000)
    assert beacon.secure is True
    assert type(beacon.strength) is int and type(beacon.ratio) is float
    lamp = _load("project").Lamp.read(_lamp())
    assert (lamp.id, lamp.name, lamp.brightness, lamp.colour) == ("7", "Example Lamp", 80, "warm")


@pytest.mark.parametrize(
    ("attribute", "text", "read"),
    [
        ("strength", "", None),
        ("strength", "strong", None),
        ("strength", "4.5", None),
        ("ratio", "", None),
        ("ratio", "half", None),
        ("ratio", "3", 3.0),
        ("secure", "0", False),
        ("secure", "false", False),
        ("secure", "True", True),
        ("secure", "", None),
        ("secure", "maybe", None),
        ("vendor", "", ""),
        ("id", "007", "007"),
    ],
)
def test_text_that_is_not_what_the_model_declares_is_read_as_none(attribute, text, read):
    """And is still what the server sent: the text itself is in ``raw``."""
    beacon = _load("json_project").Beacon.read(_beacon(**{attribute: text}))
    assert getattr(beacon, attribute) == read
    assert type(getattr(beacon, attribute)) is type(read)
    assert beacon.raw[attribute] == text and beacon.sent(attribute)


def test_a_nested_object_is_read_through_the_reader_of_the_object_it_is():
    readers = _load("json_project")
    answer = _device()
    device = readers.Device.read(answer)
    assert type(device.reading) is readers.Reading
    assert (device.reading.value, device.reading.unit) == (21.5, "C")
    assert device.reading.raw is answer["reading"]
    assert device.reading.raw["quality"] == "good"


def test_a_list_of_nested_objects_is_a_tuple_of_readers_and_a_plain_list_a_tuple():
    readers = _load("json_project")
    device = readers.Device.read(_device())
    assert type(device.history) is tuple
    assert [type(one) for one in device.history] == [readers.Reading, readers.Reading]
    assert [one.value for one in device.history] == [20.0, 21.0]
    assert device.labels == ("upstairs", "example")
    assert readers.Device.read(_device(history=[], labels=[])).history == ()
    assert readers.Device.read(_device(history=[], labels=[])).labels == ()


def test_a_map_of_nested_objects_is_a_dict_of_readers_under_the_servers_own_keys():
    readers = _load("json_project")
    answer = _hub()
    hub = readers.Hub.read(answer)
    assert list(hub.devices) == ["slot-1", "slot-2"]
    assert {type(one) for one in hub.devices.values()} == {readers.Device}
    assert hub.devices["slot-2"].device_id == "d2"
    # Three deep: a reading, in a device, in the hub's map.
    assert hub.devices["slot-1"].history[1].value == 21.0
    assert hub.devices["slot-1"].raw is answer["devices"]["slot-1"]
    # A map of plain values has no reader to go through, and is the server's own.
    assert hub.counts is answer["counts"]


def test_a_name_too_long_for_one_line_is_read_like_any_other():
    readers = _load("json_project")
    hub = readers.Hub.read(_hub())
    assert getattr(hub, ADDRESS) == "hub.example.com"
    assert type(getattr(hub, LATEST)) is readers.Device
    assert getattr(hub, LATEST).device_id == "d2"
    # Broken: the name stands on a line of its own, behind the comma that keeps it there.
    source = _path("json_project").read_text(encoding="utf-8").splitlines()
    assert f'"{ADDRESS}",' in [line.strip() for line in source]


def test_an_open_bag_is_handed_over_untouched():
    answer = _device()
    device = _load("json_project").Device.read(answer)
    assert device.settings is answer["settings"]
    assert device.settings["limits"]["low"] == [1, 2]


def test_what_the_model_does_not_declare_is_never_lost_and_never_an_attribute():
    readers = _load("json_project")
    answer = _device()
    device = readers.Device.read(answer)
    assert device.raw is answer
    assert device.raw["firmware"] == "1.2.3" and device.sent("firmware")
    assert not hasattr(device, "firmware")
    assert json.dumps(device.raw, sort_keys=True) == json.dumps(_device(), sort_keys=True)
    assert readers.Beacon.read(_beacon()).raw["channel"] == "6"


@pytest.mark.parametrize("name", ["name", "labels", "settings", "reading", "history"])
def test_a_key_sent_as_null_and_a_key_not_sent_both_read_as_none_and_are_told_apart(name):
    readers = _load("json_project")
    null = readers.Device.read(_device(**{name: None}))
    absent = readers.Device.read(_without(_device(), name))
    assert getattr(null, name) is None and getattr(absent, name) is None
    assert null.sent(name) is True
    assert absent.sent(name) is False


def test_an_attribute_not_sent_is_none_and_is_told_from_one_sent_empty():
    readers = _load("json_project")
    absent = readers.Beacon.read(_without(_beacon(), "ratio", "vendor"))
    empty = readers.Beacon.read(_beacon(ratio="", vendor=""))
    assert (absent.ratio, absent.vendor) == (None, None)
    assert (empty.ratio, empty.vendor) == (None, "")
    assert not absent.sent("ratio") and empty.sent("ratio")


def test_missing_names_each_required_key_an_answer_lacked_in_the_order_declared():
    readers = _load("json_project")
    assert readers.Device.read(_device()).missing() == ()
    assert readers.Reading.read(_reading()).missing() == ()
    assert readers.Reading.read(_without(_reading(), "at", "value")).missing() == ("value", "at")
    # Null is not a value: a key a real answer always carries, sent as null, is missing.
    assert readers.Device.read(_device(device_id=None)).missing() == ("device_id",)
    assert readers.Hub.read(_without(_hub(), "name")).missing() == ("name",)


def test_missing_names_a_required_attribute_whose_text_is_not_what_was_declared():
    readers = _load("json_project")
    assert readers.Beacon.read(_beacon()).missing() == ()
    unreadable = readers.Beacon.read(_beacon(strength="strong"))
    assert unreadable.missing() == ("strength",) and unreadable.sent("strength")
    assert readers.Beacon.read(_without(_beacon(), "id", "strength")).missing() == (
        "id",
        "strength",
    )
    assert _load("project").Lamp.read(_without(_lamp(), "name")).missing() == ("name",)


def test_what_is_there_and_is_not_an_object_is_left_out_and_is_still_in_raw():
    readers = _load("json_project")
    device = readers.Device.read(
        _device(reading="unavailable", history=[_reading(), None, "gap", 3])
    )
    assert device.reading is None and device.raw["reading"] == "unavailable"
    assert [one.value for one in device.history] == [21.5]
    assert device.raw["history"][1:] == [None, "gap", 3]
    assert (
        readers.Device.read(_device(history={"0": _reading()}, labels="upstairs")).history is None
    )
    assert readers.Device.read(_device(history={"0": _reading()}, labels="upstairs")).labels is None
    hub = readers.Hub.read(_hub(devices={"slot-1": _device(), "slot-2": None, "slot-3": []}))
    assert list(hub.devices) == ["slot-1"]
    assert set(hub.raw["devices"]) == {"slot-1", "slot-2", "slot-3"}
    assert readers.Hub.read(_hub(devices=[_device()])).devices is None


@pytest.mark.parametrize("given", [None, [], "text", 3])
def test_read_refuses_what_is_not_one_answer(given):
    with pytest.raises(TypeError) as refused:
        _load("json_project").Room.read(given)
    assert str(refused.value) == f"Room.read takes a mapping, not {type(given).__name__}"


def test_a_name_python_cannot_have_is_an_attribute_spelled_so_that_it_can():
    readers = _load("json_project")
    device = readers.Device.read(_device())
    hub = readers.Hub.read(_hub())
    assert device.class_ == "sensor" and hub.time_zone == "Example/Zone"
    # The server's own name is still the one asked about.
    assert device.sent("class") and not device.sent("class_")
    assert hub.sent("time-zone") and not hub.sent("time_zone")


def test_a_reader_is_frozen_and_is_equal_to_another_that_reads_the_same():
    readers = _load("json_project")
    room = readers.Room.read(_room())
    with pytest.raises(dataclasses.FrozenInstanceError):
        room.name = "Another Room"
    # What the model declares is what is compared: one made by hand is the one read.
    assert room == readers.Room(room_id="r1", name="Example Room")
    assert room != readers.Room(room_id="r2", name="Example Room")
    assert "sofa" not in repr(room) and "Example Room" in repr(room)
    made = readers.Room(room_id="r1")
    assert made.raw == {} and not made.sent("room_id") and made.missing() == ("name",)
    assert readers.Room().raw is not made.raw


@both
def test_a_reader_reads_every_name_the_builders_build_and_no_other(project):
    """One model, two generators: what a double may build is exactly what a reader reads,
    and what a builder insists on is what ``missing`` reports."""
    readers, elements = _load(project), _elements(project)
    assert elements["ELEMENT"], "the project declares nothing"
    for key, element in elements["ELEMENT"].items():
        reader = getattr(readers, element)
        read = [one.name for one in dataclasses.fields(reader)]
        spelled = [SPELLED.get(name, name) for name in elements["ATTRIBUTES"][key]]
        assert read == [*spelled, "raw"]
        assert reader.read({}).missing() == elements["REQUIRED"][key]
        built = elements[key](**dict.fromkeys(elements["REQUIRED"][key], "1"))
        assert reader.read(built).missing() == ()


@both
def test_a_module_carries_only_the_helpers_its_own_classes_call(project):
    names = set(vars(_load(project)))
    nested = {"_one", "_many", "_keyed", "_items", "_flag"}
    assert {"_answer", "_coerce"} <= names
    assert (nested <= names) if project == "json_project" else not (nested & names)


@both
def test_the_readers_are_python_3_9_and_import_the_standard_library_alone(project):
    tree = ast.parse(_path(project).read_text(encoding="utf-8"), feature_version=(3, 9))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0
            imported.add(node.module)
    assert imported == {"__future__", "collections.abc", "dataclasses"}
    # 3.9 cannot evaluate ``str | None``. Nothing asks it to: every annotation is a string.
    assert "annotations" in vars(_load(project))


def _ruff(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "ruff", *args, "--isolated", "--no-cache"],
        capture_output=True,
        text=True,
        check=False,
    )


@both
def test_the_readers_pass_the_lint_a_consuming_project_holds_its_own_source_to(project):
    """A consumer commits this file among its own and excludes nothing from its checks."""
    result = _ruff(
        "check",
        "--select=E,F,W,I,UP,B,C4,SIM,RUF",
        "--ignore=E501",
        "--target-version=py39",
        str(_path(project)),
    )
    assert result.returncode == 0, result.stdout + result.stderr


@both
@pytest.mark.parametrize("width", [79, 88, 100, 120, 200])
def test_the_readers_are_as_a_formatter_leaves_them_whatever_its_line_length(project, width):
    result = _ruff("format", "--check", "--diff", f"--line-length={width}", str(_path(project)))
    assert result.returncode == 0, result.stdout + result.stderr
