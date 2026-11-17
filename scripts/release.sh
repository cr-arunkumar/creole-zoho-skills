#!/bin/sh
# One-command release: bump the version everywhere, test, commit, tag and push. The tag push starts the
# `publish` workflow (npm + GitHub release). Usage: scripts/release.sh 0.2.6 [--dry-run]
set -eu

die() { printf 'error: %s\n' "$*" >&2; exit 1; }
VERSION="${1:-}"; DRY="${2:-}"
case "$VERSION" in [0-9]*.[0-9]*.[0-9]*) ;; *) die "usage: scripts/release.sh X.Y.Z [--dry-run]" ;; esac
cd "$(dirname "$0")/.."

[ "$(git rev-parse --abbrev-ref HEAD)" = "main" ] || die "release from main"
git diff --quiet && git diff --cached --quiet || die "working tree is not clean: commit or stash first"
git rev-parse "v$VERSION" >/dev/null 2>&1 && die "tag v$VERSION already exists"
PY="python3"; [ -x .venv/bin/python ] && PY=".venv/bin/python"

printf 'release v%s: bump package.json, pyproject.toml, .claude-plugin/plugin.json; test; commit; tag; push\n' "$VERSION"
[ "$DRY" = "--dry-run" ] && { echo "dry run: nothing changed"; exit 0; }

VERSION="$VERSION" "$PY" - <<'PYEOF'
import os, re
v = os.environ["VERSION"]
for path, pat in (("package.json", r'("version": ")[^"]+(")'), (".claude-plugin/plugin.json", r'("version": ")[^"]+(")'),
                  ("pyproject.toml", r'(?m)^(version = ")[^"]+(")')):
    s = open(path).read()
    n, count = re.subn(pat, lambda m: m.group(1) + v + m.group(2), s, count=1)
    assert count == 1, path
    open(path, "w").write(n)
PYEOF

"$PY" -m pytest -q tests || { git checkout -- package.json pyproject.toml .claude-plugin/plugin.json; die "tests failed; version bump reverted"; }
git add package.json pyproject.toml .claude-plugin/plugin.json
git commit -q -m "Release $VERSION"
git tag "v$VERSION"
git push origin main "v$VERSION"
echo "pushed v$VERSION — watch: gh run watch -R cr-arunkumar/creole-zoho-skills"
