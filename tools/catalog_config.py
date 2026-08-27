"""Where the published catalog lives.

The catalog template kept this in `catalog.publish.yaml`, because its publisher
needed a bucket URI and a public base URL alongside it. This catalog deploys from
git rather than uploading, so the only thing left of that configuration is the
directory Cloudflare Pages serves as the site root.

That directory is set in two places and they must agree: here, and the "Build
output directory" field in the Cloudflare Pages project. Changing one without the
other publishes the wrong tree or nothing at all.

See docs/publication.md for why this catalog carries no uploader.
"""

from __future__ import annotations

PUBLISH_DIR = "catalog"


def load_config() -> dict[str, str]:
    """The subset of the template's config that a git-deployed catalog still has.

    Kept as a function returning a mapping so the gates in `tests/` read the same
    way they do in the upstream template, which makes template changes easy to
    merge back in.
    """
    return {"publish_dir": PUBLISH_DIR}
