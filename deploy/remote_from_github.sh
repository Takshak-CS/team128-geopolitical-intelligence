#!/usr/bin/env bash
# Runs on the server; scripts/deploy.ps1 -FromGitHub uploads it and calls it.
#
#   bash ~/team128-upload/remote_from_github.sh <owner/repo> <commit> <site-address> [login|public]
#
# Downloads that commit of the repository straight from GitHub, makes it the code
# bundle, and starts remote_setup.sh from it in the background, so a dropped SSH
# session cannot stop the build. Nothing large travels from the laptop: the server
# fetches the code over AWS's network. Progress is in ~/team128-upload/setup.log,
# which ends with SETUP_EXIT=<code>.
#
# The repository must be public (GitHub serves the archive without a login).
set -euo pipefail
REPO="$1"
COMMIT="$2"
SITE="$3"
ACCESS="${4:-login}"
UP="$HOME/team128-upload"
SRC="$UP/github-src"

mkdir -p "$UP"
rm -rf "$SRC"
mkdir -p "$SRC"
curl -fsSL "https://codeload.github.com/${REPO}/tar.gz/${COMMIT}" | tar -xz -C "$SRC" --strip-components=1
tar -czf "$UP/code.tar.gz" -C "$SRC" .
cp "$SRC/deploy/remote_setup.sh" "$UP/remote_setup.sh"
echo "$COMMIT" > "$UP/deployed_commit"

nohup bash -c "bash '$UP/remote_setup.sh' '$SITE' '$ACCESS'; echo SETUP_EXIT=\$?" > "$UP/setup.log" 2>&1 < /dev/null &
echo "building ${REPO} at ${COMMIT:0:7} in the background"
