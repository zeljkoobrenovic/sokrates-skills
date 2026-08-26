---
name: sokrates-people-config
description: Builds and reviews the Sokrates config-people.json that merges contributor identities (several e-mails or user names of the same person) from git commit history - for one repository (_sokrates/config-people.json from git-history.txt) or a whole landscape (_sokrates_landscape/config-people.json across all repositories, where per-repository files with a single e-mail become duplicates once combined). The script applies explicit, confidence-rated rules (same user name, GitHub noreply forms, matching logins, same local part across domains), preserves hand-made entries, and writes config-people-for-review.json listing every merge a human should check plus candidates it did not apply. Use when contributor counts look inflated, the same person appears under several addresses, the user asks to merge or deduplicate contributors, fix bus-factor numbers, or set up people/teams before a landscape.

---

# Sokrates people config (contributor identities)

Every contributor number Sokrates reports — bus factor, knowledge risk, team sizes, "581 authors" — is only as good as identity resolution. Git records whoever configured `user.email` that day: the same person shows up as `alice@corp.com`, `alice@gmail.com`, `12345+alice@users.noreply.github.com` and as "Alice Example" / "alice-oai". Sokrates merges identities through `config-people.json` (`people[].email` = canonical id, `emailPatterns` = the addresses that collapse into it, optional `userName`, `links`, `image`), at repository level (`_sokrates/config-people.json`) and landscape level (`_sokrates_landscape/config-people.json`). Sokrates' own generator (`updatePeopleConfigByUserName`) merges only by identical user name; this skill goes further, says *why* each merge was made, and leaves a review trail instead of silent guesses.

Reference for the file format and the identity pipeline: `../sokrates-landscape-config/references/landscape-reference.md` (section `config-people.json` and "Identity pipeline").

## One skill, two levels

- **Repository**: identities come from `<repo>/git-history.txt` (Sokrates' export; run `sokrates extractGitHistory` in the repo if missing). Output: `<repo>/_sokrates/config-people.json`.
- **Landscape**: identities come from every repository under the root (each repository's `git-history.txt` when the source is present, otherwise the contributors in its `data.zip`), and each repository's own `config-people.json` is imported as trusted evidence. A person with one address in each of three repositories has three identities in the landscape — this is where most duplicates appear. Output: `<root>/_sokrates_landscape/config-people.json`.
- Both runs preserve existing entries (hand edits win) and are safe to re-run.

## Workflow

1. **Build and review** (dry-run first on a landscape you have not seen):
   ```bash
   python3 <this-skill-path>/scripts/build_people_config.py --repo <repo>            [--min-confidence high|medium] [--dry-run]
   python3 <this-skill-path>/scripts/build_people_config.py --landscape <root>       [--min-confidence high|medium] [--dry-run]
   ```
   Rules, each recorded on the merge it caused: **R1** same e-mail (certain); **R2** same user-name key, whitespace-stripped and lower-cased — Sokrates' rule (high; generic names like `admin`, `dev`, `root` are never merged); **R3** GitHub noreply forms `123+login@users.noreply.github.com` ↔ `login@…` (high); **R4** e-mail local part equal to a GitHub login or a user-name key (high); **R5** same local part on different domains (medium); **R6** local part derived from the user name — `first.last`, `flast`, `firstl` (medium); **R7** similar user names, typos/accents (low — listed, never merged). Bots (`[bot]`, `-bot@`, `robot`, github-actions, dependabot, renovate, …) are excluded. Default `--min-confidence high` applies R1–R4; `medium` adds R5/R6 — use it in organisations where one login maps to one person across domains, not for open-source portfolios where `john@` on two domains is often two people.
2. **Read `config-people-for-review.json`** — it is the deliverable for the human, structured to be scanned top-down:
   - `review_first`: merges with a medium-confidence rule, unrelated display names (`Owen Lin` + `Abhinav` joined by a shared address), three or more e-mail domains, or two busy addresses active in the same period (possibly two people sharing a name);
   - `merges`: every merge applied — canonical e-mail, display name, rules fired, and per identity: commits, first/last activity, repositories;
   - `not_applied`: R5/R6 candidates below the threshold and R7 look-alikes — each is one line to add by hand (`\Qemail\E` into a person's `emailPatterns`);
   - `generic_name_collisions`: several addresses sharing `admin`/`dev`/… — deliberately not merged.
   Go through `review_first` in full and spot-check `merges` sorted by commits (a wrong merge of two prolific people distorts more than ten wrong merges of one-commit authors). Reject a merge by splitting the entry into two people in `config-people.json`; accept a candidate by adding its address to the right entry; the tool keeps both on the next run.
3. **Complete the entries that matter**: for the top contributors (the ones every report names), set `userName` to the real display name, add `links` (GitHub profile) and `image` when the landscape uses avatars (`contributorAvatarLinkTemplate` covers GitHub logins automatically). Leave one-commit authors alone.
4. **Verify**: at landscape level run the landscape checker — it re-runs the identity pipeline (ignore → transform → people → bots → teams) and reports canonical contributor counts, merged identities, alias candidates still open, and people entries that match nobody:
   ```bash
   python3 <config-skills-path>/sokrates-landscape-config/scripts/check_landscape.py <root>
   ```
   At repository level compare `contributorsAnalysisResults.contributors` before/after `sokrates generateReports`, or simply the review summary (`identities_seen` → `people_after_merge`).
5. **Report**: the summary numbers (identities → people, merges applied, candidates left), the `review_first` list with your recommendation per item (keep / split / needs the team's knowledge), and the next command (`sokrates generateReports` or `sokrates updateLandscape`).

## Rules of thumb

- Merge only what the evidence supports; the review file exists so that the remaining decisions are made by someone who knows the team. A landscape with 900 unapplied medium candidates is normal — most are different people.
- `transformContributorEmails` in the landscape config (strip `+id`, lower-case, drop domains) runs *before* people matching; systematic normalisations belong there, individual identities here.
- Repository-level files are the safest input for a landscape: merge identities where the history is, then let the landscape import them.
- Sokrates rewrites `config-people.json` on every run (normalised, comments dropped) — keep the reviewed version under version control and diff after runs; the review file is never read by Sokrates and can stay next to it.
- The `--all` flag writes every contributor, not only merged ones — only useful when you want display names/links for people with a single address.
