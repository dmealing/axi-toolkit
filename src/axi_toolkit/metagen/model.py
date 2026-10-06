"""Read the loaded model into plain values, and refuse one that does not hold together.

The loader has already checked what it can: an ``extends`` naming an attribute that
does not exist, or one of another type, never gets this far. What it cannot check is
inside the property bags, which carry no registered vocabulary, so those are checked
here and a model that fails raises :class:`ModelError` before anything is written.
"""

from __future__ import annotations

from dataclasses import dataclass


class ModelError(ValueError):
    """The model loads, and still says something the generators cannot honour."""


#: The wire formats the generators know. An object that names none is read as the first,
#: which is the only one there was before a model could say.
FORMATS = ("xml-attributes", "json")


@dataclass(frozen=True)
class Capture:
    """The committed capture: where it is, and how the names in it are laid out."""

    file: str
    section: str
    list_suffix: str


@dataclass(frozen=True)
class Upstream:
    """One object the server answers: its attributes and the captures that show them."""

    fqn: str
    key: str
    element: str
    format: str
    capture: tuple
    fields: tuple
    maps: tuple
    required: tuple
    unobserved: dict


@dataclass(frozen=True)
class Row:
    """One row the tool prints: its columns, its default set and what each column reads.

    ``reads`` is what a column reads of the row's own object. ``also`` is what it reads
    of any other declared object, by that object, and ``key_of`` is the map it is a key
    of, as ``(object, field)``; a column appears in those two only when it says so.
    """

    fqn: str
    key: str
    of: str
    capture: tuple
    reads: dict
    also: dict
    key_of: dict
    default: tuple


@dataclass(frozen=True)
class Model:
    """Everything the generators emit from, read once and already checked."""

    objects: list
    rows: list
    capture: Capture | None


def bag(node, name):
    """A property bag, read through the resolving accessor so an inherited one is seen."""
    value = node.attrs().get(name)
    return getattr(value, "value", value)


def fqn(obj) -> str:
    package = getattr(obj, "package", None) or getattr(obj, "file_default_package", None)
    return f"{package}::{obj.name}" if package else obj.name


def _objects(root) -> list:
    return [child for child in root.children() if getattr(child, "type", "") == "object"]


def _extends(field):
    """The member a field extends, as ``(owner, member)``, or ``None``."""
    ref = getattr(field, "super_ref", None)
    if not ref or "." not in str(ref):
        return None
    owner, member = str(ref).rsplit(".", 1)
    return owner, member


def _names(value, what: str) -> tuple:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ModelError(f"{what} must be a list of names")
    return tuple(value)


def capture(root) -> Capture:
    """The committed capture: its path from the project root, and how to read it.

    ``section`` is the key of the capture file that holds the answers. ``list_suffix``
    is for a capture that records what a list held as a second name beside the list's
    own, the same name with this on the end: such a name is not one the server sent.
    """
    settings = bag(root, "capture")
    if not isinstance(settings, dict) or not isinstance(settings.get("file"), str):
        raise ModelError("the model root needs a `capture` bag naming its `file`")
    section = settings.get("section", "elements")
    if not isinstance(section, str) or not section:
        raise ModelError("`capture.section` must name the key of the capture file's answers")
    list_suffix = settings.get("list_suffix", "")
    if not isinstance(list_suffix, str) or ("list_suffix" in settings and not list_suffix):
        raise ModelError("`capture.list_suffix` must be the ending of a name that is a list's")
    return Capture(file=settings["file"], section=section, list_suffix=list_suffix)


def upstream(root) -> list:
    found = []
    for obj in _objects(root):
        wire = bag(obj, "wire")
        if wire is None:
            continue
        name = fqn(obj)
        for needed in ("key", "element", "capture"):
            if needed not in wire:
                raise ModelError(f"{name}: the `wire` bag needs `{needed}`")
        form = wire.get("format", FORMATS[0])
        if form not in FORMATS:
            raise ModelError(f"{name}: `wire.format` is {form!r}, and must be one of {FORMATS}")
        fields = obj.fields()
        unobserved = {}
        for field in fields:
            excuse = bag(field, "unobserved")
            if excuse is None:
                continue
            reason = excuse.get("reason") if isinstance(excuse, dict) else None
            if not isinstance(reason, str) or not reason.strip():
                raise ModelError(f"{name}.{field.name}: `unobserved` needs a `reason`")
            unobserved[field.name] = reason
        found.append(
            Upstream(
                fqn=name,
                key=wire["key"],
                element=wire["element"],
                format=form,
                capture=_names(wire["capture"], f"{name}: `wire.capture`"),
                fields=tuple(field.name for field in fields),
                maps=tuple(f.name for f in fields if getattr(f, "sub_type", "") == "map"),
                required=tuple(f.name for f in fields if f.attrs().get("required")),
                unobserved=unobserved,
            )
        )
    keys = [entry.key for entry in found]
    if len(set(keys)) != len(keys):
        raise ModelError(f"two objects share a `wire.key`: {sorted(keys)}")
    return found


def _defaults(root) -> dict:
    """Each projection that is a subset of one object's fields, by that object."""
    found: dict = {}
    for obj in _objects(root):
        if obj.sub_type != "projection":
            continue
        refs = [_extends(field) for field in obj.fields()]
        owners = {ref[0] for ref in refs if ref}
        if not all(refs) or len(owners) != 1:
            continue
        owner = owners.pop()
        if owner in found:
            raise ModelError(f"{owner} has two default projections")
        found[owner] = tuple(field.name for field in obj.fields())
    return found


def _wire_or_refuse(sources: dict, owner: str, where: str) -> Upstream:
    """The object a reference names, refusing one that declares no `wire`.

    ``where`` is the phrase that introduces the name, up to and including the bag
    it came from: every refusal of an unnamed object reads the same way.
    """
    other = sources.get(owner)
    if other is None:
        raise ModelError(f"{where} names {owner!r}, which declares no `wire`")
    return other


def _reads_declared(column: str, names: tuple, owner: str, fields: tuple) -> None:
    """Refuse names a column reads that the object it reads them from does not declare."""
    unknown = sorted(set(names) - set(fields))
    if unknown:
        raise ModelError(f"{column} reads {unknown}, which {owner} does not declare")


def _also(column: str, derived: dict, source: Upstream, sources: dict) -> dict:
    """What a column reads of objects other than its row's own, by that object."""
    declared = derived.get("also")
    if declared is None:
        return {}
    if not isinstance(declared, dict) or not declared:
        raise ModelError(f"{column}: `derived.also` must map an object to the names read of it")
    found = {}
    for owner, value in declared.items():
        names = _names(value, f"{column}: `derived.also` for {owner}")
        if owner == source.fqn:
            raise ModelError(
                f"{column}: `derived.also` names {owner}, which is the row's own object: "
                "what is read of it belongs in `derived.reads`"
            )
        other = _wire_or_refuse(sources, owner, f"{column}: `derived.also`")
        if not names:
            raise ModelError(f"{column}: `derived.also` names nothing it reads of {owner}")
        _reads_declared(column, names, owner, other.fields)
        found[owner] = names
    return found


def _key_of(column: str, derived: dict, sources: dict):
    """The map a column is a key of, as ``(owner, field)``, or ``None``.

    The owner may be the row's own object, which ``also`` may not name: an object that
    nests under a map of its own kind is keyed there, and there is no other way to say so.
    """
    declared = derived.get("key_of")
    if declared is None:
        return None
    owner, _, member = declared.rpartition(".") if isinstance(declared, str) else ("", "", "")
    if not owner or not member:
        raise ModelError(f"{column}: `derived.key_of` must name a map, as `Object.field`")
    other = _wire_or_refuse(sources, owner, f"{column}: `derived.key_of`")
    if member not in other.maps:
        raise ModelError(f"{column}: `derived.key_of` names {declared}, which is not a map")
    return owner, member


def rows(root, objects) -> list:
    sources = {entry.fqn: entry for entry in objects}
    defaults = _defaults(root)
    found = []
    for obj in _objects(root):
        row = bag(obj, "row")
        if row is None:
            continue
        name = fqn(obj)
        for needed in ("key", "of", "capture"):
            if needed not in row:
                raise ModelError(f"{name}: the `row` bag needs `{needed}`")
        source = _wire_or_refuse(sources, row["of"], f"{name}: `row.of`")
        built_from = _names(row["capture"], f"{name}: `row.capture`")
        stray = sorted(set(built_from) - set(source.capture))
        if stray:
            raise ModelError(f"{name}: `row.capture` names {stray}, not answers of {source.fqn}")
        reads, also, key_of = {}, {}, {}
        for field in obj.fields():
            column = f"{name}.{field.name}"
            ref = _extends(field)
            derived = bag(field, "derived")
            derived = derived if isinstance(derived, dict) else {}
            others = _also(column, derived, source, sources)
            under = _key_of(column, derived, sources)
            if others:
                also[field.name] = others
            if under:
                key_of[field.name] = under
            if ref and ref[0] == source.fqn:
                reads[field.name] = (ref[1],)
                continue
            if not derived.get("reads"):
                if not others and not under:
                    raise ModelError(
                        f"{column} says nothing about where it is read from: extend an "
                        f"attribute of {source.fqn}, or name what it reads in a `derived` bag"
                    )
                reads[field.name] = ()
                continue
            names = _names(derived["reads"], f"{column}: `derived.reads`")
            _reads_declared(column, names, source.fqn, source.fields)
            reads[field.name] = names
        if name not in defaults:
            raise ModelError(f"{name} has no default projection")
        found.append(
            Row(
                fqn=name,
                key=row["key"],
                of=source.fqn,
                capture=built_from,
                reads=reads,
                also=also,
                key_of=key_of,
                default=defaults[name],
            )
        )
    keys = [entry.key for entry in found]
    if len(set(keys)) != len(keys):
        raise ModelError(f"two rows share a `row.key`: {sorted(keys)}")
    return found


def read(root) -> Model:
    """The whole model, refused here if any generator would refuse it.

    Each generator emits from its own part, and they run one after another, so one that
    read only its part would have written before a later one refused. A project that runs
    no capture check need not name a capture, and ``capture`` is then ``None``.
    """
    objects = upstream(root)
    named = bag(root, "capture") is not None
    return Model(
        objects=objects, rows=rows(root, objects), capture=capture(root) if named else None
    )
