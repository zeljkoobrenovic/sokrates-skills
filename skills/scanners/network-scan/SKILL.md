---
name: network-scan
description: Maps how a codebase talks over the network - the connectivity topology (what it listens on, what it connects to, which side initiates, which ports and hosts), the protocols as used in code (HTTP/REST, WebSocket, SSE, gRPC, MCP, raw sockets, sync vs streaming), connection management (clients and pooling, keep-alive, reconnection, timeouts, TLS configuration, proxies, DNS), configurability of endpoints (env vars, config keys, hardcoded hosts), behaviour without connectivity (offline mode, cached fallbacks, what breaks), and the data that crosses the wire (payload shapes, sizes, what leaves the machine) - synthesized into a connectivity posture. Use whenever the user asks what a project connects to, what it listens on, which protocols it uses, how it handles proxies/TLS/timeouts, what happens offline, what data it sends where, or wants a network/connectivity review. Works best with a Sokrates analysis (_sokrates folder) but degrades gracefully without one.
---

# Network scan

Every network call is a dependency on something the program does not control. This scanner maps those dependencies as the code actually makes them — which hosts, which protocols, which side opens the connection, what the client is configured to tolerate, and what the program does when the other side is slow, gone, or behind a corporate proxy. It is the connectivity *behaviour* of the codebase, not a list of its network libraries.

**First read `sokrates-scan-core/SKILL.md`** (sibling skill) — output format, evidence rules, validate/render scripts, `_sokrates` layout. This file adds only what is specific to network scanning.

## The one question

*For each remote endpoint: who opens the connection, over what, configured how, and what does the user experience when it is unreachable?* Ask it per endpoint class, not per call site.

## Scope and boundaries with sibling scanners

- **`tech-stack-scan`** (`external-services`, `protocols-formats`) names the services and protocols. Read it first; this scanner describes the *usage and behaviour*, never re-inventories.
- **`functionality-scan`** (`integrations`) says what each integration does for the user; reference it and describe only the connectivity.
- **`reliability-scan`** (`recovery/outgoing-retry`, `reconnection`) owns retry, backoff and reconnection policy. **This scanner owns client-construction timeouts** (connect/read/idle/total on the builder, per client) — reliability's `timeouts` finding, if any, is referenced, and stream-level idle timeouts it already cited are mentioned, not re-cited. Streaming mechanics beyond what reliability described (how a stream ends, compression, framing) are `protocols`; if reliability already covered the fallback and idle timeout, keep `streaming-<class>` to what is left or fold it into `outbound-<class>`.
- **`architecture-scan`** (`security-boundaries`) owns trust boundaries, the sandbox egress proxy and network confinement as structure; **`security-scan`** owns auth flows and what data may leave the machine as *policy*; **`functionality-scan`** (`data/*what-leaves*`, `integrations`) and **`observability-scan`** (`telemetry-pipeline`) usually already say what is sent where. `data-in-transit` takes the body contents *from those findings by reference* and adds only the transport envelope: headers and identifiers, encoding/compression, size bounds, what is received and trusted. Do not read the prompt builder to reconstruct request bodies.
- **`security-scan`** owns TLS verification disabled, hardcoded credentials in URLs; note and cross-reference, do not audit.
- **`performance-scan`** owns N+1 calls and connection cost.

**Cross-referencing.** List existing ids first (`grep -h '"id"' _sokrates/findings/ai-insights/*.json --exclude=combined-report.json`) and reference siblings as `sokrates_refs: ["finding:<scanner>/<group>/<slug>"]` — only ids you saw. Never copy another scanner's evidence blocks.

## Workflow

1. **Orient per the core skill.** Read six siblings: `tech-stack-scan` (`external-services`, `protocols-formats`), `functionality-scan` (`integrations`, `data`), `architecture-scan` (`communication` — the transport/listener map), `reliability-scan` (`recovery/*`), `architecture-scan` (`security-boundaries`), `security-scan` (`identity-access`, `third-party-trust`), `observability-scan` (`telemetry-pipeline`). Decide the system kind: a client of remote APIs, a server, both (an agent runtime that calls model APIs *and* serves a protocol), or offline software with incidental network use (update checks, telemetry). A batch tool with no network use gets a short `topology/no-network` finding and stops — say so and do not pad. An empty `external-services` group in `tech-stack-scan` is itself a strong signal. If the program's *produced artifacts* depend on the network (generated HTML loading CDN scripts, reports linking out), mention it inside `no-network` with references to `functionality-scan`/`security-scan` — do not open further groups; that is not "incidental use". Incidental use means the *process* makes a few opt-in or side calls (update checks, telemetry, docs links opened in a browser).
2. **Count with the script, then find the connectivity code.** Run
   ```bash
   python3 <this-skill-path>/scripts/count_network_sites.py <src-root> --json <scratch>/network-counts.json
   ```
   It counts, per ecosystem and excluding tests: HTTP client construction and calls, servers and listeners (bind/listen/ports), WebSocket/SSE/gRPC/socket usage, URL and host literals, endpoint env vars and config keys, TLS configuration, proxy handling, timeouts and keep-alive settings on clients, DNS/resolution, offline/connectivity checks — facts to copy into `stats`, leads to read. From the top files, locate: the client factory/wrapper per remote service, the server/listener setup, the endpoint configuration (how base URLs are resolved), the transport layer (streaming, reconnection), and the offline/error path the user sees. Read those completely (outline files over ~800 lines).
3. **Build the endpoint inventory.** For every endpoint class — model/API providers, auth services, package registries, update/telemetry endpoints, local servers and IPC, peer connections: direction (outbound/inbound), protocol, default host/port, how configurable, authentication mode (reference security-scan), whether on the default path or opt-in. This is the `topology/endpoints` finding and the frame for everything else.
4. **Read protocols as used.** Request/response vs streaming; SSE/WebSocket framing and how streams end; gRPC/protobuf usage; MCP or other RPC layers; content negotiation and versioning of the wire format; how payload size is bounded.
5. **Read connection management.** Client construction and reuse (one client vs per-call), pooling and keep-alive, timeouts per phase (connect/read/idle/total) and their values, reconnection and backoff (reference reliability), TLS: certificate verification, custom roots, pinning, minimum versions; proxy support: `HTTP(S)_PROXY`/`NO_PROXY`, system proxy, authenticated proxies; DNS and IPv6; user-agent and headers; local sockets and IPC.
6. **Read configurability and defaults.** Where base URLs and ports come from (env vars, config keys, flags, hardcoded), precedence between them, what is hardcoded and cannot be changed, and whether self-hosted or air-gapped deployment is possible.
7. **Read the offline experience.** Connectivity checks, offline modes, cached responses, what fails and how it is reported when the network is absent or blocked, startup dependencies on the network (does the program start without it?).
8. **Read data in transit.** Payload shapes per endpoint class: what identifiers, file contents, environment details, and user content are sent; sizes and bounds; compression; what is received and trusted (reference security-scan for validation).
9. **Synthesize the posture.** One `network-posture/posture` finding, `severity: info`, `confidence: likely`: the endpoint map with defaults, the strongest and weakest connection handling, the offline story, deployability behind proxies / air-gapped, and the three highest-leverage changes as `finding:` refs. Evidence cites the client factory or endpoint resolution.
10. Write findings, validate, render; re-run the merge script if a `combined-report.json` exists. Report per the core workflow. Scanner id: `network-scan`, version `1.1`.

## Group taxonomy

| group | contents |
|---|---|
| `topology` | The endpoint inventory: what listens, what connects out, direction, hosts/ports, defaults, opt-in vs default path, local IPC |
| `protocols` | Protocols as used in code: request/response vs streaming, SSE/WebSocket/gRPC/MCP mechanics, wire-format versioning, payload bounds |
| `connection-management` | Client construction and reuse, pooling and keep-alive, timeouts per phase, reconnection (referencing reliability), TLS configuration, proxy support, DNS/IPv6, headers and identification |
| `configurability` | How endpoints, ports and transports are configured: env vars, config keys, flags, precedence, hardcoded hosts, self-hosting and air-gapped feasibility |
| `offline-behaviour` | Connectivity checks, offline modes, cached fallbacks, startup without network, what the user sees when unreachable |
| `data-in-transit` | What crosses the wire per endpoint class: identifiers, file contents, environment, user content; sizes; what is received and trusted (cross-referencing security and observability) |
| `network-posture` | The synthesis (one finding, `info`, id `network-posture/posture`) |

**Precedence**: a client timeout → `connection-management`; retry/backoff → reliability (reference); an env var that sets a URL → `configurability`, one that toggles telemetry → observability (reference); outbound proxy resolution → `connection-management/proxy-support`, the sandbox's egress proxy → architecture-scan `security-boundaries` (reference); a feature-flag-gated network behaviour → the group of the behaviour, with the flag in `attributes.gated_by`; a cached response used when offline → `offline-behaviour`; a payload that includes file contents → `data-in-transit` by reference to functionality/security-scan; a listener → `topology`, its auth → security-scan.

## Stable ids

Slugs are **endpoint-class, mechanism or artifact names, never consequences**. Fixed slugs (use only when the subject exists; parametrised slugs take the kebab-case endpoint class as the code names it):

| group | fixed slugs |
|---|---|
| `topology` | `endpoints` (the inventory, one finding, endpoints in `attributes`), `listeners` (all inbound surfaces including unix sockets and stdio; `local-ipc` only when IPC is a mechanism distinct from listening), `outbound-<class>` (only for the *default-path* endpoint classes — the transport selection and defaults for that class; opt-in classes stay in `endpoints.attributes`), `no-network` |
| `protocols` | `streaming-<class>`, `rpc-<class>`, `wire-versioning`, `payload-bounds` |
| `connection-management` | `client-lifecycle`, `timeouts`, `reconnection`, `tls`, `proxy-support`, `dns-and-ipv6`, `identification` (user-agent, headers) |
| `configurability` | `endpoint-config`, `hardcoded-hosts`, `self-hosting` |
| `offline-behaviour` | `connectivity-checks`, `offline-mode`, `startup-dependencies`, `unreachable-experience` |
| `data-in-transit` | `payloads-<class>`, `local-content-egress`, `inbound-trust` |
| `network-posture` | `posture` |

Project-specific findings get a free slug naming the endpoint or mechanism, never the consequence. The `<class>` token is the same string across groups (`outbound-model-api`, `streaming-model-api`, `payloads-model-api`) so refs line up. Several mechanisms sharing a slug are listed in `attributes`. A slot whose content is one or two sentences (`dns-and-ipv6`, `payload-bounds`, `wire-versioning`, `identification`) is folded into its parent finding's `attributes` rather than written alone; `offline-mode` and `unreachable-experience` are skipped when a sibling already carries the verdict — the reference goes in the posture.

## What a good finding looks like

Evidence is the client builder line with its timeout, the `bind(` call with its port, the base-URL resolution with its env var, the `danger_accept_invalid_certs`/`rejectUnauthorized` line, the proxy env read, the offline check. Descriptions speak per endpoint class: "the model API client is one `reqwest::Client` per session with a 300 s idle timeout, honours `HTTPS_PROXY`, verifies TLS with the platform roots, and the base URL is `OPENAI_BASE_URL` → config `base_url` → hardcoded default". One finding per endpoint class or mechanism, not per call site.

Expect 10–16 findings for a networked client/server or agent runtime; 3–6 for software with incidental network use; 1 (`topology/no-network`) for offline software.

## Severity calibration

- `high` — TLS verification disabled or downgradable on a default path (cross-reference security-scan; it is the owner, report here only if it does not); local file contents or secrets sent to an endpoint the user did not opt into; a listener open to non-local interfaces by default without auth (owner: security-scan `identity-access`; cross-reference).
- `medium` — no connect or total timeout on a default-path *unary* call (a stream with an idle timeout counts as having one); a hardcoded host that prevents self-hosting where the product documents or advertises self-hosting/alternate providers; proxy env vars ignored; system/PAC proxy unsupported where enterprise use is a stated target; startup that hangs without network; reconnection without bound (reference reliability).
- `low` — endpoints configurable only through undocumented env vars, inconsistent client construction across subsystems, missing user-agent/version identification, IPv6 or DNS quirks, offline mode that exists but is not discoverable, system/PAC proxy support present but flag-gated.
- `info` — the endpoint map, protocols as used, configuration precedence, mechanisms that work.
- Mitigations lower a finding one rung: opt-in feature, interruptible, documented.

## Output

Follow the core workflow: write `_sokrates/findings/ai-insights/network-scan.json`, validate until OK, render the explorer, re-merge if a combined report exists, report leading with the posture summary (what the software connects to by default and what happens when it cannot, in two sentences) and any above-info findings.

`stats` — copy the script's **facts** under its own keys (omit keys whose shape does not exist in the ecosystem; a fact key you verified to be entirely false positives is omitted and named in `count_notes`), add `count_rule`, and on top:

- `endpoint_classes` — list as used in the findings
- `outbound_endpoints` — object: class → default host (or `configurable`), e.g. `{"model-api": "api.openai.com", "telemetry": "configurable, off by default"}`
- `listeners` — list of entries `protocol:port`, `unix:<path>`, `stdio`; `[]` for none
- `protocols` — list as used, e.g. `["HTTPS", "SSE", "WebSocket", "MCP over stdio"]`
- `tls_verification` — `platform-roots`, `platform-roots+custom-ca`, `bundled-roots`, `configurable`, `disabled-on-<path>`, `not-applicable`
- `proxy_support` — list from `env-vars`, `system`, `pac`, `config`, `flag-gated:<name>`, `ignored` (connections made, proxies not honoured), `not-applicable` (no connections)
- `default_timeouts` — object per default-path client: `{"model-api": {"connect": null, "total": null, "idle": "300s"}}`
- `feature_gated` — list of network behaviours behind flags, `["respect_system_proxy", ...]`
- `offline_mode` — `full`, `partial`, `none`, `not-applicable`
