#!/bin/sh
# creole-zoho installer — fetches the repo and starts the onboarding CLI.
#   curl -fsSL https://raw.githubusercontent.com/cr-arunkumar/creole-zoho-skills/main/install.sh | sh
#   curl -fsSL .../install.sh | sh -s -- install --yes --harness claude --global --mcp-url https://...
# Env: CZ_REF (branch/tag, default main) · CZ_HOME (default ~/.creole-zoho-skills) · CZ_BIN (default ~/.local/bin)
#      CZ_NO_RUN=1 (download/update only, don't start the CLI)
set -eu

REPO="cr-arunkumar/creole-zoho-skills"
REF="${CZ_REF:-main}"
HOME_DIR="${CZ_HOME:-$HOME/.creole-zoho-skills}"
BIN_DIR="${CZ_BIN:-$HOME/.local/bin}"
SRC="$HOME_DIR/src"

say() { printf '  %s\n' "$*"; }
die() { printf '  error: %s\n' "$*" >&2; exit 1; }

command -v curl >/dev/null 2>&1 || die "curl is required"
command -v tar  >/dev/null 2>&1 || die "tar is required"
command -v python3 >/dev/null 2>&1 || die "python3 (>= 3.9) is required"
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' || die "python3 >= 3.9 is required"

printf '\n  ◆ creole-zoho · installing (%s@%s)\n' "$REPO" "$REF"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT INT TERM
curl -fsSL "https://github.com/$REPO/archive/$REF.tar.gz" -o "$TMP/src.tar.gz" || die "download failed (check network / CZ_REF)"
mkdir -p "$TMP/x" && tar -xzf "$TMP/src.tar.gz" -C "$TMP/x" || die "could not unpack archive"
EXTRACTED="$(find "$TMP/x" -mindepth 1 -maxdepth 1 -type d | head -n 1)"
[ -f "$EXTRACTED/scripts/cli.py" ] || die "archive does not look like $REPO"

mkdir -p "$HOME_DIR"
rm -rf "$SRC.new" && mv "$EXTRACTED" "$SRC.new"
rm -rf "$SRC" && mv "$SRC.new" "$SRC"

mkdir -p "$BIN_DIR"
cat > "$BIN_DIR/creole-zoho" <<EOF
#!/bin/sh
exec python3 "$SRC/scripts/cli.py" "\$@"
EOF
chmod +x "$BIN_DIR/creole-zoho"
say "installed to $SRC"
say "launcher:   $BIN_DIR/creole-zoho"
case ":$PATH:" in *":$BIN_DIR:"*) ;; *) say "add to PATH:  export PATH=\"$BIN_DIR:\$PATH\"" ;; esac

[ "${CZ_NO_RUN:-0}" = "1" ] && exit 0

# Under `curl | sh` stdin is the script, so give the CLI the real terminal when there is one.
if [ -t 1 ] && [ -r /dev/tty ] && [ ! -t 0 ]; then
  exec "$BIN_DIR/creole-zoho" "$@" < /dev/tty
fi
exec "$BIN_DIR/creole-zoho" "$@"
