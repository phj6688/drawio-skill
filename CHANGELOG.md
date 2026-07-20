# Changelog

All notable changes to this project are documented here. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); this project aims for
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.3.0] - 2026-07-19

### Fixed

- Corrupt or malicious input now exits 1 as a bad file, not exit 2 "internal
  error": a corrupt compressed body (`zlib.error`) or a decompression bomb
  (`MemoryError`) previously escaped the input-fault path and read as a broken
  tool.
- The contrast check (22) honors drawio's default colors: a node with a dark
  fill and default (unset) black text rendered unreadable but warned nothing,
  because the check skipped any node without both colors set explicitly.

### CI

- The fixture and manifest jobs run on Python 3.10 and 3.11, enforcing the
  README's 3.10 floor.

## [0.2.0] - 2026-07-18

### Security

- Bound `decompress_body` output at a hard ceiling so a compressed `.drawio`
  whose body inflates to gigabytes fails as bad input (exit 1) instead of
  exhausting memory. Reject `<!DOCTYPE>`/`<!ENTITY>` declarations at both parse
  points (the raw file and the decompressed diagram body), so an
  entity-expansion payload is refused regardless of the host libexpat version.

### Fixed

- Duplicate cell ids are detected again: the check ran over an
  already-deduplicated map and never fired, so a file-corrupting duplicate
  validated as structurally OK. Ids are now counted at parse time, covering
  `object`/`UserObject` wrappers.
- CI now validates `.claude-plugin/plugin.json`. The old `glob('**/*.json')`
  skipped dot-directories, so the one manifest the loader parses was never
  checked; enumeration switched to `git ls-files` plus a required-key assertion.

### Testing / tooling

- Fixture-suite integrity guards: an orphan fixture with no expected file, a
  drop below the count floor, and a validator crash are each reported instead of
  passing silently or raising a traceback.
- Added a `.gitignore` for Python caches and the toolchain's own render/layout
  artifacts (`calibration.json` stays tracked by design).

## [0.1.0]

- Initial release: gated draw.io diagram authoring with a 25-check structural
  validator, headless render with a blank guard, crop-based visual review with
  nonces, and a completion record no tool can fake.

[0.3.0]: https://github.com/phj6688/drawio-skill/releases/tag/v0.3.0
[0.2.0]: https://github.com/phj6688/drawio-skill/releases/tag/v0.2.0
[0.1.0]: https://github.com/phj6688/drawio-skill/releases/tag/v0.1.0
