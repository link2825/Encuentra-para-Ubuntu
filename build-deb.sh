#!/bin/sh
set -eu
cd "$(dirname "$0")"
mkdir -p dist
stage=$(mktemp -d)
trap 'rm -rf "$stage"' EXIT HUP INT TERM
cp -a packaging/. "$stage/"
chmod 755 "$stage/usr/bin/busca-ai"
find "$stage" -type d -exec chmod 755 {} +
dpkg-deb --root-owner-group --build "$stage" dist/encuentra_0.5.15-1_all.deb
