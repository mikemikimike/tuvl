#!/usr/bin/env bash
# Fail unless PyPI serves a provenance (PEP 740 attestation) for every distribution just published:
#
#     scripts/check_provenance.sh dist/*.whl dist/*.tar.gz
#
# PyPI cannot attach an attestation to a file after the upload, so this is the only point where a release
# that lost its provenance can still be noticed (b4 to b8 lost theirs without anyone seeing it).
set -uo pipefail

ATTEMPTS="${PROVENANCE_ATTEMPTS:-12}"
WAIT="${PROVENANCE_WAIT:-10}"

# tuvl_insight-2.0.0b8-py3-none-any.whl or tuvl-2.0.0b8.tar.gz -> "tuvl-insight 2.0.0b8"
project_and_version() {
  local stem="${1%.whl}"
  stem="${stem%.tar.gz}"
  local name="${stem%%-*}" rest="${stem#*-}"
  echo "${name//_/-} ${rest%%-*}"
}

has_provenance() {
  local file="$1" project version code
  read -r project version <<<"$(project_and_version "$file")"
  code=$(curl -sS -o /dev/null -w '%{http_code}' --max-time 30 \
    "https://pypi.org/integrity/${project}/${version}/${file}/provenance") || return 2
  [ "$code" = 200 ]
}

pending=()
for path in "$@"; do
  case "$path" in *.attestation) continue ;; esac
  pending+=("$(basename "$path")")
done
if [ "${#pending[@]}" -eq 0 ]; then
  echo "::error::no distributions to check"
  exit 1
fi

for attempt in $(seq 1 "$ATTEMPTS"); do
  still=()
  for file in "${pending[@]}"; do
    has_provenance "$file" || still+=("$file")
  done
  if [ "${#still[@]}" -eq 0 ]; then
    echo "PyPI serves a provenance for every file"
    exit 0
  fi
  pending=("${still[@]}")
  [ "$attempt" -lt "$ATTEMPTS" ] && sleep "$WAIT"
done

for file in "${pending[@]}"; do
  echo "::error::PyPI has no provenance for ${file}"
done
exit 1
