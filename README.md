# herdr-grok-bridge

Unofficial **read-only** [MCP](https://modelcontextprotocol.io) bridge from
[Grok Bot](https://grok.x.ai) (or any MCP stdio client) to a running
[Herdr](https://herdr.dev) session.

This project is **not** affiliated with Herdr. It offers MCP *tools* only — not
an embedded native Herdr UI, Canvas, or refresh button.

## What it does

Strict allowlist of three read operations (plus a non-sensitive `bridge_info`):

| Tool | Herdr command | Purpose |
| --- | --- | --- |
| `list_agents` | `herdr agent list --format json` | Active agents, statuses, `pane_id` targets |
| `get_agent_status` | `herdr agent get <pane_id> --format json` | Status for one live pane |
| `read_pane` | `herdr pane read <pane_id> --source …` | Bounded pane text (redacted / truncated) |
| `bridge_info` | _(none)_ | Mode, timeouts, limits — never SSH host |

**Not included (hard-denied):** prompts, send-keys, focus, start/attach, pane
run/close/split, generic RPC/shell, or any user-supplied executable command.

Read targets must be **live `pane_id` values** from `list_agents` (for example
`w1:p2`). Bare kinds such as `claude` are rejected.

## Security risks

- **Read access can reveal terminal secrets** (tokens, passwords, private keys
  scrolled into a pane). Output is best-effort redacted and size-limited, but
  redaction is not perfect.
- Prefer Tailscale / SSH Host aliases and existing `known_hosts` entries.
- The bridge never changes focus, prompts agents, or restarts Herdr — but a
  compromised MCP client can still *read* whatever is visible in panes you
  expose.

## Requirements

- Python 3.12+
- A reachable Herdr CLI (`herdr`) on the Herdr host (verified conceptually
  against Herdr 0.8.x / local-only socket; this bridge talks to the CLI, not
  the Unix socket directly)
- For remote use: OpenSSH client, `BatchMode` key auth, host key already in
  `known_hosts`

## Install

### From a release artifact (no git checkout)

```sh
python3 -m venv ~/.venvs/herdr-grok-bridge
~/.venvs/herdr-grok-bridge/bin/pip install /path/to/herdr_grok_bridge-0.1.0-py3-none-any.whl
# or: pip install /path/to/herdr_grok_bridge-0.1.0.tar.gz
```

Entry point: `~/.venvs/herdr-grok-bridge/bin/herdr-grok-bridge`

### From source with uv

```sh
uv sync
uv run herdr-grok-bridge --help
```

## Deployment

### A) Local (MCP server on the Herdr host)

```json
{
  "mcpServers": {
    "herdr-readonly": {
      "command": "/home/USER/.venvs/herdr-grok-bridge/bin/herdr-grok-bridge",
      "args": [],
      "env": {
        "HERDR_BRIDGE_MODE": "local"
      }
    }
  }
}
```

### B) SSH / Tailscale from Grok Bot’s Linux box (recommended remote path)

Configure OpenSSH so a **Host alias** already works non-interactively
(`ssh herdr-box herdr agent list`). Then:

```json
{
  "mcpServers": {
    "herdr-readonly": {
      "command": "/home/USER/.venvs/herdr-grok-bridge/bin/herdr-grok-bridge",
      "args": [],
      "env": {
        "HERDR_BRIDGE_MODE": "ssh",
        "HERDR_BRIDGE_SSH_HOST": "herdr-box"
      }
    }
  }
}
```

`herdr-box` is a **generic example** Host alias — use your own. Do not put
private hostnames, IPs, or credentials in this repository.

SSH argv is fixed by the bridge (not tool-callable):

- `BatchMode=yes`
- `StrictHostKeyChecking=yes` (existing `known_hosts` only)
- `PasswordAuthentication=no` / `KbdInteractiveAuthentication=no`
- optional `HERDR_BRIDGE_SSH_USER`, `HERDR_BRIDGE_SSH_PORT`,
  `HERDR_BRIDGE_SSH_IDENTITY_FILE`

Remote shape: `ssh … <destination> -- herdr <allowlisted args…>`

### Environment reference

| Variable | Meaning |
| --- | --- |
| `HERDR_BRIDGE_MODE` | `local` or `ssh` (default `ssh` if host set, else `local`) |
| `HERDR_BRIDGE_SSH_HOST` | OpenSSH destination / Host alias |
| `HERDR_BRIDGE_SSH_USER` | Optional user |
| `HERDR_BRIDGE_SSH_PORT` | Optional port |
| `HERDR_BRIDGE_SSH_IDENTITY_FILE` | Optional identity file path |
| `HERDR_BRIDGE_HERDR_BIN` | Default `herdr` |
| `HERDR_BRIDGE_TIMEOUT_SECONDS` | Subprocess timeout (default `30`) |
| `HERDR_BRIDGE_CONNECT_TIMEOUT_SECONDS` | SSH connect timeout (default `10`) |
| `HERDR_BRIDGE_MAX_LINES` | Cap for `--lines` on recent sources (default `200`) |
| `HERDR_BRIDGE_MAX_OUTPUT_CHARS` | Client-side output cap (default `100000`) |

## Compatibility notes

- `list_agents` expects JSON shaped like
  `{ "id": "cli:agent:list", "result": { "type": "agent_list", "agents": [ … ] } }`.
- Some Herdr versions reject `--lines` with `--source visible` / `detection`.
  This bridge **omits** `--lines` for those sources and truncates client-side
  when requested.
- For `recent` / `recent-unwrapped`, a capped `--lines` is always sent
  (default 80).

## Development

```sh
uv sync --group dev
uv run pytest
uv build   # wheel + sdist under dist/
```

Unit tests are mock-backed: command construction, validation, timeouts,
JSON decoding, mutation denial, and an in-memory MCP init/list/call smoke test.
They do not touch a live Herdr host.

## License

MIT. Wholly new code for this repository; inspired by ideas from community
Herdr MCP experiments and the public Herdr docs, without reusing their source.
