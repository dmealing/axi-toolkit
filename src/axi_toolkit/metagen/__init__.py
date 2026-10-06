"""Project-owned MetaObjects generators: what an upstream API answers, declared once.

The stock ``metaobjects gen`` runs these; ``metaobjects.config.yaml`` names each one as
``metagen:<symbol>``. They read the loaded model under ``metaobjects/`` and emit Python
that imports the standard library alone and is written in the oldest syntax the
consuming package supports, so the toolchain's own Python floor never reaches it.

Nothing here is imported by the package or by its test suite. It needs ``metaobjects``
and a Python that can run it, at development time only: to regenerate, and for
``metaobjects verify --codegen`` to prove the committed output is what the model emits.

Four generators, and what each one reads:

``rows``
    An object carrying a ``row`` bag is a row the tool prints. Its fields are the
    columns, in order; the projection whose fields extend them is the default set.
    Emits the column vocabulary, the default set and the attributes each column reads.
``elements``
    An object carrying a ``wire`` bag is something the server answers. Emits one
    builder per object that a test double builds its answers through, and that
    refuses an attribute the model does not declare.
``capture_contract``
    Emits the check that every declared attribute is in a committed capture of a real
    server's answers, or carries the reason it could not be observed.

``readers``
    Emits one frozen dataclass per object carrying a ``wire`` bag, in one module, with
    ``read(raw)``, ``sent(name)`` and ``missing()``. It is what a command reads an
    answer through in place of a chain of lookups by name, so the names it reads are
    the ones the capture check holds to a real server. A ``field.object`` is read
    through the reader of the object its ``objectRef`` names, a list of them as a
    tuple and a ``field.map`` of them as a dict. A ``field.string`` whose
    ``dbColumnType`` is ``jsonb`` is an open bag and is handed over as it was sent,
    and the whole answer is kept as ``raw``, so a name the model does not declare is
    never lost. ``None`` is a name not sent or sent as null; ``sent`` tells which.
    An attribute is the server's own name, except one Python cannot have, which takes
    an underscore where it must. A model is refused, by this generator alone, when two
    objects would be one class, two names of an object one attribute, or a nested
    object declares no ``wire`` and so has no reader.

What a model may say beyond that, and what is assumed of one that does not:

``wire.format``
    ``xml-attributes`` or ``json``; an object that names neither is the first. It
    decides the words a builder refuses in -- an attribute of an element, or a key of
    an object -- and how a reader takes a plain value: a key as it was parsed, and an
    attribute, which arrives as text, as the number or the yes-or-no the model declares
    it to be, or ``None`` when the text is not one. The tables keep one name each
    whatever it is.
``capture.section``
    The key of the capture file that holds the answers. ``elements`` when not named.
``capture.list_suffix``
    For a capture that records what a list held as a second name beside the list's
    own, that name's ending. Such a name is not one the server sent, and no check is
    shown it. A capture that names no ending is read as it is written.
``derived.also``
    On a column: the names it reads of objects other than its row's own, by object.
    Each is checked against that object, ``READS`` carries it as ``package::Object.name``,
    and the capture check requires it in every answer of that object, less whatever
    that object itself says could not be observed.
``derived.key_of``
    On a column: the map it is a key of, as ``package::Object.field``. Emitted as
    ``KEY_OF``, and the capture check holds the map to the answers of the object that
    declares it. A column that says this, or ``also``, need name no ``reads``.

This directory holds no name from any one project, so that it can move into a shared
library as it stands.
"""

from .emit import capture_contract, elements, readers, rows

__all__ = ["capture_contract", "elements", "readers", "rows"]
