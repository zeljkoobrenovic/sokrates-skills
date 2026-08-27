#!/usr/bin/env python3
"""Count connectivity-related code shapes for the network scanner.

Deterministic, standard-library only. Test code is excluded by path (test/tests/spec/
mock/fixture segments, *_test.*, *Test.java, test_*.py) and, for Rust, inside
`#[cfg(test)]` modules. Facts are copied into `stats`; leads (`*_candidates`,
`*_keyword_files`) are reading lists, never stats.

Usage:
  python3 count_network_sites.py <src-root> [--json out.json] [--top 12] [--exclude DIR ...]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

EXTS = {
    "rust": {".rs"}, "java": {".java", ".kt", ".scala"}, "csharp": {".cs"},
    "js": {".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"}, "python": {".py"}, "go": {".go"},
    "config": {".toml", ".yaml", ".yml", ".json", ".env", ".ini", ".properties", ".sql"},
}
SKIP_DIRS = {"node_modules", "target", "build", "dist", "out", ".git", "vendor", "venv", ".venv",
             "__pycache__", "_sokrates", "_sokrates_landscape"}
TEST_SEGMENT = re.compile(r"(^|[._-])(tests?|spec|specs|mocks?|fixtures?|testdata|test[-_]support)([._-]|$)", re.I)
TEST_FILE = re.compile(r"(_tests?\.\w+$|Tests?\.java$|\.spec\.\w+$|\.test\.\w+$|^test_.*\.py$|^tests?\.rs$|^conftest\.py$)", re.I)
RUST_CFG_TEST = re.compile(r"#\[cfg\(test\)\]")
RUST_MOD_OPEN = re.compile(r"^\s*(pub(\([^)]*\))?\s+)?mod\s+\w+\s*\{")

# key -> (regex, languages or None for all, note). Keys ending in _candidates/_keyword_files are leads.
PATTERNS = {
    "http_client_sites": (re.compile(r"reqwest::Client|Client::builder\(\)|ClientBuilder|HttpClient\.newBuilder|HttpClients\.|OkHttpClient|RestTemplate|WebClient\.|new HttpClient\(|axios\.create\(|axios\.|\bfetch\(|got\(|undici|requests\.(get|post|put|delete|Session)\(|httpx\.|aiohttp\.|urllib\.request|http\.(Get|Post|Client)\{|http\.NewRequest\(|curl_easy"), ['rust', 'java', 'csharp', 'js', 'python', 'go'], "HTTP client construction and calls"),
    "server_listen_sites": (re.compile(r"\.bind\(|\.listen\(|TcpListener::bind|HttpServer::new|axum::Server|Router::new\(\)|warp::serve|actix_web|ServerSocket\(|SpringBootApplication|@RestController|@GetMapping|@PostMapping|app\.(get|post|put|delete|listen)\(|createServer\(|express\(\)|fastify\(|uvicorn|FastAPI\(|Flask\(|@app\.route|http\.ListenAndServe|net\.Listen\("), ['rust', 'java', 'csharp', 'js', 'python', 'go'], "servers, listeners and routes"),
    "port_literal_sites": (re.compile(r"(port|PORT)\s*[:=]\s*\d{2,5}|:\d{4,5}[\"'/]|0\.0\.0\.0|127\.0\.0\.1|localhost:\d+"), ['rust', 'java', 'csharp', 'js', 'python', 'go', 'config'], "port and bind-address literals"),
    "websocket_sites": (re.compile(r"WebSocket|tokio_tungstenite|tungstenite|ws://|wss://|socket\.io|SockJS|@ServerEndpoint"), ['rust', 'java', 'csharp', 'js', 'python', 'go'], "WebSocket usage"),
    "sse_stream_sites": (re.compile(r"text/event-stream|EventSource|eventsource|bytes_stream\(\)|\.stream\(\)\.await|StreamingResponse|ServerSentEvent|SseEmitter|data:\s*\[DONE\]"), ['rust', 'java', 'csharp', 'js', 'python', 'go'], "SSE / streamed responses"),
    "grpc_rpc_sites": (re.compile(r"tonic::|grpc|GrpcChannel|ManagedChannel|@GrpcService|jsonrpc|JSON-RPC|rpc\.|mcp::|McpServer|McpClient|stdio transport"), ['rust', 'java', 'csharp', 'js', 'python', 'go'], "gRPC / RPC / MCP layers"),
    "raw_socket_sites": (re.compile(r"TcpStream::connect|UnixStream|UnixListener|new Socket\(|SocketChannel|net\.createConnection|net\.Socket|socket\.socket\(|net\.Dial\(|named pipe|\\\\\\\\\.\\\\pipe"), ['rust', 'java', 'csharp', 'js', 'python', 'go'], "raw TCP/Unix sockets and pipes"),
    "url_literal_sites": (re.compile(r"https?://(?!www\.w3\.org|schemas\.|xmlns|example\.com|localhost)[a-zA-Z0-9.-]+\.[a-z]{2,}[^\s\"')]*"), ['rust', 'java', 'csharp', 'js', 'python', 'go', 'config'], "URL literals (hosts the code knows about)"),
    "endpoint_env_sites": (re.compile(r"(getenv|env::var|process\.env\.|os\.environ|System\.getenv)\s*\(?\s*[\"']?[A-Z0-9_]*(URL|HOST|ENDPOINT|BASE|API|PORT|PROXY|SOCKET|ADDR)[A-Z0-9_]*"), ['rust', 'java', 'csharp', 'js', 'python', 'go'], "env vars that set endpoints, hosts, ports or proxies"),
    "proxy_sites": (re.compile(r"HTTPS?_PROXY|https?_proxy|NO_PROXY|no_proxy|\.proxy\(|Proxy\.|ProxySelector|proxy:\s*|HttpsProxyAgent|ProxyAgent|system_proxy|\.no_proxy\("), ['rust', 'java', 'csharp', 'js', 'python', 'go', 'config'], "proxy configuration"),
    "tls_config_sites": (re.compile(r"rustls|native_tls|openssl::|danger_accept_invalid_(certs|hostnames)|rejectUnauthorized|NODE_TLS_REJECT_UNAUTHORIZED|verify\s*=\s*False|InsecureSkipVerify|TrustManager|SSLContext|ssl\.create_default_context|add_root_certificate|ca_bundle|REQUESTS_CA_BUNDLE|SSL_CERT_FILE|min_tls_version|tls_built_in_root_certs|webpki"), ['rust', 'java', 'csharp', 'js', 'python', 'go'], "TLS configuration (verification, roots, versions)"),
    "tls_disabled_candidates": (re.compile(r"danger_accept_invalid_(certs|hostnames)\(true\)|rejectUnauthorized:\s*false|verify\s*=\s*False|InsecureSkipVerify:\s*true|NODE_TLS_REJECT_UNAUTHORIZED\s*=\s*['\"]?0|TrustAllCerts|ALLOW_ALL_HOSTNAME_VERIFIER"), ['rust', 'java', 'csharp', 'js', 'python', 'go'], "lead: TLS verification disabled — read whether on a default path (security-scan owns the audit)"),
    "client_timeout_sites": (re.compile(r"\.timeout\(Duration|\.connect_timeout\(|\.read_timeout\(|\.pool_idle_timeout\(|connectTimeout|readTimeout|\.timeout\(\s*\d|timeout:\s*\d|timeout\s*=\s*\d|AbortSignal\.timeout\(|http\.Client\{[^}]*Timeout"), ['rust', 'java', 'csharp', 'js', 'python', 'go'], "timeouts set on clients/requests"),
    "keepalive_pool_sites": (re.compile(r"keep_alive|keepAlive|tcp_keepalive|pool_max_idle_per_host|pool_idle_timeout|maxSockets|PoolingHttpClientConnectionManager|HTTPAdapter\(pool|Agent\(\{\s*keepAlive|MaxIdleConns"), ['rust', 'java', 'csharp', 'js', 'python', 'go'], "keep-alive and pooling settings"),
    "reconnect_keyword_files": (re.compile(r"\b(reconnect|reconnection|backoff|retry_after|Retry-After)\b"), ['rust', 'java', 'csharp', 'js', 'python', 'go'], "files mentioning reconnection/backoff (reliability owns policy)"),
    "dns_ipv6_sites": (re.compile(r"resolve\(|Resolver|dns::|hickory|trust_dns|lookup_host|InetAddress\.getByName|dns\.lookup|socket\.getaddrinfo|::1\b|Ipv6Addr|AF_INET6|happy.eyeballs"), ['rust', 'java', 'csharp', 'js', 'python', 'go'], "DNS resolution and IPv6"),
    "user_agent_sites": (re.compile(r"User-Agent|user_agent\(|USER_AGENT|\.header\(\"User-Agent|userAgent"), ['rust', 'java', 'csharp', 'js', 'python', 'go'], "client identification headers"),
    "offline_check_sites": (re.compile(r"\b(offline|is_online|isOnline|navigator\.onLine|connectivity|network_available|no_network|NetworkUnreachable|ConnectionRefused|ECONNREFUSED|ENOTFOUND|dns error|UnknownHostException|ConnectException)\b"), ['rust', 'java', 'csharp', 'js', 'python', 'go'], "offline/connectivity checks and unreachable-error handling"),
    "update_check_sites": (re.compile(r"check_for_update|checkForUpdate|latest_version|latest-version|update_available|releases/latest|version_check|UpdateChecker"), ['rust', 'java', 'csharp', 'js', 'python', 'go'], "update checks (incidental network use)"),
    "payload_local_content_candidates": (re.compile(r"(read_to_string|readFileSync|readFileToString|fs::read)\([^)]*\)[^;\n]*(body|json|payload|request|send)|(body|json|payload)\([^)]*(content|contents|file_text|source)"), ['rust', 'java', 'csharp', 'js', 'python', 'go'], "lead: request bodies built from local file contents"),
    "auth_header_sites": (re.compile(r"Authorization|Bearer\s|api[-_]?key|x-api-key|OAuth|oauth2|client_credentials|refresh_token"), ['rust', 'java', 'csharp', 'js', 'python', 'go'], "auth on the wire (security-design owns the design)"),
}


def language_of(path: Path):
    for lang, exts in EXTS.items():
        if path.suffix in exts:
            return lang
    return None


def is_test_path(path: Path, root: Path) -> bool:
    rel = path.relative_to(root)
    return bool(TEST_FILE.search(rel.name)) or any(TEST_SEGMENT.search(p) for p in rel.parts[:-1])


def rust_non_test(lines):
    pending, skip_depth, depth = False, None, 0
    for i, line in enumerate(lines, 1):
        if skip_depth is None:
            if RUST_CFG_TEST.search(line):
                pending = True
            elif pending and RUST_MOD_OPEN.search(line):
                skip_depth, pending = depth, False
            else:
                if pending and line.strip() and not line.strip().startswith(("#[", "//")):
                    pending = False
                    depth += line.count("{") - line.count("}")
                    continue
                yield i, line
        depth += line.count("{") - line.count("}")
        if skip_depth is not None and depth <= skip_depth:
            skip_depth = None


def scan(root: Path, excludes):
    hits, files_seen = defaultdict(list), defaultdict(int)
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        parts = path.relative_to(root).parts
        if any(p in SKIP_DIRS or p in excludes for p in parts[:-1]):
            continue
        lang = language_of(path)
        if not lang or is_test_path(path, root):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if lang == "config" and len(text) > 400_000:
            continue
        files_seen[lang] += 1
        lines = text.splitlines()
        rel = path.relative_to(root).as_posix()
        candidates = rust_non_test(lines) if lang == "rust" else enumerate(lines, 1)
        for lineno, line in candidates:
            for key, (rx, langs, _note) in PATTERNS.items():
                if langs and lang not in langs:
                    continue
                if rx.search(line):
                    hits[key].append((rel, lineno, line.strip()[:160]))
    return hits, files_seen


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
    hits, files_seen = scan(root, set(args.exclude))
    stats = {}
    for k, v in sorted(hits.items()):
        stats[k] = len({f for f, _, _ in v}) if k.endswith("_keyword_files") else len(v)
    leads = {k: n for k, n in stats.items() if k.endswith(("_candidates", "_keyword_files"))}
    facts = {k: n for k, n in stats.items() if k not in leads}
    notes = {k: PATTERNS[k][2] for k in stats}
    print(f"Scanned {sum(files_seen.values())} non-test files "
          f"({', '.join(f'{l}: {n}' for l, n in sorted(files_seen.items()))}) under {root}\n")
    print("stats (copy into findings stats):")
    for k, n in facts.items():
        print(f"  {k:36s} {n:6d}   {notes.get(k, '')}")
    print("leads (read before citing; do NOT copy as stats):")
    for k, n in leads.items():
        print(f"  {k:36s} {n:6d}   {notes.get(k, '')}")
    print()
    for key, rows in sorted(hits.items()):
        per_file = defaultdict(int)
        for f, _, _ in rows:
            per_file[f] += 1
        print(f"{key} — top files:")
        for f, n in sorted(per_file.items(), key=lambda kv: -kv[1])[: args.top]:
            print(f"  {n:5d}  {f}")
        print()
    if args.json:
        Path(args.json).write_text(json.dumps({
            "src_root": str(root), "files_scanned": dict(files_seen),
            "count_rule": "non-test files by path (test/tests/spec/mock/fixture segments, *_test.*, *Test.java, test_*.py)"
                          + ("; Rust #[cfg(test)] modules excluded" if "rust" in files_seen else "") + "; single-line regex matches",
            "stats": facts, "leads": leads, "notes": notes,
            "hits": {k: [{"file": f, "line": l, "snippet": s} for f, l, s in v] for k, v in hits.items()},
        }, indent=2))
        print(f"wrote {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
