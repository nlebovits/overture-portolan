# AGENTS.md — Example Catalog

Guidance for AI agents and automated clients working with this catalog.

**One rule survives every edit to this file.** Every claim here is either quoted
from a source or measured from the data. If you cannot point at where a fact
came from, it does not belong in this file. An agent acting on an invented join
key or an invented column name produces a confident wrong answer, and nothing
downstream catches it.

## What this catalog holds

TODO(setup): the collections, and what each one covers. Name the public root
URL so a client that arrived here by another route can orient itself.

## How to read it

TODO(setup): one worked query per format you publish, each one run against the
published files before it was written down.

## Join keys

TODO(setup): the columns that join collections to each other, and their types.
State which side is unique. If no two collections join, say that instead.

## Quirks that produce silently wrong answers

TODO(setup): the traps. A projection that is not WGS84, so lengths come out in
feet. A column whose name differs from the one the source documentation uses. A
category field with inconsistent casing. A geometry column that GDAL names
`geometry_bbox` where the query you copied says `bbox`. These are the entries
that earn this file, so write them as you find them.

## Structure

Assets and structural links resolve relative to the object that carries them.
Catalogs here carry no `self` link, so a client tracks its own location.

## Publication

This catalog is deployed from git by Cloudflare Pages. It uses neither
`portolan push` nor the catalog template's `tools/publish.py`, and it uploads
nothing to an object store. A merge to `main` is a deploy.

`_headers` in this directory is not catalog content. Cloudflare consumes it at
deploy time to set CORS and range headers, and never serves it. Deleting it makes
the published catalog fail PTL-LIV-003, PTL-LIV-004, and PTL-LIV-005 while the
repository still looks healthy. See [docs/publication.md](https://github.com/nlebovits/overture-portolan/blob/main/docs/publication.md)
for why this catalog publishes the way it does.

Every `data` and `visual` asset href points at Overture's own buckets rather than
at this host. Those buckets answer range requests and permit cross-origin reads,
so a client reads them directly. This catalog holds metadata only.
