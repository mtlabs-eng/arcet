#!/usr/bin/env bash
#
# pin.sh — resolve owner/repo@tag para o SHA completo, no formato de pin.
#
#   ./scripts/pin.sh actions/checkout v4.2.2
#   → actions/checkout@a1b2c3...  # v4.2.2
#
#   ./scripts/pin.sh --check .github/workflows/ci.yml
#   → lista as actions do ficheiro que não estão fixadas por SHA
#
# Requer: gh (autenticado) ou curl. jq para o modo --check.

set -uo pipefail

usage() {
  sed -n '3,12p' "$0" | sed 's/^# \{0,1\}//'
  exit "${1:-0}"
}

resolve() {
  local repo="$1" ref="$2" sha=""

  if command -v gh >/dev/null 2>&1; then
    sha=$(gh api "repos/${repo}/commits/${ref}" --jq '.sha' 2>/dev/null)
  fi

  if [[ -z "$sha" ]]; then
    sha=$(curl -sSL --max-time 15 \
            -H "Accept: application/vnd.github+json" \
            ${GITHUB_TOKEN:+-H "Authorization: Bearer ${GITHUB_TOKEN}"} \
            "https://api.github.com/repos/${repo}/commits/${ref}" 2>/dev/null \
          | sed -n 's/.*"sha"[[:space:]]*:[[:space:]]*"\([0-9a-f]\{40\}\)".*/\1/p' \
          | head -1)
  fi

  if [[ -z "$sha" ]]; then
    printf 'erro: não consegui resolver %s@%s\n' "$repo" "$ref" >&2
    printf '      verifica o nome, o tag, e a autenticação (gh auth login)\n' >&2
    return 1
  fi

  # Sanidade: 40 hex e nada mais. Nunca emitir um pin que não seja um SHA.
  if [[ ! "$sha" =~ ^[0-9a-f]{40}$ ]]; then
    printf 'erro: resposta inesperada para %s@%s: %q\n' "$repo" "$ref" "$sha" >&2
    return 1
  fi

  printf '%s@%s  # %s\n' "$repo" "$sha" "$ref"
}

check_file() {
  local f="$1" found=0
  [[ -r "$f" ]] || { printf 'erro: não consigo ler %s\n' "$f" >&2; return 2; }

  while IFS= read -r line; do
    # uses: owner/repo@ref  — ignora actions locais (./) e docker://
    case "$line" in
      *uses:*./*|*uses:*docker://*) continue ;;
    esac
    local ref="${line##*@}"
    ref="${ref%%[[:space:]]*}"
    ref="${ref%%#*}"
    if [[ ! "$ref" =~ ^[0-9a-f]{40}$ ]]; then
      printf '  NÃO FIXADO  %s\n' "$(printf '%s' "$line" | sed 's/^[[:space:]]*//')"
      found=1
    fi
  done < <(grep -n 'uses:[[:space:]]*[^.]' "$f" 2>/dev/null || true)

  if [[ $found -eq 0 ]]; then
    printf '  ok — todas as actions de %s estão fixadas por SHA\n' "$f"
  fi
  return $found
}

[[ $# -eq 0 ]] && usage 1

case "$1" in
  -h|--help) usage 0 ;;
  --check)
    shift
    [[ $# -eq 0 ]] && { printf 'erro: --check precisa de um ficheiro\n' >&2; exit 1; }
    rc=0
    for f in "$@"; do check_file "$f" || rc=1; done
    exit $rc
    ;;
  *)
    [[ $# -ne 2 ]] && usage 1
    resolve "$1" "$2"
    ;;
esac
