# Changelog

## [0.4.1](https://github.com/dmealing/axi-toolkit/compare/v0.4.0...v0.4.1) (2026-08-29)


### Documentation

* record the forced-release procedure and correct the stale publish job comment ([#13](https://github.com/dmealing/axi-toolkit/issues/13)) ([4dc2952](https://github.com/dmealing/axi-toolkit/commit/4dc295236bd698943b20b9ec97384b0352e5b2c4))


### Code Refactoring

* **conformance:** retire the three Plex drift gates ([#11](https://github.com/dmealing/axi-toolkit/issues/11)) ([da503f9](https://github.com/dmealing/axi-toolkit/commit/da503f9654e339755eb347c5ff4834fe2d1194f6))
* **conformance:** retire the Home Assistant service-model drift gate ([#10](https://github.com/dmealing/axi-toolkit/issues/10)) ([0c34dcc](https://github.com/dmealing/axi-toolkit/commit/0c34dcc2eabfa48057f9a0bb1f3dafdd2d651397)). Those four gates each compared a module extracted into this package against the copy still standing in the tool it came from. Both tools have since deleted their copies and import this package instead, so every gate had nothing left to compare against, and a cross-repository gate is the wrong instrument once there is one copy of the code. This is conformance machinery only: the modules themselves are unchanged, `tests/test_ha_services.py`, `tests/test_plex_ids.py` and `tests/test_plex_filters.py` state their behaviour directly, and nothing a consumer of this package imports behaves differently.


### Build System

* set the development environment up in .venv, never the ambient interpreter ([#12](https://github.com/dmealing/axi-toolkit/issues/12)) ([adcdfba](https://github.com/dmealing/axi-toolkit/commit/adcdfba5e057aa771cd186befdd3a8d48bd4606a)). Setting up a checkout is `scripts/dev-setup.sh` now: it builds `.venv` at the repository root, installs `.[dev]` into it, and prints the `.venv/bin/<tool>` forms every development command is run by afterwards. The block it replaces installed the checkout, editable, into whatever interpreter happened to be ambient, which overwrites the launcher of an existing isolated install of one of the tools this package serves and leaves it dead once the checkout is deleted, with nothing announcing it. Nothing in the shipped package behaves differently.

## [0.4.0](https://github.com/dmealing/axi-toolkit/compare/v0.3.0...v0.4.0) (2026-08-29)


### Features

* **plex:** move the Plex id and filter language in as axi_toolkit.plex ([#8](https://github.com/dmealing/axi-toolkit/issues/8)) ([b8d029f](https://github.com/dmealing/axi-toolkit/commit/b8d029f8fb8905798847fc1f18cb695c7065517e))

## [0.3.0](https://github.com/dmealing/axi-toolkit/compare/v0.2.0...v0.3.0) (2026-08-29)


### Features

* **ha:** move the Home Assistant service model in as axi_toolkit.ha.services ([#6](https://github.com/dmealing/axi-toolkit/issues/6)) ([8397ede](https://github.com/dmealing/axi-toolkit/commit/8397ede6a1aa6fe815ed27547a7313cfcf160c7c))

## [0.2.0](https://github.com/dmealing/axi-toolkit/compare/v0.1.0...v0.2.0) (2026-08-28)


### ⚠ BREAKING CHANGES

* the distribution is now axi-toolkit and the import package is axi_toolkit. There is no axi_core alias; imports must be updated.

### Features

* rename the package to axi-toolkit ([#3](https://github.com/dmealing/axi-toolkit/issues/3)) ([539d9a3](https://github.com/dmealing/axi-toolkit/commit/539d9a3d56f173b40c963b7449c77894f258b7e5))
* the shared AXI toolkit, with requirements declared before the code ([55ef182](https://github.com/dmealing/axi-toolkit/commit/55ef18222f71d0fadc3654c482eb6dd8972a16a5))
