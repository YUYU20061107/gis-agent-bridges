# Security model and vulnerability reporting (SECURITY)

Chinese version: [`SECURITY.md`](SECURITY.md)

Security is a core differentiator of this project. This document is open
for review; where it disagrees with the implementation, the code wins
and an issue pointing out the gap is welcome.

## Security model

- **Local listeners only**: in-app bridges listen on `127.0.0.1` only
  (ports 47615–47619), never on an external interface; MCP servers use
  stdio and talk only to the local client. The pgRouting/istsos consumer
  bridges listen on no port, but they do initiate connections to a
  configured database or SensorThings service (see "Consumer bridge
  egress" below).
- **Random token**: each in-app bridge launch generates a random token
  stored in a local token file (a dotfile in the home directory; the
  location can be changed with each package's `*_BRIDGE_TOKEN_FILE`
  environment variable). Requests without the correct token are refused
  (`BAD_TOKEN`). For desktop packages the MCP server reads the token
  file automatically — **users never copy tokens by hand**. The
  pgRouting/istsos bridges are direct stdio consumers with no separate
  in-app process, so tool calls must carry the current `_token`
  argument; see each package's README/SKILL. Headless packages (ENVI /
  Global Mapper / FME / MapGIS probe) provide equivalent optional or
  required token guards.
- **Confirm gate**: content-level write/execute tools refuse to run
  without `confirm=true`; only the user may authorize setting it. This
  invariant is statically checked by `manifest/check_invariants.py`
  and continuously verified in CI.
- **Originals are read-only**: headless inventory never opens an
  original directly; every write works on a timestamped backup copy.
  A PathGuard-lite check rejects UNC paths, control characters, and
  writes whose resolved target equals the source.
- **No arbitrary code execution**: there is no eval/exec of external
  input, no arbitrary script or processing-tool channel. Everything an
  agent can do is an enumerated, auditable tool; the machine-readable
  list is `manifest/tools-manifest.json`.

## Consumer bridge egress

- **pgRouting (database surface)**: the bridge connects through the
  `psql` subprocess to a user-configured PostgreSQL and runs only
  three fixed templates — no arbitrary SQL. A table name must pass
  both an identifier regex and the `PGROUTING_ALLOWED_TABLES`
  allowlist; connection parameters are inherited by psql from `PG*`
  environment variables, and the bridge never reads or logs the value
  of `PGPASSWORD`. **The bridge cannot enforce database permissions
  for you**: give it a read-only account with `SELECT` on the target
  edge tables only. If you hand psql a highly privileged account, the
  risk is whatever that account can do. The export tool only writes a
  new GeoJSON file at a caller-specified path.
- **istsos / SensorThings API (network surface)**: the bridge sends
  GET requests only to the user-configured `ISTSOS_BASE_URL` — no
  arbitrary URL fetching. `$top`, pagination, observation counts,
  export counts, response size and timeout all have hard caps. Treat
  a remote STA server as an **untrusted input source**: the bridge can
  bound volume and shape, not truth. Prefer HTTPS for public services;
  never commit credential-bearing URLs to the repo, prompts or logs.
  Public demo endpoints are for protocol connectivity checks only;
  they do not make istSOS4 itself trusted or calibrated.

## Threat model (in scope)

- Another process on the same machine connecting to a bridge port and
  impersonating the agent (token defense);
- An agent induced to write without user consent (confirm defense);
- A mistaken path overwriting an original (backup + copy + PathGuard);
- An over-privileged database account (read-only account + table
  allowlist defense);
- A malicious or compromised STA server returning oversized, malformed
  or misleading responses (GET-only, count/pagination/size/timeout
  caps; content truth is out of scope).

## Out of scope (stated honestly)

- This project is **not a sandbox**: any process that can read the
  local token file can call the bridge; token-file protection depends
  on your OS account and directory permissions.
- `confirm` is a consent protocol, not cryptographic enforcement: a
  fully hijacked client can set it itself. When running next to real
  GIS software, that software's own permissions and licensing are
  outside this project's control.
- This project distributes no vendor components and bypasses no vendor
  licensing.
- PostgreSQL account permissions, network isolation and auditing are
  the database administrator's responsibility; an STA server's
  identity, content truth and availability are its operator's.

## Calibration status

Whether a bridge actually works is decided by real-machine calibration
in each package's `docs/CALIBRATION.md`. "Protocol selftest passed"
does not mean "calibrated on real software". Current per-package state
is in the root README matrix and honesty statement.

## Reporting a vulnerability

Prefer GitHub's private vulnerability reporting:
<https://github.com/YUYU20061107/gis-agent-bridges/security/advisories/new>.
Include the affected package and version, reproduction steps, impact,
and your proposed disclosure timeline. If the private entry point is
unavailable to your account, open a public GitHub issue titled
`[security]` with a **summary only** — no working exploit details, no
real tokens, credentials or private project paths — and the maintainer
will arrange a private channel.

Response targets (best effort for a solo-maintained project, not an
SLA): acknowledgement within 7 days, an initial assessment within 14
days or an explanation of why it needs longer. Supported versions are
the latest GitHub Release and the `main` branch; older snapshots are
handled only when the issue also affects a supported version.
