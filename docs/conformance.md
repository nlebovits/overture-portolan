# Portolan Conformance

Conformance means passing [rashid](https://github.com/portolan-sdi/rashid),
not claiming to conform, so it runs in CI:

```bash
python3 tests/test_conformance.py
```

That gate runs rashid without `--live`, so it never reaches the two rules in
the table below. Both probe a server, and a pull request has no server to
probe. A second gate covers them after each deploy:

```bash
python3 tests/test_live_hosting.py https://nlebovits.github.io/overture-portolan/
```

It runs from `.github/workflows/pages.yml` once the deploy succeeds. It passes
only when the host reports exactly PTL-LIV-004 and PTL-LIV-005 and nothing
else, so a third finding fails the build. The `--url` is mandatory: rashid
exempts the upstream hosts under PORTO-CORE-073 only when it knows the publish
host, and without it the Overture buckets report CORS failures this catalog
does not control. The gate also fails on any finding that names another host,
which proves the carve-out took effect.

The metadata gate fails on any error-severity finding whose rule is not listed
below.
The list starts empty and it must never grow without a row here. A known
deviation with an issue number is a debt someone can pay off. A silently
widened allow-list is a false claim about what this catalog conforms to.

## The rashid version floor

The gate needs rashid `>=0.1.5,<0.2.0`. It reads `rashid --version` and fails
outside that range. It also fails when rashid is absent, and prints the install
command. A skip would report a green run for a catalog that no validator read.

The floor is 0.1.5 because rules PTL-LNK-007, PTL-LNK-008, PTL-LNK-009 and
PTL-AST-006 do not exist below it. The gate asserts all four. An older rashid
reports a pass for a catalog that it never checked against them. The same range
is in `portolan-cli/pyproject.toml`.

The upper bound stops an unreviewed 0.2 rule set from changing what this gate
means. Raise both bounds together when you move to 0.2, and read the new rules
first.

## The rashid pin and the watch on it

The version the gates actually install is in `requirements-ci.txt`. Three
workflows read that file: `ci.yml`, `sync.yml`, and `data-pass.yml`. One file
keeps all three on one validator, because a gate must not mean one thing on a
pull request and a different thing in a weekly run.

The pin is a git commit, not a release. It names the merge commit of
[rashid#167](https://github.com/portolan-sdi/rashid/pull/167), which moves
PTL-DAT-006 off a per-row read and onto footer statistics. Measured on one
remote Overture part on 2026-08-27, that takes the data pass from 48.5 seconds
to 7.1 seconds. The fix is merged and it is not released.

`tools/check_rashid_release.py` watches PyPI for the release that ends the git
pin, and `.github/workflows/rashid-release.yml` runs it every Tuesday. When a
release above 0.1.7 appears, the workflow opens a pull request that replaces
the git URL with `rashid==X.Y.Z`.

Dependabot cannot do this work. It does not read a `pip install` inside a
workflow `run:` step, and it cannot move a requirement from a git URL to a PyPI
version. It can keep a version pin current, which is the reason the pin moved
into a requirements file. Delete the tool and the workflow after that pull
request merges, and let Dependabot take the job.

The tool reads one rashid line in one of two exact shapes. A line in a third
shape stops the check with exit code 2, and the workflow files an issue. A
check that matches nothing would report that no release is due, every week,
forever.

This file also records workarounds for the other validator CI runs. Those are
not conformance debts, because the catalog is correct and the validator is not.
They live here so nobody has to read CI code to find out why a gate skips
something.

## The weekly data pass

`tests/test_conformance.py` runs rashid with `--no-data`, so a pull request
never reaches the byte rules. Those rules read every `data` asset over HTTP
range: PTL-DAT-006 spatial ordering, PTL-DAT-007 per-row-group statistics,
PTL-DAT-008 the 150,000 row cap on a row group, and PTL-DAT-012 the GeoParquet
version.

One remote Overture part takes about 7 seconds, and the catalog cites 987
parts. A single pass is about 2 hours, which no pull request can wait for.
`.github/workflows/data-pass.yml` runs it weekly instead, as one job per
collection:

```bash
python3 tests/test_data_pass.py divisions/division_area
```

rashid takes a catalog root and it carries no flag that scopes the pass to one
collection. The gate makes a pruned copy of the catalog in a temporary
directory: the root catalog, the theme catalog, and the one collection. The
copy is metadata only.

The pass reports and it does not gate. The bytes belong to Overture. Overture
can republish a part in the middle of a release, and the pass then goes red on
data this repository does not own and cannot fix. On a failure the workflow
opens one issue, or it comments on the issue that is already open. Nothing
downstream reads the result.

The gate carries no accepted-finding list, unlike `tests/test_conformance.py`.
It never passes `--live`, so PTL-LIV-004 and PTL-LIV-005 cannot fire. Any
error-severity finding fails the job and goes in the report.

### What the pass reports today

Measured against release 2026-08-19.0 on 2026-08-27:

| Collection | Result |
|---|---|
| base/bathymetry | PTL-DAT-006: 59,963 rows in 4 row groups do not cluster spatially |
| buildings/building_part | no error |
| divisions/division | no error |
| divisions/division_area | no error |
| divisions/division_boundary | no error |

The other 10 collections were not measured, because 512 parts of
`buildings/building` cost an hour. The first scheduled run reports them.

The bathymetry finding is upstream. Overture writes that file, and this
catalog copies no bytes. It is not a row in the table below, and its rule is
not in `ACCEPTED`: that list gates a pull request, and this pass gates nothing.

## Accepted deviations

| Rule | Where | Why accepted | Tracking |
|---|---|---|---|
| PTL-LIV-004 | the published host | GitHub Pages sends no `Access-Control-Expose-Headers` and exposes no header configuration | portolan-spec#183 |
| PTL-LIV-005 | the published host | GitHub Pages returns 405 to an OPTIONS preflight, and exposes no header configuration | portolan-spec#183 |

Both findings concern range reads. A `Range` header is not CORS-safelisted, so a
ranged fetch from a browser triggers a preflight, and a range reader needs
`Content-Range`, `Accept-Ranges`, and `ETag` readable from script.

Nothing on this host is range-read. It serves STAC JSON, Markdown, thumbnails,
and style JSON. Each is small and each arrives through a simple GET, which
triggers no preflight and needs no exposed headers. The GeoParquet and PMTiles
sit on Overture's buckets, which serve range requests and cross-origin reads
correctly, and which PORTO-CORE-073 exempts because this catalog does not control
them.

GitHub Pages does answer range requests correctly, verified on 2026-08-27. It
returns 206 with `Content-Range` and `Accept-Ranges`. Only the two CORS elements
that support a browser range read are absent.

This constrains one design decision, recorded in
[publication.md](publication.md): the catalog ships plain item JSON rather than a
STAC-GeoParquet item mirror. An item mirror is a cloud-native asset, and to host
one here would put a range-read file on a host that cannot serve a preflighted
range request.

[portolan-spec#183](https://github.com/portolan-sdi/portolan-spec/issues/183)
proposes to scope these requirements to hosts that serve cloud-native assets.
Both rows leave this table when it resolves, whichever way it resolves.

<!--
When you accept one, add a row and a section explaining it, like this:

| Rule | Where | Why accepted | Tracking |
|---|---|---|---|
| PTL-VIZ-001 | all thumbnails | WebP is not yet permitted; the size saving is 4x | portolan-spec#121 |

Then add the rule id to ACCEPTED in tests/test_conformance.py. Both, or
neither.
-->

## Validator workarounds

### stac-check reports a dialect crash on every collection

`tests/test_stac_valid.py` exempts one stac-check failure:

```
'list' object has no attribute 'get'
[Schema: https://schemas.portolan-sdi.org/portolan/vX.Y.Z/schema.json]. Error in Extensions.
```

The Portolan schema is valid draft-07, and rashid validates catalogs against it
cleanly. `stac-validator`, which stac-check uses, hardcodes the JSON Schema
2020-12 dialect and ignores the `$schema` a schema declares. The profile schema
uses the draft-07 tuple form of `items` in `valid_bbox`, which means something
different under 2020-12, so the library raises instead of validating.

Tracked upstream at <https://github.com/stac-utils/stac-check/issues/159>,
and on the Portolan side at
<https://github.com/portolan-sdi/portolan-spec/issues/157>.

The exemption matches that exact message, and only when the failing schema is a
Portolan profile schema. Every other stac-check error still fails the build,
and the gate prints how many objects took the exemption.

The exemption expires on its own. The gate fails once stac-check stops emitting
the crash on a collection or item that declares the profile schema, and tells
you to delete both the exemption and this section. CI installs stac-check
unpinned, so the next release triggers that without anyone watching for it.

`tests/test_stac_valid.py` also fails when stac-check is absent, and prints the
install command. It takes no version floor and no pin. The rashid floor exists
because that gate asserts four named rules. This gate asserts no stac-check
rule. It needs the opposite property. A pin holds the exemption open after the
upstream fix ships.
