#!/usr/bin/env bash
# Rebuilds the analysis fixtures with a real Sokrates run. tests/fixtures/alpha and beta are the source trees;
# the analysis outputs (_sokrates/, git-*.txt) live inside them, exactly as in a repository a user analyzes.
#
#   SOKRATES_JAR=/path/to/cli-1.0-jar-with-dependencies.jar tests/fixtures/make_fixtures.sh
#
# For each source tree (alpha: Python + JavaScript service, beta: Java library) it replays a scripted git
# history with fixed authors and dates, runs extractGitHistory + init + generateReports, and keeps only what
# the scripts read: the git exports, _sokrates/config.json and reports/data/data.zip. Then it lays both
# analyses out the way analyzeGitRepo does (config.json next to reports/) under landscape/acme/ and runs
# analyzeLandscape -dataOnly on it. Everything the tests assert on is derived from the sources and this
# script, so a rebuild with a newer Sokrates should only change what Sokrates itself changed.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
JAR="${SOKRATES_JAR:?set SOKRATES_JAR to the Sokrates CLI jar}"
WORK="$(mktemp -d -t sokrates-fixtures)"
trap 'rm -rf "$WORK"' EXIT

commit() {   # commit <name> <email> <date> <message> [files...]
  local name="$1" email="$2" date="$3" message="$4"; shift 4
  git add -A -- "$@"
  GIT_AUTHOR_NAME="$name" GIT_AUTHOR_EMAIL="$email" GIT_AUTHOR_DATE="$date" \
  GIT_COMMITTER_NAME="$name" GIT_COMMITTER_EMAIL="$email" GIT_COMMITTER_DATE="$date" \
    git commit -q --no-gpg-sign -m "$message"
}

build_alpha() {
  local repo="$WORK/alpha"; mkdir -p "$repo"; cd "$repo"; git init -q -b main
  local src="$HERE/alpha"
  # 1. skeleton: the first version of the service is just the settings loader
  cp "$src/README.md" "$src/requirements.txt" .; mkdir -p src/app; cp "$src/src/app/__init__.py" src/app/
  head -20 "$src/src/app/service.py" > src/app/service.py
  commit "Ada Lovelace" "ada@example.com" "2024-03-01T10:00:00+00:00" "Initial service skeleton" .
  # 2. persistence, plus a cache module that will be deleted later (a file death for the evolution timeline)
  cp "$src/src/app/repo.py" src/app/; mkdir -p tests; cp "$src/tests/test_repo.py" tests/; cp "$src/pyproject.toml" .
  printf '"""In-memory cache, replaced by the disk cache."""\nCACHE = {}\n\n\ndef get(key):\n    return CACHE.get(key)\n' > src/app/old_cache.py
  commit "Grace Hopper" "grace@example.com" "2024-06-15T09:30:00+00:00" "Add sqlite repository and tests" .
  # 3. web client, CI and image — Ada under her GitHub noreply address
  mkdir -p web .github/workflows; cp "$src/web/client.js" web/; cp "$src/.github/workflows/ci.yml" .github/workflows/; cp "$src/Dockerfile" .
  commit "Ada Lovelace" "12345+ada@users.noreply.github.com" "2024-09-10T15:45:00+00:00" "Add web client, CI and Docker image" .
  # 4. the retrying fetch (the complex unit), the legacy copy of the normalizer, the cache module removed
  cp "$src/src/app/service.py" "$src/src/app/legacy.py" src/app/; cp "$src/tests/test_service.py" tests/; git rm -q src/app/old_cache.py
  commit "Ada Lovelace" "ada@example.com" "2025-01-20T11:15:00+00:00" "Retry the orders fetch, keep the legacy CSV export" .
  # 5. a bot commit
  printf 'requests==2.32.3\n' > requirements.txt; sed -i.bak 's/2.32.3/2.32.4/' requirements.txt && rm requirements.txt.bak
  commit "dependabot[bot]" "49699333+dependabot[bot]@users.noreply.github.com" "2025-04-05T06:00:00+00:00" "Bump requests from 2.32.3 to 2.32.4" .
  # 6. infrastructure and docs, AI co-authored
  mkdir -p infra docs; cp "$src/infra/main.tf" infra/; cp "$src/docs/architecture.md" docs/; cp "$src/CODEOWNERS" .
  git add -A .; GIT_AUTHOR_NAME="Grace Hopper" GIT_AUTHOR_EMAIL="grace@example.com" GIT_AUTHOR_DATE="2025-07-12T14:20:00+00:00" \
    GIT_COMMITTER_NAME="Grace Hopper" GIT_COMMITTER_EMAIL="grace@example.com" GIT_COMMITTER_DATE="2025-07-12T14:20:00+00:00" \
    git commit -q --no-gpg-sign -m "Terraform for the cache bucket, architecture notes

Co-Authored-By: Claude <noreply@anthropic.com>"
  # 7. the pinned requirements line back to the fixture's content (so the tree equals sources/alpha)
  cp "$src/requirements.txt" .
  commit "Ada Lovelace" "ada@example.com" "2025-08-02T08:00:00+00:00" "Pin requests to the version the tests run with" .
  diff -r --exclude=.git --exclude=_sokrates --exclude='git-*.txt' "$src" "$repo" > /dev/null || { echo "the replayed alpha tree differs from fixtures/alpha"; exit 1; }
}

build_beta() {
  local repo="$WORK/beta"; mkdir -p "$repo"; cd "$repo"; git init -q -b main
  local src="$HERE/beta"
  cp "$src/README.md" "$src/pom.xml" .; mkdir -p src/main/java/acme/beta; cp "$src/src/main/java/acme/beta/Calculator.java" src/main/java/acme/beta/
  commit "Grace Hopper" "grace@example.com" "2024-11-03T10:00:00+00:00" "Calculator" .
  cp "$src/src/main/java/acme/beta/Parser.java" src/main/java/acme/beta/; mkdir -p src/test/java/acme/beta; cp "$src/src/test/java/acme/beta/CalculatorTest.java" src/test/java/acme/beta/
  commit "Ada Lovelace" "12345+ada@users.noreply.github.com" "2025-02-14T12:00:00+00:00" "Parser and a first test" .
}

analyze() {   # analyze <name>
  local repo="$WORK/$1" out="$HERE/$1"
  cd "$repo"
  java -jar "$JAR" extractGitHistory -analysisRoot . > "$WORK/$1-history.log" 2>&1
  java -jar "$JAR" init -srcRoot . -confFile _sokrates/config.json > "$WORK/$1-init.log" 2>&1
  java -jar "$JAR" generateReports -confFile _sokrates/config.json -outputFolder _sokrates/reports -dataOnly > "$WORK/$1-reports.log" 2>&1
  rm -rf "$out/_sokrates" "$out"/git-*.txt; mkdir -p "$out/_sokrates/reports/data"
  cp git-history.txt git-commits.txt git-commit-trailers.txt "$out/" 2>/dev/null || true
  cp _sokrates/config.json "$out/_sokrates/"
  cp _sokrates/reports/data/data.zip "$out/_sokrates/reports/data/"
}

build_landscape() {
  local root="$WORK/landscape"; mkdir -p "$root/acme/alpha/reports/data" "$root/acme/beta/reports/data"
  for r in alpha beta; do cp "$HERE/$r/_sokrates/config.json" "$root/acme/$r/"; cp "$HERE/$r/_sokrates/reports/data/data.zip" "$root/acme/$r/reports/data/"; done
  cd "$root"; java -jar "$JAR" analyzeLandscape -analysisRoot . -dataOnly > "$WORK/landscape.log" 2>&1
  local out="$HERE/landscape"; rm -rf "$out"; mkdir -p "$out/_sokrates_landscape/data"
  cp -R "$root/acme" "$out/"
  cp _sokrates_landscape/config.json "$out/_sokrates_landscape/"
  cp _sokrates_landscape/data/data.zip "$out/_sokrates_landscape/data/"
}

build_alpha; build_beta; analyze alpha; analyze beta; build_landscape
cd "$HERE" && du -sh alpha beta landscape && find alpha beta landscape -type f | sort
