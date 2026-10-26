#!/bin/bash
# Build the tagger image and write ./out/avare_aptdiags.php
set -euo pipefail
cd "$(dirname "$0")"
docker build -t apd-learner-tagger .
mkdir -p out
docker run --rm -v "$PWD/out:/out" apd-learner-tagger
