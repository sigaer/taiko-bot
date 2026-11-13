#!/usr/bin/env bash
# Offline verification only. Every workload owns the standard bounded QA scope.
set -euo pipefail
repo="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../../.." && pwd)"
cd "$repo"
fixture="${1:?Usage: verify.sh FIXTURE OUTPUT_DIRECTORY}"
output="${2:?Usage: verify.sh FIXTURE OUTPUT_DIRECTORY}"
runner=/home/sigaer/taiko/taiko-forum/scripts/memory/run_qa.sh
python=/opt/taiko-bot/releases/0.23.0/bin/python
baseline=/opt/taiko-bot/releases/0.23.0/lib/python3.11/site-packages
core="$repo/packages/sakura-taiko-core/core"
run="$repo/scripts/performance/song_query/run.py"
mkdir -p "$output"

bash "$runner" "$python" "$run" tests --fixture "$fixture" \
  --keyword 'not client and not what_song_command' \
  --tests tests/test_song_search.py tests/test_song_phonetics.py tests/test_song_catalog_snapshot.py
bash "$runner" "$python" "$run" tests --fixture "$fixture" --core-source "$core" \
  --tests tests/test_song_search.py tests/test_song_phonetics.py tests/test_song_visibility.py tests/test_song_catalog_snapshot.py

for role in center client; do
  core_options=()
  if [[ "$role" == client ]]; then core_options=(--core-source "$core"); fi
  bash "$runner" "$python" "$run" benchmark --fixture "$fixture" --profile "$role" \
    --output "$output/after-$role.json" --repetitions 40 "${core_options[@]}"
  for state in before after; do
    source="$repo"
    if [[ "$state" == before ]]; then source="$baseline"; fi
    bash "$runner" "$python" "$run" benchmark --source "$source" --fixture "$fixture" --profile "$role" \
      --output "$output/$state-partial-$role.json" --partial-only --repetitions 40 "${core_options[@]}"
    bash "$runner" "$python" "$run" allocation --source "$source" --fixture "$fixture" --profile "$role" \
      --output "$output/$state-allocation-$role.json" "${core_options[@]}"
    bash "$runner" "$python" "$run" trace --source "$source" --fixture "$fixture" --profile "$role" \
      --output "$output/$state-trace-$role.json" "${core_options[@]}"
  done
done
