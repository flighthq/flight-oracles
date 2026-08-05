# flight-oracles

Sources, verifies, and publishes fixture data for downstream flight sdk projects as
compressed archives attached to GitHub releases.

Downstream repos currently inline their fixtures — `flighthq-ports/awayjs-examples` carries
~65 MB in-tree — so every consumer pays that cost again and nobody can tell where any of it
came from. This repository sources fixtures from their real upstreams, records provenance
per file, carries each licence with the bytes it covers, and ships versioned archives a test
suite can pin.

**Oracles** (expected-output data for comparison) are a later phase. Today this is fixtures.

## Current packs

| Pack | Files | Size | Sources |
| --- | ---: | ---: | --- |
| `spine-fixtures` | 905 | 48.6 MB | 18 Spine example exports (skeleton data, atlases, textures) |
| `swf-ruffle-fixtures` | 4810 | 42.9 MB | Ruffle's SWF test corpus — SWF versions 4 through 50 |
| `rive-fixtures` | 27 | 1.1 MB | Rive WebGPU player demo corpus |
| `rive-fixtures-unit` | — | ~139 MB | Rive unit-test assets — declared, not yet ingested |

Two variants build from each pack: `-full` (everything not excluded) and `-permissive`
(declared-permissive licence, no unresolved third-party subject matter, commercial use
permitted). `spine-fixtures` produces no `-permissive` archive — every Spine example is
declared non-commercial.

## Usage

```bash
export PYTHONPATH=tools

python3 -m oracles ingest [pack…]           # fetch at pinned commits, vendor, write locks
python3 -m oracles ingest <pack> --update   # re-resolve refs and adopt newer upstream
python3 -m oracles verify [pack…]           # re-hash vendored bytes against the locks
python3 -m oracles pack --version v0.1.0    # build dist/ archives + index.json + SHA256SUMS
python3 -m oracles drift [pack…]            # re-resolve pins, report divergence
python3 -m oracles show [pack…]             # summarise what is locked

python3 -m unittest discover -s tools/tests
```

Stdlib only — no dependencies to install, in CI or anywhere else.

## How it works

**`sources/*.toml`** are hand-authored and record *intent*: which upstream, which ref, which
paths, and what that upstream declared about the licence. The `[[source]]` block is the unit
of declaration — where one repo declares different things for different subtrees, that is
several blocks.

**`locks/*.lock.json`** are generated and record *facts*: resolved commit, per-file SHA-256,
size, container format version, and the declaration that covered each file. Hand-maintaining
5,000 file entries is not something anyone will keep doing correctly, so the split matters.

The spec carries a ref, the lock carries the commit. A plain `ingest` reuses the locked
commit and is reproducible; `--update` moves the pin deliberately.

**`licenses/`** holds each upstream's licence text captured *at the pinned commit*. If an
upstream relicenses or disappears, what we relied on stays verifiable.

**`vendor/`** holds the bytes. Currently gitignored — see the note in `.gitignore`, which is
a repository-weight decision rather than a technical one.

Archives are byte-reproducible: sorted entries, zeroed mtimes, fixed modes and ownership.
Rebuilding the same lock produces the same digest.

## Provenance model

We report what each source **declared**; we do not adjudicate it. A manifest entry is a claim
about a document — *"rive-runtime's LICENSE said MIT at commit abc123"* — not a claim about
the world. That is mechanically derivable for thousands of files and stays true even if the
declaration turns out to have been wrong.

`declaredScope` records how specific the declaration was (`file-adjacent`, `directory`,
`repository-root`), because a repository-root LICENSE is a statement about a repository, not
about every binary inside it.

Nothing is excluded on a guess. Files with no resolvable licence are recorded as
`declared: UNKNOWN` with where and when they were found, because a labelled unknown is more
useful than an omission. Third-party subject matter gets a `depicts` annotation naming the
subject and rights holder alongside the declaration — authorship and subject matter are
separate facts, and the manifest records both rather than resolving the blur.

**One thing is excluded, and not as a judgement call:** where a declaration *explicitly
forbids* redistribution, honouring it and republishing are incompatible. Two Spine examples
are declared this way by third-party authors — `dragon` (Thiago Brayner) and `hero` (XDTech),
both "may not be redistributed for any reason". They stay in `sources/spine-fixtures.toml`
with the clause quoted, so the record of having checked is durable, and the pipeline refuses
to vendor or pack them.

File-adjacent licences travel beside their assets as well as in `LICENSES/`, because
spineboy's terms permit redistribution "as long as they are accompanied by this license
file" and the safe reading of *accompanied* is adjacent, not merely present.

See [`docs/sourcing-policy.md`](docs/sourcing-policy.md) for the full reasoning, and
[`docs/fixture-coverage.md`](docs/fixture-coverage.md) for the exhaustive fixture target set
derived from flight's decode surface.

## Removal requests

Every file records where it came from and the licence found there, and some are marked
unknown because they are. If you hold rights in something here and want it removed, open an
issue. Removal is a one-line `exclude:` in the lock and a re-cut release; the pack step fails
the build if an excluded file's bytes reach an archive, so the guarantee is mechanical rather
than procedural. We also notify the upstream we obtained it from.

## Licence

Pipeline code: MIT. **The fixture archives are not MIT** — each carries its own upstream
declarations, and several are non-commercial only. See each archive's `NOTICE.md`.
