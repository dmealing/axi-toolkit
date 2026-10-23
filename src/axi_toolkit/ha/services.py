"""Home Assistant's own service model, read live and used only where it helps.

``GET /api/services`` publishes every service the installation has registered:
each field, which are required, the selector each one takes, whether the service
answers with a response payload, and -- for the services where it matters -- the
capability a target entity must have before the service can reach it.

The model is deliberately **not** used to generate commands. A generated surface
would be maximally confident and capability-blind, and would duplicate the one
general call command once per service, which is why a tool that adopts this
module keeps that command and consults the model to explain it. It is used for
three narrow things instead: explaining a refusal, rendering one service's field
table on request, and checking a capability before dispatch.

Nothing here is cached. An integration added or removed rewrites the model and
nothing signals when, so a stale copy would turn a valid call into a hard
failure -- which is worse than not knowing. Every function below is pure: the
caller does the fetching and decides whether it is worth paying for.

The model is read through the readers generated into
:mod:`axi_toolkit.ha.model.readers` from the declaration under ``models/``, and
never by key: every name read here is one that declaration holds to a capture of
a real server. A domain, a service and a field are handed back as their readers.
A function that takes one service or one field takes its reader, the mapping it
was parsed into, which is read through that reader, or ``None`` for one that
declares nothing.
"""

from __future__ import annotations

import difflib
from collections.abc import Mapping

from .model.readers import Service, ServiceDomain, ServiceField

#: Keys Home Assistant reads as targeting rather than as service data. They are
#: never declared as fields, so an unknown-field check has to allow them.
TARGET_KEYS = ("entity_id", "device_id", "area_id", "floor_id", "label_id")

RESPONSE_NONE = "none"
RESPONSE_OPTIONAL = "optional"
RESPONSE_REQUIRED = "required"


def domains(model) -> list:
    """Every service domain the installation has registered, sorted."""
    return sorted(entry.domain for entry in _entries(model) if entry.domain)


def find_domain(model, domain: str):
    """One domain's published entry, as its reader, or None."""
    for entry in _entries(model):
        if entry.domain == domain:
            return entry
    return None


def service_names(model, domain: str) -> list:
    """Every service a domain registers, sorted.

    One published with null in place of its description is registered all the same,
    and is named here: a listing that dropped it would hide a service that exists.
    """
    entry = find_domain(model, domain)
    services = entry.services if entry is not None else None
    return sorted(services) if services is not None else []


def find_service(model, domain: str, service: str):
    """The published description of one service, as its reader.

    None if it is not registered, and None if it is registered with no description.
    """
    entry = find_domain(model, domain)
    services = entry.services if entry is not None else None
    return services.get(service) if services is not None else None


def near(needle: str, candidates, limit: int = 6) -> list:
    """The candidates a wrong name plausibly meant, or nothing.

    Deliberately allowed to come back empty. A caller that pads this out with
    whatever else exists turns "did you mean" into a claim it cannot support;
    listing the rest is a separate sentence, and reads as one.
    """
    pool = [candidate for candidate in candidates if candidate]
    close = difflib.get_close_matches(needle, pool, n=limit, cutoff=0.6)
    prefix = needle[:4]
    for candidate in pool:
        if len(close) >= limit:
            break
        if candidate not in close and len(prefix) >= 3 and candidate.startswith(prefix):
            close.append(candidate)
    return close


def fields(spec) -> list:
    """Every declared field as ``(name, field, section)``, sections flattened.

    A section is a display grouping only: Home Assistant validates the service
    data flat, so a field inside one is passed exactly like an ungrouped one.
    Reporting the section as though it were itself a field would invite an
    agent to send it. A field published with nothing declared is still one the
    service accepts, and is handed back as a field that declares nothing.
    """
    out = []
    spec = _read(Service, spec)
    declared = spec.fields if spec is not None else None
    if declared is None:
        return out
    for name, field in declared.items():
        field = field or ServiceField()
        if field.fields is not None:
            for inner_name, inner_field in field.fields.items():
                out.append((inner_name, inner_field or ServiceField(), name))
        else:
            out.append((name, field, ""))
    return out


def field_names(spec) -> list:
    return [name for name, _, _ in fields(spec)]


def required_field_names(spec) -> list:
    return [name for name, field, _ in fields(spec) if field.required]


def selector_kind(field) -> str:
    """The one-word type a field's selector declares, or '' when it declares none.

    A selector is one key naming its kind and holding that kind's configuration, so
    the kind is the key itself and not a value read under one.
    """
    field = _read(ServiceField, field)
    selector = field.selector if field is not None else None
    return next(iter(selector.raw), "") if selector is not None else ""


def selector_options(field) -> list:
    """The values a `select` selector accepts, so a miss can list them.

    An option published as a label and a value is reduced to its value. The capture
    has never seen one, so no reader declares one, and it is read where it is found.
    """
    field = _read(ServiceField, field)
    selector = field.selector if field is not None else None
    select = selector.select if selector is not None else None
    options = select.options if select is not None else None
    if options is None:
        return []
    return [o.get("value", "") if isinstance(o, Mapping) else str(o) for o in options]


def response_mode(spec) -> str:
    """Whether the service answers with a payload: none, optional, or required.

    Home Assistant includes the ``response`` key only for a service that can
    answer, and ``optional: false`` means it answers with one or not at all.
    """
    spec = _read(Service, spec)
    response = spec.response if spec is not None else None
    if response is None:
        return RESPONSE_NONE
    return RESPONSE_OPTIONAL if response.optional else RESPONSE_REQUIRED


def takes_target(spec) -> bool:
    """Whether the service publishes a target at all, which an entity service does.

    One published empty still does: it narrows nothing, and the service still acts on
    a target. Only a service that publishes no target, or null, takes none. This is
    the question a caller asks before sending a call that names no target.
    """
    spec = _read(Service, spec)
    return spec is not None and spec.target is not None


def describes_target(spec) -> bool:
    """Whether the published target says anything about what the service can reach.

    An empty one says nothing, so it reads as no target wherever a target is
    described or counted, while :func:`takes_target` still counts it as one. That
    difference is the whole reason there are two functions.
    """
    spec = _read(Service, spec)
    target = spec.target if spec is not None else None
    return target is not None and bool(target.raw)


def target_domains(spec) -> list:
    """The entity domains a service says it can be aimed at.

    Empty means "no published restriction", which is the honest reading of both
    a service that declares no entity target and one whose entity filter names
    no domain -- `homeassistant.turn_on` reaches every domain by design. Filter
    a resolved target through this rather than through the service's own domain
    name: an integration is free to register a service that acts on another
    domain's entities, and several do.
    """
    out: list = []
    for entry in _entity_filters(spec) or ():
        if entry.domain is None:
            return []
        out.extend(name for name in entry.domain if isinstance(name, str))
    return sorted(set(out))


def feature_masks(spec, domain: str) -> list:
    """The capability masks a target entity must satisfy, if any are published.

    Home Assistant resolves the enum names in ``services.yaml`` to integers
    before publishing them, and treats the list as alternatives: an entity
    qualifies when it satisfies **any** one mask. That is what encodes an
    upstream fallback -- ``media_player.volume_up`` publishes both VOLUME_SET
    and VOLUME_STEP because core backs a player that cannot step with one that
    can set, so a speaker with only the first still qualifies. Reading the list
    as a conjunction would gate exactly the behaviour that works today.

    Read only when the entity filter names exactly this service's own domain. A
    service that targets another domain's entities publishes that other domain's
    capability names, which say nothing about the entity it will reach; and a
    value that did not resolve to an integer disables the gate rather than
    guessing at it.
    """
    entries = _entity_filters(spec)
    if entries is None or len(entries) != 1:
        return []
    entry = entries[0]
    if list(entry.domain or ()) != [domain]:
        return []
    masks = entry.supported_features
    if not masks:
        return []
    resolved = [m for m in masks if isinstance(m, int) and not isinstance(m, bool) and m > 0]
    return resolved if len(resolved) == len(masks) else []


def satisfies(features, masks) -> bool:
    """Home Assistant's own rule: any one mask fully present in the entity's bits."""
    if not masks:
        return True
    if not isinstance(features, int) or isinstance(features, bool):
        return False
    return any(features & mask == mask for mask in masks)


def entity_features(state) -> int:
    """The `supported_features` bits a state reports, absent counting as none.

    A state is not part of the service model, and no reader for one is declared here,
    so this is the one function that reads what it is given by key.
    """
    value = (state.get("attributes") or {}).get("supported_features")
    if isinstance(value, bool) or not isinstance(value, int):
        return 0
    return value


def _entries(model):
    """Each published domain, read through its reader as it is reached."""
    if not isinstance(model, list):
        return
    for entry in model:
        if isinstance(entry, Mapping):
            yield ServiceDomain.read(entry)


def _entity_filters(spec):
    """The entity filters of a service's target, as their readers, or None."""
    spec = _read(Service, spec)
    target = spec.target if spec is not None else None
    return target.entity if target is not None else None


def _read(reader, value):
    """A service or a field as its reader: one already read, or a mapping read now."""
    if value is None or isinstance(value, reader):
        return value
    return reader.read(value) if isinstance(value, Mapping) else None
