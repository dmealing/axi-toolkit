"""The Home Assistant domain tier.

:mod:`axi_toolkit.ha.services` reads the service model an installation publishes at
``GET /api/services``. It is pure and stdlib-only: the caller fetches the model and
decides whether the read is worth paying for, and this package still declares no
runtime dependency -- the ``ha`` extra exists to say where the tier lives, not to
install a transport.

:mod:`axi_toolkit.ha.model.readers` is what it reads that model through: one reader per
object of it, generated from the declaration under ``models/`` and standard-library
Python like everything else here.
"""
