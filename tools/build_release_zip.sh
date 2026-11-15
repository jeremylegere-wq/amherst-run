#!/bin/bash
# Build the release zip from committed files only (git archive), so the same commit always gives the
# same contents. Files marked export-ignore in .gitattributes are left out.
#
#   tools/build_release_zip.sh 0.1.0 dist      -> dist/amherst-run-v0.1.0.zip + dist/SHA256SUMS.txt
#
# Run from inside the git repository. Needs git, zip tools are not required.
set -euo pipefail

version="${1:?usage: build_release_zip.sh VERSION OUTDIR}"
outdir="${2:?usage: build_release_zip.sh VERSION OUTDIR}"
version="${version#v}"
name="amherst-run-v${version}"

mkdir -p "$outdir"
git archive --format=zip --prefix="${name}/" -o "${outdir}/${name}.zip" HEAD
(cd "$outdir" && sha256sum "${name}.zip" > SHA256SUMS.txt)
echo "built ${outdir}/${name}.zip"
