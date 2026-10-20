# Existing ChatGPT conversations over MCP

This extension runs chat2api behind an authenticated MCP server. It lists, reads,
and continues the connected account's existing ChatGPT conversations using HTTP.
The backend does not need a browser. Existing conversation tools can run when
ChatGPT makes them available to that continuation; availability depends on ChatGPT.

The upstream chat2api base is commit `a63a90c`. Its license remains in
[../LICENSE](../LICENSE). The root source contains the backend patches; `mcp/`
contains the server, deployment files, authentication, and acceptance checks.

## Changes

- Preserve supplied user-message UUIDs, forward the account/workspace header,
  and distinguish failures before sending from uncertain delivery.
- Disable chat2api's application logger because upstream log messages can contain
  credentials and conversation contents.
- Persist send receipts in SQLite. Repeating a `request_id` observes the same send
  instead of submitting another message. A saved reply is checked against the
  conversation tree.
- Share one Python process between HTTP/OAuth and private Unix MCP sessions.
  SSH stdio uses `socat`, with no Python process per connection. Tool calls are
  limited to four concurrently; the Unix listener allows at most 32 clients.
- Use FastMCP OAuthProxy with DCR/CIMD, PKCE, explicit consent, and encrypted
  persistent grant storage. Authelia supplies the server's separate login.
- Refresh a dedicated upstream account login atomically under a file lock.
- Supply a Cloudflare Worker and Caddy origin template. OAuth responses bypass
  caching, including cookies needed for consent CSRF validation.

## Tools

| Tool | Behavior |
| --- | --- |
| `list_conversations` | List a page; `query` filters that page only. Follow `next_offset`. |
| `read_conversation` | Read saved messages on the current branch. Page backwards with `next_before_message_id`. |
| `continue_conversation` | Send an authorized message to an existing conversation, then inspect its saved reply. |

`continue_conversation` requires `conversation_id`, `message`, and `request_id`.
Use a unique request ID per intended message. For retries, keep **all arguments
identical**. Never use a new ID merely because a request timed out.

- `completed`: a saved reply was found for this exact user-message UUID.
- `sent_reply_pending`: message saved, reply still pending; repeat the same call.
- `delivery_uncertain`: repeat the same call to reconcile; do not resend.
- `reply_failed` / `reply_ended`: the observed reply reached a terminal state.
- `not_sent`: the backend confirms sending never started. Fix the cause before
  intentionally making a new attempt with a new ID.

Allow at least 360 seconds per tool call. The generation request can take 180
seconds before the additional observation interval. The `chatgpt://health`
resource reports credential expiry/refresh availability without revealing tokens.
Conversation contents are untrusted data, not instructions for the MCP client.

## Linux installation

Prerequisites: Docker Compose, Python 3, OpenSSL, and `socat` for SSH stdio.
The optional edge deployment also needs Caddy and Wrangler. This is a deployment
kit for a Linux administrator; review and adapt the example configuration first.

1. Clone this fork into `/opt/chat2api`, then create a symlink:
   `ln -s /opt/chat2api/mcp /opt/chatgpt-mcp`. The parent repository must remain
   present because the backend Docker build uses it as its context.
2. In `/opt/chatgpt-mcp`, copy `.env.example` to `.env` and set the public MCP
   URL and Authelia issuer. Use the same hostname everywhere below.
3. As root, run `PUBLIC_HOST=mcp.example.com python3 https/configure-auth.py`.
   This generates Authelia keys, an initial `owner` login, an internal OAuth
   client, and the stable proxy encryption key. It refuses to overwrite existing
   provisioning. Credentials are written to root-only `private-connection.json`;
   keep this file private. The internal client secret is **not** a ChatGPT input.
4. Create a dedicated `chatgpt-login` Linux user with home
   `/var/lib/chatgpt-mcp-login`. Run `python3 install-cli.py` to obtain the pinned
   official Linux x64 Codex login binary with npm SHA-512 integrity verification.
   Symlink `/usr/local/libexec/chatgpt-codex-login` to
   `/opt/chatgpt-mcp/bin/codex`. Run `./login-account` and complete device login
   with the intended ChatGPT account/workspace. The login cache is imported to
   `secrets/auth.json`, then removed to avoid competing token refreshers.
5. Run `docker compose up -d --build`. Services bind only to loopback. Keep the
   backend private. Install the supplied systemd service/timer into
   `/etc/systemd/system/`, reload systemd, and enable
   `chatgpt-mcp-auth.timer` for credential checks every ten minutes.
6. Adapt `https/Caddyfile.origin.template`: replace `__PUBLIC_HOST__`,
   `__ORIGIN_HOST__`, and `__ORIGIN_AUTH__`. Obtain HTTPS for the origin. Set a
   fresh random origin secret and store the same value with
   `wrangler secret put ORIGIN_AUTH --config edge/wrangler.jsonc`.
7. Edit the domain/route and origin URL in `edge/wrangler.jsonc`, then deploy
   with Wrangler. Keep `workers_dev` and preview URLs disabled. The origin must
   reject requests missing the shared edge secret. The server trusts proxy
   headers from loopback and `172.20.0.1`; adapt that explicit allowlist in
   `server/server.py` if the Docker bridge gateway differs.
8. In ChatGPT, add your public `/mcp` URL using OAuth and automatic client
   registration. Log in with the separate server login and approve consent.

The `.env` values are Docker Compose configuration. `configure-auth.py` uses
`PUBLIC_HOST` explicitly; keep it consistent with `.env` and the edge configuration.
The default internal client ID is `chatgpt-mcp`. Existing deployments must retain
and reuse their own client IDs, keys, and data instead of re-provisioning them.

SSH stdio clients can run:

```sh
ssh -o BatchMode=yes -o ConnectTimeout=10 your-server /opt/chatgpt-mcp/mcp-stdio
```

The Unix directory is mode 0700 and its socket mode 0600, owned by UID 10001.
Privileged SSH access is the boundary for this transport. Never switch the wrapper
back to launching `docker exec ... python server.py --stdio` for each client.

To change the dedicated login later, run `python3 update-login.py` as root,
supplying a JSON object with `username` and `password` through standard input.
The helper hashes the password with Argon2id, updates the single configured
account, restarts Authelia, and verifies the login without printing the password.

## Repository updates

Run `/opt/chatgpt-mcp/update` as root. It requires a clean `main` checkout,
fast-forwards from this fork, builds versioned backend/MCP images, runs unit
tests before replacing services, and waits for container health. Runtime state
is ignored by Git and retained. Keep the preceding image tags for rollback.
Run the live checks below after each update; health alone does not verify ChatGPT.

## Verification and maintenance

```sh
# Offline unit tests inside the pinned runtime; no account writes:
docker compose exec -T mcp python -m unittest discover -p 'test_*.py'
node edge/test-edge.mjs

# Live tests (require a configured installation):
python3 https/test-auto-oauth.py
python3 https/test-auto-http.py
MCP_SSH_HOST=your-server python3 https/test-ssh-shared.py
python3 https/test-shared-process.py /opt/chatgpt-mcp/run/server.sock chatgpt-mcp-mcp-1
```

The OAuth check temporarily writes `auto-oauth-test-tokens.json` as root; remove
it after the HTTP check. Live checks read conversations but do not post messages.
The shared-process check's second argument must match your MCP container name.
Full public DCR login, consent, PKCE, refresh, and saved conversation reads were
verified in the original deployment. Real ChatGPT CIMD authorization was checked
through callback; its signed exchange requires ChatGPT's own client key.

Preserve `secrets/`, `state/` (including receipts and encrypted grants),
`auth-config/`, and `auth-data/` across rebuilds. Do not delete receipts casually:
old request IDs could otherwise send again. The UUID namespace in `service.py`
is intentionally stable for compatibility with already-issued receipts.
Never commit these runtime directories or private connection/token files.

The upstream interface is undocumented and can change. Container health alone
does not prove upstream authentication or generation works. Concurrent writes
from the official site/app are outside the service's receipt lock; avoid using
multiple writers on the same conversation at once.
