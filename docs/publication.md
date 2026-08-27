# Publication

This catalog is deployed to GitHub Pages by `.github/workflows/pages.yml`. It
uploads nothing to an object store, and it carries neither of the two publishers
the Portolan tooling ships. That is a deliberate departure, and this page records
why, along with the two conformance findings it costs.

## How it works

A push to `main` uploads `catalog/` as the Pages artifact and deploys it. There is
no build step, no upload command, and no storage credential anywhere.

Pages can only serve `/` or `/docs` when it deploys from a branch, and the
published catalog is `catalog/`. The workflow therefore uses the Actions
deployment path, which can take any directory. That choice also preserves the
property this catalog depends on: the deployed state equals the repository state,
so a file that leaves `catalog/` leaves the site.

## Why not a bucket

Portolan offers two bucket publishers. `portolan push` records what it uploaded in
`versions.json`, keyed on sha256. The catalog template's `tools/publish.py` is
stateless and diffs local size and MD5 against a remote listing.

Both share a property their own documentation states plainly: publishing never
deletes. Removal of a file from the catalog does not remove the object from the
bucket.

For most catalogs that is a footnote. Here it is a defect, because of what the
upstream does.

This catalog mirrors Overture Maps, which ships a release every month. Overture
part filenames carry UUIDs, so every asset href changes on every release, even
when the schema and the row counts do not. A bucket would therefore keep a
complete copy of the previous catalog live at its old URLs after each sync, twelve
times a year. To close that gap needs a prune tool, and a prune tool that guesses
wrong deletes a live catalog.

A git-deployed host removes the problem instead of management of it.

## What this costs: two accepted deviations

Portolan requires a host to answer range requests and to permit cross-origin
reads, so browser clients read data directly. `rashid` checks this in its live
pass. Measured against GitHub Pages on 2026-08-27:

| Check | Requirement | Result |
|---|---|---|
| PTL-LIV-001, PTL-LIV-002 | `Range` answered with 206 | passes |
| PTL-LIV-003 | `Access-Control-Allow-Origin` | passes, sends `*` |
| PTL-LIV-004 | `Access-Control-Expose-Headers` | fails, sends none |
| PTL-LIV-005 | OPTIONS preflight | fails, returns 405 |

GitHub Pages exposes no header configuration, so neither failure is fixable from
this repository. Both are recorded in [conformance.md](conformance.md).

The two failures matter only for range reads. A `Range` header is not
CORS-safelisted, so a ranged fetch from a browser triggers a preflight, and a range
reader needs `Content-Range`, `Accept-Ranges`, and `ETag` readable from script.

**Nothing on this host is range-read.** It serves STAC JSON, Markdown,
thumbnails, and style JSON. Each is small and each is fetched whole by a simple
GET, which triggers no preflight and needs no exposed headers. The GeoParquet and
PMTiles live on Overture's buckets, which answer range requests and permit
cross-origin reads correctly, and which PORTO-CORE-073 exempts from these
requirements because this catalog does not control them.

So the findings are real against the letter of the spec and describe no defect a
client can encounter. See [portolan-spec#183](https://github.com/portolan-sdi/portolan-spec/issues/183),
which proposes to scope the requirements to hosts that serve cloud-native assets.

## Why this rules out a STAC-GeoParquet item mirror

PORTO-FMT-038 recommends an item mirror above 100 items, and every large
collection here clears that. This catalog ships plain item JSON instead.

An item mirror is `application/vnd.apache.parquet`, which is a cloud-native asset.
To host one here would put a range-read file on a host that cannot serve a
preflighted range request, and the two accepted deviations above would stop
describing a technicality and start describing a broken client.

The item mirror is a generated artifact rather than a migration, so it returns for
free if either the host or the requirement changes.

## Why not Cloudflare

Cloudflare Pages and Workers static assets both looked like better candidates,
because a `_headers` file sets arbitrary response headers and would close both
gaps above.

Neither can serve a Portolan catalog. Their asset layer does not implement 206
Partial Content, and no configuration changes it. Measured on 2026-08-27, a ranged
request for a 1,649-byte `catalog.json` returned 200 with the full body and no
`Accept-Ranges` header. See
[cloudflare/workers-sdk#3861](https://github.com/cloudflare/workers-sdk/issues/3861).

Range support is a property of the serving layer rather than a header, so it fails
in the one place a header file cannot reach. This is recorded because the failure
is invisible until deploy time, and the `_headers` support makes Cloudflare look
like the obvious answer.

## Reversing this

Nothing here is one-way. If a Source Cooperative copy is wanted later, for the
discoverability that source.coop offers and a `github.io` domain does not, restore
`tools/publish.py` and `catalog.publish.yaml` from
[portolan-catalog-template](https://github.com/portolan-sdi/portolan-catalog-template)
and publish to both. Source Cooperative passes all five live checks, verified on
2026-08-27, so that copy would carry no accepted deviations.

The catalog metadata does not change. Only the host does.
