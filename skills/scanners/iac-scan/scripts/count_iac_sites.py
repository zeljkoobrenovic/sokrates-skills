#!/usr/bin/env python3
"""Inventory and count infrastructure-as-code shapes for the IaC scanner.

Deterministic, standard-library only. Unlike the code scanners' counting scripts this one
classifies *files* by IaC tool first (a Dockerfile is a Dockerfile wherever it sits), then counts
declaration and hardening shapes inside them. Test/fixture paths are excluded, but note that IaC
under `test/` is often a real fixture worth reading — such files are listed under
`excluded_test_iac_files` as a lead rather than silently dropped.

Facts are copied into `stats`; leads (`*_candidates`, `*_keyword_files`) are reading lists, never
stats. Every hardening count is a *candidate* until read: `privileged: true` in a devcontainer is
not a production risk.

Usage:
  python3 count_iac_sites.py <src-root> [--json out.json] [--top 12] [--exclude DIR ...]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

SKIP_DIRS = {"node_modules", "target", "build", "dist", "out", ".git", "vendor", "venv", ".venv",
             "__pycache__", "_sokrates", "_sokrates_landscape", ".terraform", "site-packages"}
TEST_SEGMENT = re.compile(r"(^|[._-])(tests?|spec|specs|mocks?|fixtures?|testdata|test[-_]support)([._-]|$)", re.I)

# --- file classification -------------------------------------------------------------------
# tool -> (filename regex, path regex or None). A file may match several tools; the first wins.
FILE_KINDS = [
    ("dockerfile", re.compile(r"^(Dockerfile|Containerfile)(\..+)?$|\.dockerfile$", re.I), None),
    ("compose", re.compile(r"^(docker-)?compose([.-].+)?\.ya?ml$", re.I), None),
    # `devcontainer.secure.json` and friends count too — matching only `devcontainer.json` hid the
    # file carrying the capability grants. Still name-shaped, so an npm manifest sitting under
    # .devcontainer/ is not swept in.
    ("devcontainer", re.compile(r"^devcontainer(\..+)?\.json$|^devcontainer(\..+)?\.ya?ml$", re.I), None),
    ("terraform", re.compile(r"\.tf$|\.tfvars$|\.tf\.json$", re.I), None),
    ("terraform_state", re.compile(r"\.tfstate(\.backup)?$", re.I), None),
    ("helm", re.compile(r"^(Chart|values)([.-].+)?\.ya?ml$", re.I), None),
    # Anything under a chart's templates/ is Helm, not plain Kubernetes — its `{{ .Values }}`
    # references only mean something in the chart's context.
    ("helm", re.compile(r"\.ya?ml$|\.tpl$", re.I), re.compile(r"(^|/)templates/", re.I)),
    ("kustomize", re.compile(r"^kustomization\.ya?ml$", re.I), None),
    ("cloudformation", re.compile(r"\.(template|cfn)\.(ya?ml|json)$", re.I), None),
    ("serverless", re.compile(r"^serverless\.ya?ml$|^template\.ya?ml$|^sam\.ya?ml$", re.I), None),
    ("ansible", re.compile(r"^(playbook|site|main)\.ya?ml$", re.I), re.compile(r"(ansible|playbooks?|roles)/", re.I)),
    ("vagrant", re.compile(r"^Vagrantfile$", re.I), None),
    ("nix", re.compile(r"^(flake|shell|default|configuration)\.nix$|^flake\.lock$", re.I), None),
    ("systemd", re.compile(r"\.(service|timer|socket|target)$", re.I), None),
    ("pulumi", re.compile(r"^Pulumi(\..+)?\.ya?ml$", re.I), None),
    ("cdk", re.compile(r"^cdk\.json$", re.I), None),
    ("packer", re.compile(r"\.pkr\.(hcl|json)$", re.I), None),
    ("procfile", re.compile(r"^Procfile$", re.I), None),
    ("skaffold", re.compile(r"^skaffold\.ya?ml$", re.I), None),
]
# YAML that declares Kubernetes objects is recognised by content, not name.
K8S_DOC = re.compile(r"^\s*apiVersion:\s*\S+", re.M)
K8S_KIND = re.compile(r"^\s*kind:\s*([A-Za-z][A-Za-z0-9]*)", re.M)
# Cloud-provider IaC written in a general-purpose language (CDK/Pulumi/CDKTF).
CDK_CODE = re.compile(r"aws-cdk-lib|@pulumi/|pulumi_aws|from aws_cdk|cdktf|constructs\.Construct")
CODE_EXTS = {".ts", ".js", ".py", ".go", ".java", ".cs"}
YAML_EXTS = {".yaml", ".yml"}

# --- shapes counted inside classified files ------------------------------------------------
# key -> (regex, tools it applies to (None = all IaC files), note)
PATTERNS = {
    # --- what is declared -------------------------------------------------------------------
    "terraform_resources": (re.compile(r'^\s*resource\s+"([^"]+)"'), {"terraform"}, "declared Terraform resources"),
    "terraform_data_sources": (re.compile(r'^\s*data\s+"([^"]+)"'), {"terraform"}, "Terraform data sources"),
    "terraform_modules": (re.compile(r'^\s*module\s+"'), {"terraform"}, "module calls"),
    "terraform_variables": (re.compile(r'^\s*variable\s+"'), {"terraform"}, "declared input variables"),
    "terraform_outputs": (re.compile(r'^\s*output\s+"'), {"terraform"}, "declared outputs"),
    "backend_blocks": (re.compile(r'^\s*backend\s+"|^\s*cloud\s*\{'), {"terraform"}, "state backend declarations"),
    "provider_blocks": (re.compile(r'^\s*(provider\s+"|required_providers\s*\{)'), {"terraform"}, "provider declarations"),
    "lifecycle_ignore": (re.compile(r"ignore_changes|prevent_destroy"), {"terraform"}, "drift accommodations"),
    "k8s_documents": (re.compile(r"^\s*apiVersion:\s*\S+"), {"k8s", "helm", "kustomize"}, "Kubernetes object documents"),
    "k8s_replicas": (re.compile(r"^\s*replicas:\s*\d+"), {"k8s", "helm"}, "replica declarations"),
    "helm_value_refs": (re.compile(r"\{\{\s*\.Values\."), {"helm"}, "chart template value references"),
    "compose_services": (re.compile(r"^\s{2,4}[a-zA-Z0-9_-]+:\s*$"), {"compose"}, "lead: compose service-like keys (indentation heuristic)"),
    "docker_stages": (re.compile(r"^\s*FROM\s+", re.I), {"dockerfile"}, "Dockerfile FROM stages"),
    "exposed_ports": (re.compile(r"^\s*EXPOSE\s+\d|^\s*-?\s*(containerPort|nodePort|hostPort):\s*\d|^\s*-\s*[\"']?\d+:\d+"), None, "declared/published ports"),
    "volumes_and_mounts": (re.compile(r"^\s*VOLUME\s|volumeMounts:|^\s*volumes:|persistentVolumeClaim:|hostPath:"), None, "declared volumes and mounts"),
    "healthchecks": (re.compile(r"^\s*HEALTHCHECK\s|livenessProbe:|readinessProbe:|startupProbe:|healthcheck:", re.I), None, "health/liveness checks"),
    "restart_policies": (re.compile(r"^\s*restart:|restartPolicy:"), None, "restart policies"),
    "resource_limits": (re.compile(r"^\s*limits:|^\s*requests:|\bmem_limit\b|\bcpus\b:|resources:\s*$"), {"k8s", "helm", "compose"}, "resource limit/request blocks"),
    "iam_policy_docs": (re.compile(r'"Effect"\s*:\s*"Allow"|Effect:\s*Allow|aws_iam_(policy|role)|google_project_iam|azurerm_role'), None, "IAM/role declarations"),
    # --- hardening candidates (read before rating) -------------------------------------------
    "image_refs": (re.compile(r"^\s*FROM\s+\S+|^\s*image:\s*\S+", re.I), None, "image references (base and runtime)"),
    # An image ref is unpinned when it carries no tag at all or the mutable `:latest`; a version tag
    # (`ubuntu:24.04`) is a *mutable tag*, not unpinned — only a digest is immutable. Build-stage
    # references (`FROM builder AS x`, `COPY --from=`) are not image refs and must not match.
    "unpinned_image_candidates": (re.compile(r"^\s*(?:FROM|image:)\s*[\"']?(?![-\w.]+\s+AS\b)[\w./-]+(?::latest)?[\"']?\s*(?:AS\s+[\w-]+)?\s*$", re.I), None, "lead: image refs with no tag or :latest (a version tag is a mutable tag, counted under image_refs)"),
    "mutable_tag_candidates": (re.compile(r"^\s*(?:FROM|image:)\s*[\"']?(?![^@\s]*@sha)[\w./-]+:(?!latest\b)[\w.-]+[\"']?(?:\s+AS\s+[\w-]+)?\s*$", re.I), None, "lead: image refs pinned by a version tag only (mutable — the tag can be repointed; :latest counts as unpinned instead)"),
    "digest_pinned_images": (re.compile(r"^\s*(FROM|image:)\s*[\"']?\S+@sha256:", re.I), None, "images pinned by digest"),
    "user_directives": (re.compile(r"^\s*USER\s+\S+|runAsUser:|runAsNonRoot:|^\s*user:\s*\S+", re.I), None, "explicit user directives"),
    "root_user_candidates": (re.compile(r"^\s*USER\s+(root|0)\b|runAsUser:\s*0\b|runAsNonRoot:\s*false|^\s*user:\s*[\"']?(root|0)\b", re.I), None, "lead: explicit root users"),
    "privileged_candidates": (re.compile(r"privileged:\s*true|\"privileged\"\s*:\s*true|allowPrivilegeEscalation:\s*true|--privileged|hostNetwork:\s*true|hostPID:\s*true|hostIPC:\s*true|network_mode:\s*[\"']?host|cap_add:|capabilities:|--cap-add|--security-opt|seccomp=unconfined|apparmor=unconfined", re.I), None, "lead: privilege, capability and host-namespace grants (compose, k8s and devcontainer runArgs)"),
    # devcontainer.json shapes — these were previously invisible, and a devcontainer is the whole
    # subject on a container-only repo.
    "devcontainer_mounts": (re.compile(r"\"(mounts|workspaceMount)\"\s*:|source=[^,]+,target="), {"devcontainer"}, "devcontainer mounts and bind sources"),
    "devcontainer_env": (re.compile(r"\"(containerEnv|remoteEnv)\"\s*:|^\s*\"[A-Z][A-Z0-9_]{2,}\"\s*:"), {"devcontainer"}, "devcontainer container/remote env values"),
    "devcontainer_features": (re.compile(r"\"features\"\s*:|ghcr\.io/[\w./-]+devcontainers?"), {"devcontainer"}, "devcontainer features pulled in"),
    # A feature is a container image too, but it is a JSON *key*, so the FROM/image: counters miss
    # it — `.../dotslash:latest` is exactly the mutable ref the pinning findings care about.
    "unpinned_feature_candidates": (re.compile(r"""["'][\w.-]+/[\w./-]+:latest["']\s*:"""), {"devcontainer"}, "lead: devcontainer features pinned to :latest"),
    "devcontainer_build_args": (re.compile(r"\"args\"\s*:|\"(dockerfile|context|image)\"\s*:"), {"devcontainer"}, "devcontainer build inputs (image/dockerfile/args)"),
    "docker_socket_candidates": (re.compile(r"/var/run/docker\.sock|docker\.sock"), None, "lead: docker socket mounts"),
    "read_only_root": (re.compile(r"readOnlyRootFilesystem:\s*true|read_only:\s*true"), None, "read-only root filesystems"),
    "public_access_candidates": (re.compile(r"0\.0\.0\.0/0|::/0|public-read|acl\s*=\s*[\"']public|allUsers|allAuthenticatedUsers|publicly_accessible\s*=\s*true|type:\s*LoadBalancer|NodePort"), None, "lead: world-open or publicly exposed declarations"),
    "encryption_settings": (re.compile(r"encrypt(ed|ion)?\s*[=:]|kms_key|sse_algorithm|storage_encrypted|tls:|secretName:", re.I), None, "encryption/TLS settings"),
    "build_arg_sites": (re.compile(r"^\s*ARG\s+\S+|--build-arg|^\s*args:", re.I), {"dockerfile", "compose", "devcontainer"}, "build args (a secret-carrying surface)"),
    "build_secret_mounts": (re.compile(r"--mount=type=secret|secrets:\s*$|secret_id"), None, "build-time secret mounts"),
    "copy_whole_context": (re.compile(r"^\s*(COPY|ADD)\s+\.\s+", re.I), {"dockerfile"}, "COPY/ADD of the whole build context"),
    "add_remote_candidates": (re.compile(r"^\s*ADD\s+https?://|curl[^|]*\|\s*(sudo\s+)?(ba)?sh", re.I), None, "lead: remote content fetched into images"),
    "env_declarations": (re.compile(r"^\s*ENV\s+\S+|^\s*env:\s*$|^\s*-\s*name:\s*[A-Z_]{3,}|^\s*environment:"), None, "environment values supplied to the runtime"),
    "secret_refs": (re.compile(r"secretKeyRef|valueFrom:|env_file:|kind:\s*Secret|aws_secretsmanager|vault_|sops|sealed-?secret", re.I), None, "references to secret stores (mechanism, not values)"),
    "plaintext_secret_candidates": (re.compile(r"(password|passwd|secret|token|api[_-]?key|private[_-]?key)\s*[=:]\s*[\"']?[A-Za-z0-9/+_-]{8,}", re.I), None, "lead: secret-shaped literals in IaC files (read every one; most are placeholders)"),
    "version_pins": (re.compile(r"^\s*version\s*[=:]\s*[\"']?[~^><=]*\d|required_version|chart:\s*\S+@|targetRevision:"), None, "version pins of providers, modules and charts"),
    "apply_command_candidates": (re.compile(r"terraform\s+(apply|plan)|kubectl\s+apply|helm\s+(install|upgrade)|pulumi\s+up|ansible-playbook|docker\s+compose\s+up|aws\s+cloudformation\s+deploy"), None, "lead: apply commands (in scripts and workflows)"),
    # Populated from CI/script files rather than by the per-IaC-file loop; registered here so they
    # carry notes and print under leads.
    "ci_job_image_candidates": (None, None, "lead: images referenced by CI jobs and devcontainer features (no Dockerfile builds them here — judge their pinning too)"),
    "undeclared_infrastructure_candidates": (None, None, "lead: infrastructure named in CI but declared nowhere in the repo (buckets, distributions, registries, environments) — the raw material for inventory/coverage"),
}
# Files worth scanning even though they are not IaC themselves: they carry the apply path, image
# references in CI job containers, and the names of infrastructure nothing in the repo declares.
APPLY_SCAN = re.compile(r"\.(sh|bash|zsh|ps1|mk|just)$|^(Makefile|justfile|Justfile)$|\.github/workflows/.*\.ya?ml$|\.gitlab-ci\.ya?ml$|buildspec\.ya?ml$|\.circleci/.*\.ya?ml$|azure-pipelines\.ya?ml$")
CI_IMAGE = re.compile(r"""^\s*(?:image|container):\s*["']?([\w./-]+(?::[\w.-]+)?(?:@sha256:[0-9a-f]+)?)["']?\s*$""", re.I)
# Infrastructure named in CI but declared nowhere — buckets, distributions, registries, environments.
UNDECLARED = re.compile(r"s3://|cloudfront|distribution[_-]?id|AWS_[A-Z_]{2,}|GOOGLE_[A-Z_]{2,}|AZURE_[A-Z_]{2,}|"
                        r"^\s*environment:\s*\S|secretsmanager|\.amazonaws\.com|ghcr\.io/|endpoint[_-]?url", re.I)
COMMENT = re.compile(r"^\s*(#|//|/\*|\*|<!--)")


def is_test_path(rel: Path) -> bool:
    return any(TEST_SEGMENT.search(p) for p in rel.parts[:-1])


def classify(path: Path, rel: Path, text: str | None):
    """Return the IaC tool name for this file, or None."""
    name, posix = path.name, rel.as_posix()
    for tool, name_rx, path_rx in FILE_KINDS:
        if name_rx.search(name) and (path_rx is None or path_rx.search(posix)):
            return tool
    if text is None:
        return None
    if path.suffix.lower() in YAML_EXTS and K8S_DOC.search(text) and K8S_KIND.search(text):
        return "k8s"
    if path.suffix.lower() in CODE_EXTS and CDK_CODE.search(text):
        return "cdk_code"
    return None


def scan(root: Path, excludes):
    hits = defaultdict(list)
    files_by_tool = defaultdict(list)
    k8s_kinds, tf_resource_types, images = defaultdict(int), defaultdict(int), defaultdict(int)
    excluded_test_iac, apply_hits, ci_image_hits, undeclared_hits = [], [], [], []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(root)
        if any(p in SKIP_DIRS or p in excludes for p in rel.parts[:-1]):
            continue
        try:
            if path.stat().st_size > 2_000_000:
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        tool = classify(path, rel, text)
        posix = rel.as_posix()
        if tool and is_test_path(rel):
            excluded_test_iac.append(posix)
            continue
        if not tool:
            # non-IaC files may still carry the apply path
            if APPLY_SCAN.search(posix) or APPLY_SCAN.search(path.name):
                rx = PATTERNS["apply_command_candidates"][0]
                for lineno, line in enumerate(text.splitlines(), 1):
                    if COMMENT.match(line):
                        continue
                    if rx.search(line):
                        apply_hits.append((posix, lineno, line.strip()[:160]))
                    m = CI_IMAGE.search(line)
                    if m:
                        ci_image_hits.append((posix, lineno, line.strip()[:160]))
                        images[m.group(1)] += 1
                    if UNDECLARED.search(line):
                        undeclared_hits.append((posix, lineno, line.strip()[:160]))
            continue
        files_by_tool[tool].append(posix)
        for lineno, line in enumerate(text.splitlines(), 1):
            if COMMENT.match(line):
                continue
            for key, (rx, tools, _note) in PATTERNS.items():
                if rx is None or (tools and tool not in tools):
                    continue  # rx None = filled in from CI/script files, not from IaC files
                m = rx.search(line)
                if not m:
                    continue
                hits[key].append((posix, lineno, line.strip()[:160]))
                if key == "terraform_resources":
                    tf_resource_types[m.group(1)] += 1
                elif key == "image_refs":
                    ref = re.sub(r"^\s*(FROM|image:)\s*[\"']?", "", line.strip(), flags=re.I)
                    images[ref.split()[0].strip("\"'") if ref.split() else ref] += 1
        if tool in {"k8s", "helm", "kustomize"}:
            for m in K8S_KIND.finditer(text):
                k8s_kinds[m.group(1)] += 1
    hits["apply_command_candidates"].extend(apply_hits)
    hits["ci_job_image_candidates"].extend(ci_image_hits)
    hits["undeclared_infrastructure_candidates"].extend(undeclared_hits)
    return hits, files_by_tool, k8s_kinds, tf_resource_types, images, excluded_test_iac


DOCKER_FROM = re.compile(r"^\s*FROM\s+(\S+)(?:\s+AS\s+(\S+))?", re.I)
DOCKER_USER = re.compile(r"^\s*USER\s+(\S+)", re.I)
DOCKER_ENTRY = re.compile(r"^\s*(ENTRYPOINT|CMD)\s+(.+)", re.I)


def dockerfile_stages(root: Path, rel_paths):
    """Per-Dockerfile stage records. `COPY . .` is only a finding when nothing filters the
    context, and for a multi-stage build the load-bearing user is the *final* stage's."""
    out = {}
    for rel in rel_paths:
        try:
            lines = (root / rel).read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        stages, cur = [], None
        for line in lines:
            if COMMENT.match(line):
                continue
            m = DOCKER_FROM.search(line)
            if m:
                cur = {"base": m.group(1), "as": m.group(2), "user": None, "entrypoint": None}
                stages.append(cur)
                continue
            if cur is None:
                continue
            m = DOCKER_USER.search(line)
            if m:
                cur["user"] = m.group(1)
            m = DOCKER_ENTRY.search(line)
            if m:
                cur["entrypoint"] = m.group(2).strip()[:120]
        if stages:
            out[rel] = {"stages": stages, "final_stage_user": stages[-1]["user"] or "(none — root)"}
    return out


def build_context(root: Path):
    """Size of what an unfiltered `COPY . .` would pull in, and whether anything filters it."""
    ignore = root / ".dockerignore"
    total, biggest = 0, []
    for p in root.rglob("*"):
        if not p.is_file() or any(d in SKIP_DIRS for d in p.relative_to(root).parts[:-1]):
            continue
        try:
            n = p.stat().st_size
        except OSError:
            continue
        total += n
        biggest.append((n, p.relative_to(root).as_posix()))
    biggest.sort(reverse=True)
    return {
        "dockerignore_present": ignore.is_file(),
        "dockerignore_lines": len([l for l in ignore.read_text(errors="replace").splitlines()
                                   if l.strip() and not l.startswith("#")]) if ignore.is_file() else 0,
        "context_bytes": total,
        "context_mb": round(total / 1_048_576, 1),
        "largest_files": [{"bytes": n, "file": f} for n, f in biggest[:10]],
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    ap.add_argument("src_root")
    ap.add_argument("--json")
    ap.add_argument("--top", type=int, default=12)
    ap.add_argument("--exclude", action="append", default=[], metavar="DIR")
    args = ap.parse_args(argv)
    root = Path(args.src_root).resolve()
    if not root.is_dir():
        print(f"error: not a directory: {root}", file=sys.stderr)
        return 2

    hits, files_by_tool, k8s_kinds, tf_types, images, excluded = scan(root, set(args.exclude))
    file_counts = {t: len(f) for t, f in sorted(files_by_tool.items())}
    dockerfiles = dockerfile_stages(root, files_by_tool.get("dockerfile", []))
    ctx = build_context(root) if files_by_tool.get("dockerfile") or files_by_tool.get("compose") else None
    provisioning = bool({"terraform", "k8s", "helm", "kustomize", "cloudformation", "cdk", "cdk_code",
                         "pulumi", "ansible", "serverless", "packer", "skaffold"} & set(file_counts))
    stats = {}
    for k in PATTERNS:
        v = hits.get(k, [])
        if not v and k.endswith(("_candidates", "_keyword_files")):
            continue
        stats[k] = len(v)
    stats = dict(sorted(stats.items()))
    leads = {k: n for k, n in stats.items() if k.endswith(("_candidates", "_keyword_files"))}
    facts = {k: n for k, n in stats.items() if k not in leads}
    notes = {k: PATTERNS[k][2] for k in stats}

    total = sum(file_counts.values())
    print(f"=== src_root: {root}")  # echoed prominently: a stale --json file is easy to misread
    print(f"Found {total} infrastructure files under {root}")
    print(f"  provisioning IaC: {'yes' if provisioning else 'no (container/dev-environment definitions only)'}\n")
    print("iac_files (facts — one entry per tool):")
    for t, n in file_counts.items():
        print(f"  {t:22s} {n:5d}")
    if not file_counts:
        print("  (none)")
    print()
    if k8s_kinds:
        print("k8s_kinds (facts):")
        for k, n in sorted(k8s_kinds.items(), key=lambda kv: -kv[1]):
            print(f"  {k:30s} {n:5d}")
        print()
    if tf_types:
        print("terraform_resource_types (facts):")
        for k, n in sorted(tf_types.items(), key=lambda kv: -kv[1])[: args.top]:
            print(f"  {k:40s} {n:5d}")
        print()
    if images:
        print("images referenced (facts — pinning judged by reading, not by this list):")
        for k, n in sorted(images.items(), key=lambda kv: -kv[1])[: args.top]:
            print(f"  {n:4d}  {k}")
        print()
    if dockerfiles:
        print("dockerfiles (facts — a multi-stage build is ONE image finding; the final stage's user is the one that runs):")
        for f, rec in dockerfiles.items():
            print(f"  {f}")
            for i, st in enumerate(rec["stages"], 1):
                as_ = f" AS {st['as']}" if st["as"] else ""
                print(f"    stage {i}: FROM {st['base']}{as_}  user={st['user'] or '-'}"
                      + (f"  entry={st['entrypoint']}" if st["entrypoint"] else ""))
            print(f"    final_stage_user: {rec['final_stage_user']}")
        print()
    if ctx is not None:
        di = "present" if ctx["dockerignore_present"] else "ABSENT"
        print(f"build_context (facts): .dockerignore {di}"
              + (f" ({ctx['dockerignore_lines']} patterns)" if ctx["dockerignore_present"] else "")
              + f", context {ctx['context_mb']} MB")
        if not ctx["dockerignore_present"] and ctx["largest_files"]:
            print("  `COPY . .` with no .dockerignore pulls in, largest first:")
            for e in ctx["largest_files"][:5]:
                print(f"    {e['bytes']/1_048_576:8.1f} MB  {e['file']}")
        print()
    print("stats (facts; copy into findings stats after discarding keys you verified as false positives, naming them in count_notes):")
    for k, n in facts.items():
        print(f"  {k:32s} {n:6d}   {notes.get(k, '')}")
    print("leads (read before citing; do NOT copy as stats):")
    for k, n in leads.items():
        print(f"  {k:32s} {n:6d}   {notes.get(k, '')}")
    if excluded:
        print(f"\nexcluded_test_iac_files ({len(excluded)}) — IaC under test/fixture paths, read if relevant:")
        for f in excluded[: args.top]:
            print(f"  {f}")
    print()
    for key, rows in sorted(hits.items()):
        if not rows:
            continue
        per_file = defaultdict(int)
        for f, _, _ in rows:
            per_file[f] += 1
        print(f"{key} — top files:")
        for f, n in sorted(per_file.items(), key=lambda kv: -kv[1])[: args.top]:
            print(f"  {n:5d}  {f}")
        print()

    if args.json:
        Path(args.json).write_text(json.dumps({
            "src_root": str(root),
            "count_rule": "files classified by IaC tool (name, path and, for YAML/code, content); IaC under "
                          "test/fixture paths excluded and listed separately; single-line regex matches, "
                          "comment lines skipped",
            "provisioning_iac": provisioning,
            "iac_files": file_counts,
            "iac_file_paths": {t: f for t, f in sorted(files_by_tool.items())},
            "k8s_kinds": dict(sorted(k8s_kinds.items(), key=lambda kv: -kv[1])),
            "terraform_resource_types": dict(sorted(tf_types.items(), key=lambda kv: -kv[1])),
            "images": dict(sorted(images.items(), key=lambda kv: -kv[1])),
            "excluded_test_iac_files": excluded,
            "dockerfiles": dockerfiles,
            "build_context": ctx,
            "stats": facts, "leads": leads, "notes": notes,
            "hits": {k: [{"file": f, "line": l, "snippet": s} for f, l, s in v] for k, v in hits.items() if v},
        }, indent=2))
        print(f"wrote {args.json} (src_root {root})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
