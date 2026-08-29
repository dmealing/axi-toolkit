"""The Plex domain tier.

Two modules, and the split between them is the one the extraction had to get right:

- :mod:`axi_toolkit.plex.ids` -- which ``plex://`` string is safe to hand to a
  consumer and which is a bug. Six forms are in circulation, two of them break a
  media player and one raises inside it.
- :mod:`axi_toolkit.plex.filters` -- the pure half of the music search language:
  stars, the field map, the one inequality a real Plex section offers for an
  integer, relative dates and sort directions.

Everything here takes plain values and returns plain values. What is deliberately
*not* here is the probing layer -- anything that takes a ``server``, a ``section``
or a page of ``items`` -- and the classification of ``plexapi``'s own exceptions.
Both need the client library; these two modules need ``math`` and ``re``, which is
why the ``plex`` extra is not a dependency of anything in this package and the
distribution still declares no runtime dependency at all.
"""
