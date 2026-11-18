#!/bin/sh
# zoho-skills installer: installs uv (if missing) and the zoho-skills CLI, then starts onboarding.
#   curl -fsSL https://raw.githubusercontent.com/cr-arunkumar/creole-zoho-skills/main/install.sh | sh
#   curl -fsSL .../install.sh | sh -s -- install --yes --harness claude --global --mcp-url https://...
# Env: ZOHO_SKILLS_REF     git ref/tag to install (default: the latest GitHub release; falls back to main)
#      ZOHO_SKILLS_NO_RUN  set to 1 to install only, without starting the CLI
set -eu

REPO="cr-arunkumar/creole-zoho-skills"
REF="${ZOHO_SKILLS_REF:-}"

say() { printf '  %s\n' "$*"; }
die() { printf '  error: %s\n' "$*" >&2; exit 1; }

if ! command -v uv >/dev/null 2>&1; then
  for d in "$HOME/.local/bin" "$HOME/.cargo/bin"; do
    [ -x "$d/uv" ] && PATH="$d:$PATH" && break
  done
fi

if ! command -v uv >/dev/null 2>&1; then
  command -v curl >/dev/null 2>&1 || die "curl is required to install uv"
  say "uv (https://docs.astral.sh/uv/) is required and was not found."
  say "installing it with the official installer: curl -LsSf https://astral.sh/uv/install.sh | sh"
  curl -LsSf https://astral.sh/uv/install.sh | sh || die "uv installation failed"
  for d in "$HOME/.local/bin" "$HOME/.cargo/bin"; do
    [ -x "$d/uv" ] && PATH="$d:$PATH" && break
  done
  command -v uv >/dev/null 2>&1 || die "uv installed but not found on PATH; open a new shell and re-run"
fi

if [ -z "$REF" ] && command -v curl >/dev/null 2>&1; then
  REF="$(curl -fsSL "https://api.github.com/repos/$REPO/releases/latest" 2>/dev/null |
    sed -n 's/.*"tag_name": *"\([^"]*\)".*/\1/p' | head -n 1 || true)"
fi
REF="${REF:-main}"

printf '\n  zoho-skills: installing (%s@%s)\n' "$REPO" "$REF"
# A release tag ships a wheel (no git needed, no npm approval involved); anything else installs from git.
case "$REF" in
  v[0-9]*) WHEEL="https://github.com/$REPO/releases/download/$REF/zoho_skills-${REF#v}-py3-none-any.whl" ;;
  *) WHEEL="" ;;
esac
if [ -n "$WHEEL" ] && uv tool install --force "$WHEEL" >/dev/null 2>&1; then
  :
else
  uv tool install --force "git+https://github.com/$REPO@$REF" || die "install failed (check network / ZOHO_SKILLS_REF)"
fi

BIN_DIR="$(uv tool dir --bin 2>/dev/null || true)"
[ -n "$BIN_DIR" ] && PATH="$BIN_DIR:$PATH"
case ":$PATH:" in *":$HOME/.local/bin:"*) ;; *) PATH="$HOME/.local/bin:$PATH" ;; esac
command -v zoho-skills >/dev/null 2>&1 || die "zoho-skills not found on PATH after install; run 'uv tool update-shell' and open a new shell"
say "installed: $(command -v zoho-skills)"

[ "${ZOHO_SKILLS_NO_RUN:-0}" = "1" ] && exit 0

[ "$#" -gt 0 ] || set -- onboard

# Under `curl | sh` stdin is the script, so give the CLI the real terminal when there is one.
if [ -t 1 ] && [ -r /dev/tty ] && [ ! -t 0 ]; then
  exec zoho-skills "$@" < /dev/tty
fi
exec zoho-skills "$@"
