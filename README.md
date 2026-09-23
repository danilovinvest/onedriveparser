# onedrive-mcp

Local MCP server giving Claude **read-only** access to a **personal** OneDrive
(outlook.com / hotmail.com / live.com accounts) through Microsoft Graph.
No work or school account required.

Tools exposed to Claude:

| Tool | What it does |
|---|---|
| `list_folder` | List a folder by drive path (`Documents/Taxes`) or item id; root if empty |
| `search` | Search names and contents across the drive |
| `get_metadata` | Size, type, dates and web link of one item |
| `read_file` | Download a file and return its text (pdf, docx, xlsx, plain text) |

## 1. Register an app (one time)

Microsoft no longer lets a bare personal account register apps outside a
directory, so you first need your own (free) Entra directory:

1. Create a free Azure account at <https://azure.microsoft.com/free> with your
   personal Microsoft account. This creates a *Default Directory* for you.
2. In <https://portal.azure.com> → **Microsoft Entra ID** → **App registrations**
   → **New registration**:
   - Supported account types: **Personal Microsoft accounts only**
   - Redirect URI: leave empty
3. In the new app → **Authentication** → **Advanced settings** → set
   **Allow public client flows** to **Yes** (required for the device code login).
4. **API permissions** → Microsoft Graph → *Delegated*: `Files.Read`, `User.Read`
   (`offline_access` is requested automatically).
5. Copy the **Application (client) ID** from the Overview page.

No client secret is needed: this is a public client.

## 2. Install and sign in

```bash
uv sync
export ONEDRIVE_CLIENT_ID=<your-client-id>
uv run onedrive-mcp login     # prints a code to enter at microsoft.com/devicelogin
```

Tokens are cached in `~/.config/onedrive-mcp/token_cache.json` (mode `0600`)
and refreshed silently. `uv run onedrive-mcp logout` removes them.

## 3. Connect Claude

Claude Code:

```bash
claude mcp add onedrive -e ONEDRIVE_CLIENT_ID=<your-client-id> -- \
  uv --directory /absolute/path/to/onedrive-mcp run onedrive-mcp serve
```

Claude Desktop (`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "onedrive": {
      "command": "uv",
      "args": ["--directory", "/absolute/path/to/onedrive-mcp", "run", "onedrive-mcp", "serve"],
      "env": { "ONEDRIVE_CLIENT_ID": "<your-client-id>" }
    }
  }
}
```

## Windows installer (Claude Desktop, nothing else required)

Copy the whole project folder to the PC (zip, USB, LocalSend…), then
double-click `scripts\windows\install.bat`. It:

1. installs [uv](https://docs.astral.sh/uv/) and Python 3.12 (per user, no admin)
2. copies the project to `%LOCALAPPDATA%\onedrive-mcp` and installs dependencies
3. opens the Microsoft sign-in page for the device code login (skipped if already signed in)
4. adds `onedrive` to `claude_desktop_config.json`, keeping existing servers (backup in `.bak`)

Then fully quit Claude Desktop (tray icon → Quit) and start it again.
Re-running the installer is safe. `scripts\windows\uninstall.bat` removes the
Claude Desktop entry, the OneDrive token and the install folder.

`onedrive-mcp status` exits 0 when signed in, 3 when a login is needed.

## Running on a server (Docker, over SSH)

The container publishes no port: Claude starts it per session through SSH, so
MCP traffic only travels inside the SSH tunnel and tokens stay in a volume.

```bash
# on the server, in /opt/onedrive-mcp (code + .env with ONEDRIVE_CLIENT_ID)
docker compose build
docker compose run --rm -T mcp login   # device code, once

# on your machine
claude mcp add -s user onedrive -- ssh -o BatchMode=yes root@<host> \
  docker compose -f /opt/onedrive-mcp/compose.yaml run --rm -T mcp serve
```

Update: ship the new code (`git archive HEAD | ssh root@<host> tar -x -C
/opt/onedrive-mcp`) then `docker compose build` again; the token volume is kept.

## Configuration

| Variable | Default |
|---|---|
| `ONEDRIVE_CLIENT_ID` | required |
| `ONEDRIVE_TOKEN_CACHE` | `~/.config/onedrive-mcp/token_cache.json` |
| `ONEDRIVE_AUTHORITY` | `https://login.microsoftonline.com/consumers` |
| `ONEDRIVE_MAX_DOWNLOAD_BYTES` | `20971520` (20 MB) |
| `ONEDRIVE_MAX_TEXT_CHARS` | `100000` |

## Development

```bash
uv run pytest        # hermetic: network access is blocked in tests
```
