# Safety, privacy and security

## Safety and privacy boundaries

- CareLoop is not medical advice and does not replace a clinician. It does not diagnose, prescribe, change a dose, interpret a trend, or treat missing data as normal.
- Self-harm or medical-emergency words get emergency guidance (the local emergency number; 988 in the US) and never reach a tool or model.
- Only reviewed, patient-approved, source-backed rules can create alerts.
- A notification is not confirmation that someone saw it, acted on it, or that care occurred.
- Raw uploads, clinical data in audit logs, and private details in generic alerts or spoken replies are prohibited by design.
- Synthetic adult data only; no real patient records.
- Public [privacy policy](http://127.0.0.1:8010/privacy) and [terms of use](http://127.0.0.1:8010/terms) pages are served by the CareLoop server (`/privacy`, `/terms`). The same pages are on the [product page](https://ghost-141.github.io/CareLoop/privacy.html).
- The simulator is not an Amazon product and is not a certified Alexa+ integration. Production use needs independent clinical, legal, security, privacy, identity/account-linking, accessibility, and device review.

## Security decisions (MCP)

Choices made against the [MCP security best practices](https://modelcontextprotocol.io/docs/2026-07-28/tutorials/security/security_best_practices):

- **Static bearer tokens, not OAuth.** The Alexa+ MCP client doesn't support the `WWW-Authenticate` challenge yet, so `/mcp` answers 401 with a plain body. Account linking in a real deployment stays outside this adapter.
- **Identity comes from the credential.** Tool arguments never select a patient or caregiver, and returned refs are opaque, so holding a ref is not authentication.
- **Grants instead of protocol scopes.** Least privilege is enforced per patient through expiring caregiver grants.
- **No demo tokens off loopback.** The server exits at startup if it listens on a non-loopback address with the built-in demo tokens (`CARELOOP_ALLOW_DEMO_TOKENS` overrides).
- **Host and Origin allowlist.** DNS-rebinding protection is always on, including when bound to all interfaces. Add a tunnel hostname with `CARELOOP_ALLOWED_HOSTS`.
- **No token passthrough or proxying.** The server calls no downstream API with caller tokens.
