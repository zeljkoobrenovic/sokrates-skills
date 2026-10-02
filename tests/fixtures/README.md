# Test fixtures

Two small repositories analyzed by a real Sokrates run, plus a landscape over both. Every number the tests
assert on comes from these trees and the scripted git history in `make_fixtures.sh`.

| folder | what it is |
| --- | --- |
| `alpha/` | a Python + JavaScript service: a complex retrying fetch (`fetch_orders`, McCabe 19), a duplicated normalizer (`repo.py` / `legacy.py`, 13 lines), a swallowed exception, env-var settings, SQLite, a `fetch`/WebSocket client, pytest tests, Terraform with a public bucket, a Dockerfile running as root, CODEOWNERS. Inside it: `_sokrates/config.json`, `_sokrates/reports/data/data.zip`, the git exports (`git-history.txt`, `git-commits.txt`, `git-commit-trailers.txt`: six commits by three people and a bot, one AI co-authored) and two hand-written findings files under `_sokrates/reports/ai-insights/` whose evidence cites real lines. |
| `beta/` | a Java library with one unit, analyzed the same way (a second repository for the landscape). |
| `landscape/` | both analyses laid out as `analyzeGitRepo` does (`acme/<repo>/config.json` next to `reports/`) and the `_sokrates_landscape/` that `analyzeLandscape -dataOnly` produced over them. |

Rebuild after a Sokrates change with `SOKRATES_JAR=<cli jar> tests/fixtures/make_fixtures.sh`; the findings files
are not touched by the rebuild (their line numbers follow the sources, which the script does not change).

One rule, pinned by `tests/test_config.py`: Sokrates matches scope patterns against a file's path below the source
root, with a leading `/`, and the configuration scripts mirror that. This folder lives under `tests/`, and
`.*/[Tt]ests/.*` must not claim its files because of that (with Sokrates builds before 2026-10-02, which matched the
whole path as loaded, it did).
