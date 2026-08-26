# `_sokrates/config.json` — field reference

Read from the Sokrates source (`codeanalyzer/src/main/java/nl/obren/sokrates/sourcecode/...`), not from the docs; where `docs/configuration.md` disagrees with the code, the code is cited. JSON keys equal the Java field names (plain Jackson, camelCase); unknown keys are silently ignored on load; a generated config is always fully expanded and any omitted key falls back to the Java default.

## Top level (`core/CodeConfiguration.java:26-71`)

| key | type | default | meaning |
|---|---|---|---|
| `metadata` | Metadata | `{}` | name, description, tooltip, logoLink, links[{label,href}]. **`metadata.name` is the repository's identity in a landscape.** |
| `summary` | string[] | `[]` | key findings shown as bullets in the report |
| `srcRoot` | string | `".."` | source root relative to the config file (see resolution) |
| `extensions` | string[] | `[]` (init fills) | only these extensions are analysed; everything else is dropped before any other rule |
| `ignore` | SourceFileFilter[] | `[]` | files dropped before scope classification (`exception` is *not* honoured here) |
| `main` / `test` / `generated` / `buildAndDeployment` / `other` | NamedSourceCodeAspect | main = `{".*"}` | the five scopes; `main` starts as everything |
| `logicalDecompositions` | LogicalDecomposition[] | one `"primary"` | component groupings + dependency analysis; empty list is replaced by the default |
| `concernGroups` (alias `concerns`) | ConcernsGroup[] | one `"general"` with `TODOs` | cross-cutting file classifications, matched against **main only** |
| `goalsAndControls` | MetricsWithGoal[] | one default goal | metric goals with desired ranges |
| `fileHistoryAnalysis` | FileHistoryAnalysisConfig | see below | git-history / contributor settings |
| `analysis` | AnalysisConfig | see below | switches, limits, risk thresholds |
| `tagRules` | TagRule[] | 24 defaults (init only) | tag the repository by file paths (jenkins, maven, react, …) |

Keys that **do not exist** (docs mention some): `trendAnalysis`, `compareResultsWith`, `excludeFiles`, `maxFileSize` (it's `analysis.maxFileSizeBytes`), `skipFileHistoryAnalysis`, top-level `thresholds`, `unitAnalysis`. `cacheSourceFiles` is a read-only alias of `analysis.saveSourceFiles` and is never written back.

**`srcRoot` resolution** (`CodeConfiguration.java:114-128`): if it starts with `..`, resolve `srcRoot[2:]` against the config file's grandparent (so the default `..` with `<repo>/_sokrates/config.json` → `<repo>`); otherwise against the config file's folder; if the result doesn't exist the literal string is used.

## SourceFileFilter (`SourceFileFilter.java:17-33`)

`{ "pathPattern": "", "contentPattern": "", "exception": false, "note": "" }`

- `pathPattern` — Java regex that must match the **entire** path (anchored). The path tested is the file's path *as loaded, including the srcRoot prefix* — so patterns almost always start with `.*`. Separator-agnostic (`/` and `\` variants are tried). Blank = matches everything.
- `contentPattern` — Java regex that must match an **entire line**, for at least one line. To find a substring write `.*TODO.*`. Blank = no content constraint. (`maxLinesForContentSearch` exists in code but is `@JsonIgnore` — not settable via JSON.)
- A filter matches when path matches AND (content blank OR content matches).
- **A malformed regex is swallowed and matches nothing** — no error, the rule is silently dead. Always compile-check patterns.
- `exception: true` = veto. In scopes/components (`SourceCodeFiles.getSourceFiles`) order does not matter: any matching exception filter excludes the file regardless of position. (In `LogicalDecomposition.getSourceFiles` filters apply sequentially — a later inclusive match can re-include; in `AnalyzerOverride` an exception match breaks immediately.)
- `note` is documentary only.

## Broad scope and `ignore` (`SourceCodeFiles.java:107-185`)

Order per file: (1) extension not in `extensions` → dropped; (2) size > `analysis.maxFileSizeBytes`; (3) lines > `analysis.maxLines`; (4) any line longer than `analysis.maxLineLength`; (5) any `ignore` filter matches. Excluded files are listed in the report grouped by reason.

## Scopes and precedence (`CodeConfiguration.java:202-218`)

Each scope is populated independently, then subtracted: `main -= test, generated, buildAndDeployment, other`; `buildAndDeployment -= other, generated, test`; `test -= other, generated`. Effective winner order: **generated > other > test > buildAndDeployment > main** (a file can end up in both `generated` and `other`). A decomposition's `scope` string is lower-cased and mapped to `main|test|generated|buildanddeployment|other`; anything else → main.

NamedSourceCodeAspect: `{ "name", "sourceFileFilters": [...], "files": ["relative/path", ...] }` — `files` lists explicit relative paths included unconditionally (still subject to exception filters).

## LogicalDecomposition (`aspects/LogicalDecomposition.java:23-77`)

| key | default | meaning |
|---|---|---|
| `name` | `""` (`"primary"`) | |
| `scope` | `"main"` | which scope supplies the files |
| `filters` | `[]` | narrow the scope; empty = all |
| `componentsFolderDepth` | `1` | auto-components from the first N path segments of the relative path; `0` disables folder components |
| `minComponentsCount` | `0` | if >0, raise the depth (up to 20) until at least this many components exist — never lowers it |
| `components` | `[]` | explicit components (NamedSourceCodeAspect); folder-based ones are *added* to this list |
| `metaComponents` | `[]` | MetaRule[] deriving component names from path/content |
| `groups` | `[]` | GroupingRule `{name, pattern}` — regex on component *names* for diagram grouping |
| `includeRemainingFiles` | `true` | with `filters`: keep unfiltered files as `Unclassified` (true) or drop them (false) |
| `dependenciesFinder` | `{useBuiltInDependencyFinders:true, rules:[], metaRules:[]}` | rules: `{component, pathPattern, contentPattern, reverseDirection, color}` (component = *target*); metaRules = MetaRule + reverseDirection/color |
| `renderingOptions` | `{orientation:"TB", maxNumberOfDependencies:100, renderComponentsWithoutDependencies:true, renderIndirectDependencies:false, renderInternalIndirectDependencies:false, reverseDirection:false}` | |
| `includeExternalComponents` | `true` | |
| `dependencyLinkThreshold` / `duplicationLinkThreshold` / `temporalLinkThreshold` | `1` / `50` / `1` | minimum counts to draw an edge |
| `maxSearchDepthLines` | `200` | only the first N lines are scanned for dependencies |

Folder-based components (`SourceCodeAspectUtils.java:43-118`): take the first N segments of the relative path; root files → `ROOT`; the greatest common prefix of all derived paths is stripped (so `src/` alone doesn't become the single component); each component gets an inclusive filter `<srcRoot>/<path>/.*` plus `exception` filters for nested sibling components, keeping them disjoint. Assembly: folder components + explicit components → populate → metaComponents → `Unclassified` / `Multiple Classifications` pseudo-components → empty components removed.

MetaRule: `{ "pathPattern": "", "contentPattern": "", "use": "content"|"path", "ignoreComments": false, "nameOperations": [{"op": "extract|remove|replace|trim|uppercase|lowercase|append|prepend", "params": [...]}] }`. The input to `nameOperations` is the matched **line** (`use: content`) or the relative path (`use: path`). Operation semantics (`operations/impl/*Operation.java`): `extract` [regex] keeps the **whole first match** of the regex (`Matcher.find()`, not a capture group; no match → empty name → file not classified); `remove` [regex] deletes all matches; `replace` [regex, replacement]; `trim`; `lowercase`/`uppercase`; `append`/`prepend` [text]. Operations apply in order — so "the value of target_os" is `extract 'target_os = "[a-z]+"'` → `replace 'target_os = "' ''` → `replace '"' ''`. Note MetaRules match the **relative** path. Unique classification for components (a file lands in one), non-unique for concerns.

## Concerns (`aspects/ConcernsGroup.java`, `Concern.java`)

`concernGroups: [{ "name", "concerns": [Concern], "metaConcerns": [MetaRule] }]`; Concern = NamedSourceCodeAspect + `textOperations`. Evaluated against `main` files only; `Unclassified`/`Multiple Classifications` appended; pairwise overlap concerns only when `analysis.analyzeConcernOverlaps` is true. Default: group `general`, concern `TODOs` with `contentPattern ".*(TODO|FIXME)( |:|\t).*"`.

## Goals and controls (`metrics/MetricsWithGoal.java`, `MetricRangeControl.java`, `aspects/Range.java`)

`goalsAndControls: [{ "goal", "description", "controls": [{ "metric": "<METRIC_ID>", "description", "desiredRange": { "min": "0", "max": "200000", "tolerance": "20000" } }] }]` — range values are **strings**; blank min/max = unbounded; tolerance widens the band. Default goal "Keep the system simple and easy to change": `LINES_OF_CODE_MAIN` 0–200000 ±20000, `DUPLICATION_PERCENTAGE` 0–5 ±1, `VERY_HIGH_RISK_FILE_SIZE_COUNT` 0–0 ±1, `CONDITIONAL_COMPLEXITY_VERY_HIGH_RISK_COUNT` 0–0 ±1.

## fileHistoryAnalysis (`analysis/FileHistoryAnalysisConfig.java:27-48`)

| key | default | meaning |
|---|---|---|
| `importPath` | `"../git-history.txt"` | resolved relative to the `_sokrates` folder; history analysis is skipped when the file is missing/empty (there is no skip flag) |
| `ignoreContributors` | `[]` | regexes; matching contributors dropped |
| `bots` | `[".*\\[bot\\].*", ".*[-]bot[@].*"]` | regexes identifying bots |
| `anonymizeContributors` | `false` | `Contributor 1, 2, …` |
| `transformContributorEmails` | `[]` | OperationStatement pipeline normalising ids (e.g. strip domain) |

People/aliases live in a separate `_sokrates/config-people.json` (`emailPatterns` → canonical email/name), generated by `updatePeopleConfigByUserName`.

## analysis (`core/AnalysisConfig.java:13-78`)

| key | default | meaning |
|---|---|---|
| `skipDuplication` / `skipCorrelations` / `skipDependencies` | `false` | switch analyses off (dependencies also disables static dependency analysis) |
| `saveSourceFiles` / `saveCodeFragments` | `true` | copies for report links (turn off for huge repos or when source must not be copied) |
| `maxFileSizeBytes` / `maxLines` / `maxLineLength` | `1000000` / `10000` / `1000` | files beyond these are excluded (listed with a reason) |
| `maxTemporalDependenciesDepthDays` | `365` | window for changed-together analysis |
| `locDuplicationThreshold` | `10000000` | skip duplication above this main LOC |
| `minDuplicationBlockLoc` | `6` | |
| `maxTopListSize` | `50` | |
| `analyzerOverrides` | `[]` | `[{ "analyzer": "<extension key: tsql|plsql|java|…>", "filters": [SourceFileFilter] }]` — e.g. route `.sql` files to T-SQL; an unknown key silently degrades to the generic analyzer |
| `fileSizeThresholds` | 100/200/500/1000 | `{low, medium, high, veryHigh}`; getters repair non-monotonic values |
| `fileAgeThresholds` | 30/90/180/365 | days |
| `fileUpdateFrequencyThresholds` | 5/20/50/100 | |
| `fileContributorsCountThresholds` | 1/5/10/25 | |
| `unitSizeThresholds` | 10/20/50/100 | |
| `conditionalComplexityThresholds` | 5/10/25/50 | per unit |
| `fileConditionalComplexityThresholds` | 5/10/25/50 | (code initialises it with the unit default; the 50/100/250/500 helper is unused) |
| `commitFilesCountThresholds` | 5/20/50/100 | |
| `customHtmlReportHeaderFragment` | `""` | raw HTML into report `<head>` |
| `analyzeConcernOverlaps` | `false` | |

## tagRules (`core/TagRule.java`)

`[{ "tag", "color", "pathPatterns": [regex...], "excludePathPatterns": [regex...] }]` — the repository gets the tag if at least one file matches any pattern (entire path), excluding paths matching `excludePathPatterns`. Defaults (`landscape/DefaultTags.java`): CI/CD (jenkins `(|.*/)Jenkinsfile`, travis, github actions `(|.*/)[.]github[/]workflows[/].*`, circleci, gitlab), build tools (maven `(|.*/)pom[.]xml`, pnpm, npm `(|.*/)package[.]json`, yarn, jest, babel, gradle, sbt, bazel, pip, nuget, aws codebuild, renovate, dependabot, gemfile, podfile, make, docker `(|.*/)Dockerfile`, helm), tech (react `.*[.]tsx`/`.*[.]jsx`, android, vue).

## Built-in scoping conventions (`scoping/ScopingConventions.java`)

Hundreds of linguist-derived rules for test / generated / build-and-deployment / other / ignore. **They are applied only by `init`, and only rules that match at least one existing file are written into `config.json`** (`ConventionUtils.addConventions`). At analysis time only what is in the file counts — so a repo that later adds e.g. Jest snapshots gains no rule for them until the config is edited. Representative rules:

- test: `.*/[Tt]ests?/.*`, `.*[.][Tt]ests?[.].*`, `.*_tests?[.].*`, `.*/test_.*`, `.*__tests__.*`, `.*[.]spec[.](ts|tsx|js)`, `.*/e2e/.*`, `.*[.]snap`, `.*/[Mm]ocks/.*`, `.*/test[-]data/.*`, `.*/IntegrationTests?/.*`, `.*/src/androidTest/.*`
- generated: `.*/generated/.*`, `.*/__generated__/.*`, `.*/package[-]lock[.]json`, `.*[.]designer[.](cs|vb)`, `.*/zz_generated[.].*[.]go`, `.*/Pods/.*`; content rules like `//[ ]*Generated by .*`, `.*Generated by the protocol buffer compiler[.][ ]+DO NOT EDIT[!].*`, `[/][/][ ]*<auto[-]?generated.*`, `.*GENERATED CODE.*DO NOT MODIFY.*`
- build and deployment: `(.*/)?[.](idea|vscode|vs|gradle|mvn|settings|metadata|circleci)/.*`, `.*/pom[.]xml`, `.*[.]gradle`, `.*[.]sh`, `.*[.]bat`, `.*/package[.]json`, `.*/Dockerfile`, `.*/docker[-]compose[.](yaml|yml)`, `.*/[.]github/workflows/.*[.]ya?ml`, `.*/[.]gitlab[-]ci[.]yml`, `.*[.]tf`, `.*/Chart[.]ya?ml`, `.*/CMakeLists[.]txt`, `.*/BUILD[.]bazel`, `.*/Cargo[.]toml`, `.*/go[.]mod`, `.*/pyproject[.]toml`, `.*/requirements[a-zA-Z0-9._-]*[.]txt`, `.*[.]csproj`, `.*[.]sln`, lock files (`yarn[.]lock`, `Cargo[.]lock`, `go[.]sum`, …), dotfiles (`(.*/)?[.]eslintrc([.].*)?`, `(.*/)?[.]prettierrc([.].*)?`, `(.*/)?[.]gitignore`, …)
- other: markdown/asciidoc/rst, `.*[.]json`, `.*[.]svg`, `.*[.]properties`, `.*[.]txt`, `.*[.]ini`, `.*[.]lock`, README/LICENSE/CHANGELOG families, `.*/[Dd]ocumentation/.*`, `.*/[Ee]xamples/.*`, `.*/[Ss]amples/.*`, `.*/[Dd]emos?/.*`, `.*/vendor/.*`, `.*/site[-]packages/.*`
- ignore: `(.*/)?[.](git|svn|hg|bzr)/.*` (fixed list — not "any dotted folder"), `(.*/)?[.]env([.].*)?` (secrets), `.*/node_modules/.*`, `.*/target/.*`, `.*/bin/.*`, `.*/dist/.*`, `.*/[Vv]endors?/.*`, `.*/extern(al)?/.*`, `.*/(3rd|[Tt]hird)[-_]?[Pp]arty/.*`, `.*/deps/.*`, `.*/docs/.*`, `.*[.]min[.]js`, `.*\.d\.ts`, bundled libraries (jquery, bootstrap, d3, CodeMirror, MathJax, …), `.*/_sokrates/.*`, `.*/_sokrates_landscape/.*`, `.*/git[-][a-zA-Z0-9_]+[.]txt`, `.*/gradlew`, `.*/mvnw`, `.*/Thumbs[.]db`, `.*/__MACOSX/.*`

Note `.*/package[-]lock[.]json` is in both build and generated — generated wins.

## Extensions and analyzers (`lang/LanguageAnalyzerFactory.java`, `ExtensionGroupExtractor.java`)

Dedicated analyzers (units, complexity, dependencies) exist for: java, js (+cjs, es6, …), ts/tsx, go, cs, lua, d, c, cpp/cc/h/hpp/… (also `m`, `mm`, `dart`), php, hack, scala/sbt/sc, html-family (html, htm, cshtml, razor, jsx, vue, erb, hbs, handlebars, jinja, asp/aspx…), perl, ruby, groovy, gradle, css/less/sass/scss, jsp/gsp, vb/vbs/bas, clojure family, swift, kt/kts, sh/bash/zsh, yml/yaml, r, python family (py, pyi, pyx, …), jl, rs, pas/dpr, abap, adabas natural, puppet `pp` (overrides Object Pascal `pp`), sql, tsql, plsql, json, xml, dbc, cfg. Note `jsx` → HTML analyzer. Anything else in the ~1500-entry known-source list (md, txt, properties, proto, graphql, ipynb, tf, …) is analysed by the generic line-counting analyzer. `init` keeps every extension present in the tree that is known; `yml` is normalised to `yaml`.

## CLI (`cli/.../CommandLineInterface.java`, `Commands.java`)

- `init [-srcRoot .] [-confFile <path>] [-name] [-description] [-logoLink] [-addLink href label] [-conventionsFile analysis_conventions.json]` — detects extensions (ranked by presence), names the repo after the folder (capitalised), starts from the default configuration (default concerns, goal, tag rules), materialises matching scoping conventions, writes `<srcRoot>/_sokrates/config.json`. `srcRoot` stays `..`.
- `generateReports [-confFile ./_sokrates/config.json] [-outputFolder ./_sokrates/reports] [-date YYYY-MM-DD] [-timeout s]` — default config path is relative to the **current directory**; no flag overrides config values.
- `updateConfig [-confFile] [-skipComplexAnalyses] [-setCacheFiles true|false] [-setName] [-setDescription] [-setLogoLink] [-addLink href label]` — `-skipComplexAnalyses` sets skipDependencies/skipDuplication/skipCorrelations and saveSourceFiles=false.
- `extractGitHistory` (→ `git-history.txt`), `extractGitSubHistory -prefix`, `extractFiles -pattern -destFolder -destParent`, `createConventionsFile` (→ `./analysis_conventions.json`), `exportStandardConventions`, `updatePeopleConfigByUserName` (→ `_sokrates/config-people.json`).

`analysis_conventions.json` (custom conventions, `docs/configuration.md:528-689`): extra ignore/test/generated/build/other rules, `extensions.onlyInclude` / `alwaysExclude`, `ignoreStandardScopingConventions`, concerns, `ignoreContributors`/`bots`, and wholesale replacements of `analysis`, `fileHistoryAnalysis`, `tagRules`, plus `componentsFolderDepth`/`minComponentsCount`. Use it to make `init` reproducible across many repositories instead of hand-editing each config.

## Monorepos

No dedicated mechanism; use `componentsFolderDepth` / `minComponentsCount`, several named decompositions in one config (e.g. by folder depth 1 and by technology via explicit components), `filters` + `includeRemainingFiles:false` to analyse a slice, or `extractFiles` to carve out a subset for a separate analysis.

## Documentation in the Sokrates repo

`docs/configuration.md` (canonical manual; wrong about `trendAnalysis` and the "exactly one scope" claim), `README.md` quick start (`init` → edit → `generateReports`), `CLAUDE.md` (`CodeConfiguration` is the central model), `codeanalyzer/README.md`, `cli/README.md`.
