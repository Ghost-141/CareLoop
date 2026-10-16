# MCP guideline fixes for the hackathon

Fixes 1 to 5 from the review against the MCP 2026-07-28 docs (architecture, security best practices, build-server). Only the gaps that matter for the Alexa+ track submission (deadline Oct 23, 2026, noon PDT).

## Key finding behind item 2

The MCP SDK (2.1.1) already blocks unexpected Host and Origin headers, but only when the server binds to loopback (`127.0.0.1`, `localhost`, `::1`). Two consequences:

- **Behind a tunnel:** requests carry the tunnel's hostname and may be rejected (not yet tested).
- **Bound to all interfaces:** the protection turns off completely.

## 1. Refuse demo tokens off loopback (~30 min)

- **Change:** at startup in `server/care_loop/server.py`, if the host is not loopback and either token is still the built-in demo value (`auth.LOCAL_DEMO_TOKEN`, `auth.LOCAL_CAREGIVER_TOKEN`), exit with a message naming `CARELOOP_API_TOKEN` and `CARELOOP_CAREGIVER_TOKEN`.
- **Escape hatch:** `CARELOOP_ALLOW_DEMO_TOKENS`, off by default, for a deliberate local network demo.
- **Tests:**
  - Loopback with demo tokens starts.
  - Public host with demo tokens fails.
  - Public host with custom tokens starts.

## 2. Make Host and Origin protection explicit (~45 min)

- **Config:** add comma-separated `CARELOOP_ALLOWED_HOSTS` and `CARELOOP_ALLOWED_ORIGINS` in `server/care_loop/config.py`. Defaults match the SDK's loopback values:
  - hosts: `127.0.0.1:*`, `localhost:*`, `[::1]:*`
  - origins: `http://127.0.0.1:*`, `http://localhost:*`, `http://[::1]:*`
- **Wiring:** in `create_app`, always pass `TransportSecuritySettings(enable_dns_rebinding_protection=True, ...)` to `streamable_http_app`, so protection stays on for any bind address and the tunnel or deployed hostname can be allowed.
- **Tests:**
  - Allowed host succeeds.
  - Unknown host is rejected.
  - Foreign browser Origin is rejected.
- **Manual check:** one run through the actual demo tunnel.

## 3. Add tool titles (~30 min)

- **Change:** the SDK tool decorator accepts `title`. Extend the `tool(...)` helper in `server/care_loop/tools/records.py` to take one and give all 30 tools short titles (for example "Start daily check-in", "Revoke caregiver access").
- **Test:** every tool in `tools/list` has a non-empty title.

## 4. Fix the README protocol line (~10 min, after item 5)

- **If item 5 passes:** state support for 2025-11-25 and 2026-07-28.
- **If item 5 fails:** claim only 2025-11-25 and list 2026-07-28 as untested.
- **Add a "Security decisions" section covering:**
  - Static bearer tokens instead of OAuth, because the Alexa+ MCP client does not yet support the `WWW-Authenticate` challenge.
  - Patient-owned in-app grants instead of protocol scopes.
  - The demo token guard (item 1).
  - The host and origin allowlist (item 2).

## 5. Smoke test the 2026-07-28 path (~1 hour, time-boxed)

- **Test:** in `server/tests/test_care_loop_mcp_transport.py`, call `server/discover`, list tools, and make one read-only tool call with 2026-07-28 per-request `_meta`.
- **Stretch:** one elicitation call through `start_daily_checkin`, since elicitation moved to multi round-trip requests in this revision.
- **If it fails:** stop at the time box, record it in `docs/FRICTION_LOG.md`, and update the README per item 4. Alexa+ uses the older initialize handshake, which current tests already cover.

## Out of scope (documented, not fixed)

- **OAuth and `WWW-Authenticate`:** not supported by the Alexa+ MCP client yet.
- **Fine-grained protocol scopes:** per-patient grants already enforce least privilege.
- **Sampling and protocol logging:** deprecated in 2026-07-28 and unused.

## Schedule

| Day | Work |
| --- | --- |
| Oct 16 | Items 1 and 2, plus the tunnel check |
| Oct 17 | Item 3, item 5, then item 4 |
| Oct 18 | Full test suite, one commit per item |

About three hours total, leaving Oct 19 to 23 for the demo video and submission.
