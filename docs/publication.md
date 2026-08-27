# Publication

This catalog is deployed from git by Cloudflare Pages. It uploads nothing to an
object store, and it carries neither of the two publishers the Portolan tooling
ships. That is a deliberate departure, and this page records why.

## How it works

Cloudflare Pages watches `main` and serves `catalog/` as the site root. A merge
is a deploy. There is no build step, no upload command, and no credential in CI.

Response headers come from `catalog/_headers`, which Cloudflare consumes at deploy
time and never serves. That file is load-bearing: it is what satisfies Portolan's
Data Storage requirements, and deleting it breaks the published catalog while
leaving the repository looking healthy.

## Why not a bucket

Portolan offers two bucket publishers. `portolan push` tracks what it has uploaded
in `versions.json`, keyed on sha256. The catalog template's `tools/publish.py` is
stateless and diffs local size and MD5 against a remote listing.

Both share a property their own documentation states plainly: publishing never
deletes. Removing a file from the catalog does not remove the object from the
bucket.

For most catalogs that is a footnote. For this one it is a defect, because of what
the upstream does.

This catalog mirrors Overture Maps, which ships a release every month. Overture's
parquet part filenames carry UUIDs, so **every href changes on every release**,
even when the schema and the row counts do not. Publishing to a bucket would
therefore leave a complete copy of the previous catalog live at its old URLs after
each sync, twelve times a year. Closing that gap needs a purpose-built prune tool,
and a prune tool that guesses wrong deletes a live catalog.

A git-deployed host removes the problem instead of managing it. The deployed state
is the repository state, so an object that leaves the tree leaves the site. No
sync, no orphans, no prune tool, and no long-lived storage credential anywhere in
the pipeline.

## Why Cloudflare Pages and not GitHub Pages

GitHub Pages was the obvious candidate, since the repository already lives there.
It fails, and the failure is not fixable.

Portolan requires a host to answer range requests and to permit cross-origin reads,
so browser clients can read the data directly. `rashid` checks this in its live
pass. Measured against GitHub Pages on 2026-08-27:

| Check | Requirement | GitHub Pages |
|---|---|---|
| PTL-LIV-001, PTL-LIV-002 | `Range` answered with 206 | passes |
| PTL-LIV-003 | `Access-Control-Allow-Origin` | passes, sends `*` |
| PTL-LIV-004 | `Access-Control-Expose-Headers` | fails, sends none |
| PTL-LIV-005 | OPTIONS preflight | fails, returns 405 |

Both failures are errors rather than warnings, and GitHub Pages exposes no header
configuration, so neither can be fixed from the repository.

One carve-out exists in the spec and does not apply here. PORTO-CORE-073 forbids a
validator from holding *upstream* servers to these requirements, which is what lets
this catalog point at Overture's buckets without inheriting their header gaps. It
says nothing about the host serving the catalog's own metadata. That host is
exactly what the live pass exists to probe.

Cloudflare Pages supports a `_headers` file that sets arbitrary response headers,
which covers both gaps while keeping every property that made the git-deploy model
attractive.

## What this implies for the Portolan spec

Worth raising upstream, now that it is proven in practice.

Portolan's Data Storage section is written for an object store. It describes a
CORS policy and a bucket, and the tooling follows: two publishers, both of which
upload, neither of which deletes. A git-deployed static host is a legitimate
publication target that meets the same requirements by a different mechanism, and
the spec currently has no vocabulary for it.

Two additions would help the next publisher:

1. Say that a static host configured by a committed file, such as `_headers`,
   satisfies PORTO-CORE-043 through PORTO-CORE-045 the same way a bucket CORS
   policy does. The requirement is about what the server sends, not about how the
   publisher configured it.
2. Name the never-deletes property of bucket publication as a hazard for any
   mirror on a release cadence, and offer git-deploy as the alternative. The
   hazard is invisible until the second sync, and by then the orphans are live.

## Reversing this

Nothing here is one-way. If a Source Cooperative copy is wanted later, for the
discoverability that source.coop offers and a `pages.dev` domain does not, restore
`tools/publish.py` and `catalog.publish.yaml` from
[portolan-catalog-template](https://github.com/portolan-sdi/portolan-catalog-template)
and run both targets. The catalog metadata does not change; only the host does.
