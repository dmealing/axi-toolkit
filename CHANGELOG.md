# Changelog

## [1.0.1](https://github.com/dmealing/axi-toolkit/compare/v1.0.0...v1.0.1) (2026-10-29)


### Documentation

* **metagen:** name generators as axi_toolkit.metagen:&lt;generator&gt; in module docstring ([#40](https://github.com/dmealing/axi-toolkit/issues/40)) ([020ac6c](https://github.com/dmealing/axi-toolkit/commit/020ac6cdf44835bd7524f4f85838359c39216fe5))

## [1.0.0](https://github.com/dmealing/axi-toolkit/compare/v0.8.1...v1.0.0) (2026-10-24)


### Documentation

* declare stable surface and drop pre-1.0 version rule ([#38](https://github.com/dmealing/axi-toolkit/issues/38)) ([76c09ce](https://github.com/dmealing/axi-toolkit/commit/76c09ce596ef080712423728ef9622990990c79c))

## [0.8.1](https://github.com/dmealing/axi-toolkit/compare/v0.8.0...v0.8.1) (2026-10-24)


### Bug Fixes

* **plex:** accept only ASCII digits in rating keys, local guids and dates ([#34](https://github.com/dmealing/axi-toolkit/issues/34)) ([10fa96c](https://github.com/dmealing/axi-toolkit/commit/10fa96cef45c055b2dac3e7d5cb6bbac3ba3fc98))


### Documentation

* add search terms to package summary and keywords ([#36](https://github.com/dmealing/axi-toolkit/issues/36)) ([700e7b4](https://github.com/dmealing/axi-toolkit/commit/700e7b4c27ef6e00b809b34fa1e8c4dc2be1665d))
* retire the Plex probing-layer extraction ([#35](https://github.com/dmealing/axi-toolkit/issues/35)) ([8ecf812](https://github.com/dmealing/axi-toolkit/commit/8ecf8122c29fc515264edbd9cdb96c2a95bc97eb))

## [0.8.0](https://github.com/dmealing/axi-toolkit/compare/v0.7.1...v0.8.0) (2026-10-24)


### ⚠ BREAKING CHANGES

* **ha:** axi_toolkit.ha.services.find_domain, find_service and fields return generated reader objects instead of the raw mappings. Each reader keeps the mapping it read as `.raw`.

### Features

* **ha:** read published service model through generated readers ([#32](https://github.com/dmealing/axi-toolkit/issues/32)) ([3504400](https://github.com/dmealing/axi-toolkit/commit/35044007e1bf3c86c1188b340a36c0334ed8392e))

## [0.7.1](https://github.com/dmealing/axi-toolkit/compare/v0.7.0...v0.7.1) (2026-10-23)


### Documentation

* **readme:** state the metaobjects pin the development extras carry ([#30](https://github.com/dmealing/axi-toolkit/issues/30)) ([e0bb971](https://github.com/dmealing/axi-toolkit/commit/e0bb971d07f381d67d5e1b80cfee085728af457d))

## [0.7.0](https://github.com/dmealing/axi-toolkit/compare/v0.6.0...v0.7.0) (2026-10-06)


### Features

* **metagen:** generate a reader for each object the server answers ([#27](https://github.com/dmealing/axi-toolkit/issues/27)) ([dd812a3](https://github.com/dmealing/axi-toolkit/commit/dd812a3a5b2b50d0bed72f6cb26dff8772b3ac60))

## [0.6.0](https://github.com/dmealing/axi-toolkit/compare/v0.5.0...v0.6.0) (2026-10-06)


### Features

* **metagen:** let a model name its capture section, read other objects, and be JSON ([#25](https://github.com/dmealing/axi-toolkit/issues/25)) ([dda7bbb](https://github.com/dmealing/axi-toolkit/commit/dda7bbba3b73d7fdb4ce7b8a5838dd3d095404d4))

## [0.5.0](https://github.com/dmealing/axi-toolkit/compare/v0.4.3...v0.5.0) (2026-10-06)


### Features

* **metagen:** ship the MetaObjects generators as a development extra ([#23](https://github.com/dmealing/axi-toolkit/issues/23)) ([47cd100](https://github.com/dmealing/axi-toolkit/commit/47cd1004c392c3d662b9a6f963d48e7c5913c61c))

## [0.4.3](https://github.com/dmealing/axi-toolkit/compare/v0.4.2...v0.4.3) (2026-10-06)


### Bug Fixes

* **commitcheck:** fault release bodies that silently replace a commit message ([#20](https://github.com/dmealing/axi-toolkit/issues/20)) ([36738bb](https://github.com/dmealing/axi-toolkit/commit/36738bb92cab554e584c9bf0ae9c357057633ec1))

## [0.4.2](https://github.com/dmealing/axi-toolkit/compare/v0.4.1...v0.4.2) (2026-10-05)


### Bug Fixes

* **toolkit:** align with hass-axi rename, add delegation-parameter redaction, fix TOON encoder regex ([#18](https://github.com/dmealing/axi-toolkit/issues/18)) ([9dad76e](https://github.com/dmealing/axi-toolkit/commit/9dad76e8c91adb484202e5dcb5bd47b301764241))

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
