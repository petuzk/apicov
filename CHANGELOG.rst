=========
Changelog
=========

Note: this project is in early development, so expect breaking changes in every release.

unreleased
==========

Added
-----

- Settings to ``include`` and ``exclude`` paths to trace, configurable via pyproject.toml, apicov.toml or CLI
- Serialization of apicov trace data into a file for later analysis and report generation

Changed
-------

- Split CLI into `run` and `html` subcommands to separate data collection and report generation

apicov 0.0.2
============

Added
-----

- Readme
- Support for more types (tuples, collections, Any, Self, Literal, Never)
- Support for function overloads
- Calculation of API coverage on different levels (single arguments or aggregated by functions, classes, modules)
- HTML report generation showing matched and unmatched calls, API coverage

apicov 0.0.1
============

Initial release of a proof of concept.
More importantly, grab a name on PyPI.
