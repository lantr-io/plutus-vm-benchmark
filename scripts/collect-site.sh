#!/usr/bin/env bash
# Collects the GitHub Pages site into _site/ (run.yml and publish-page.yml, the "pages" job).
#
# Publishes only the page and its assets, not the internal docs (specs, contracts) in docs/.
# Also gives each published run a permalink: results/<name>/index.html at /results/<name>/, with
# its link-preview image results/<name>/og.png.
# The report is self-contained and its copy in results/<name>/ has noindex, so search shows only
# the main page. Partial runs (results/partial-*) were never published and stay out.
set -euo pipefail

mkdir -p _site
cp docs/index.html docs/favicon.svg docs/og.png docs/robots.txt docs/sitemap.xml \
   docs/lantr-logo.png docs/lantr-logo-dark.png _site/

for page in results/*/index.html; do
    name=$(basename "$(dirname "$page")")
    [[ "$name" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}(-[0-9]+)?$ ]] || continue
    mkdir -p "_site/results/$name"
    cp "$page" "_site/results/$name/index.html"
    # The run's link-preview image (its og:image). An old run without one keeps none.
    if [[ -f "results/$name/og.png" ]]; then cp "results/$name/og.png" "_site/results/$name/og.png"; fi
done
