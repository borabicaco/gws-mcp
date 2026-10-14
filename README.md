# gws-mcp: Google Workspace MCP server (multi-account)

A local [MCP](https://modelcontextprotocol.io) server that gives Claude Desktop access to
**Gmail, Google Calendar and Google Drive** on one or more Google Workspace accounts.
Each account gets an alias (e.g. `work`) and every tool takes an optional `account` argument.

- **Read-only by default.** Write access is opt-in per account.
- **No sending, no deleting.** Even with write enabled, there are no tools to send email,
  send drafts, delete, trash or cancel anything. You send your own emails.
- **Tokens in the macOS Keychain** (or an encrypted file on servers), never in plain text.
- **Nothing sensitive is logged.** Logs go to stderr and token-shaped strings are redacted.

## Contents

1. [Tools](#tools)
2. [Security model](#security-model)
3. [Google Cloud setup](#google-cloud-setup) (one time per Workspace organization)
4. [Install](#install)
5. [Add an account](#add-an-account)
6. [Add to Claude Desktop](#add-to-claude-desktop)
7. [Turn write access on or off](#turn-write-access-on-or-off)
8. [More accounts](#more-accounts)
9. [Token storage options](#token-storage-options)
10. [Troubleshooting](#troubleshooting)
11. [Development](#development)

## Tools

| Area | Read (always) | Write (only with `write = true`) |
|---|---|---|
| General | `list_accounts` | |
| Gmail | `gmail_get_profile`, `gmail_search` (Gmail operators), `gmail_get_message`, `gmail_get_thread`, `gmail_list_attachments`, `gmail_download_attachment`, `gmail_list_labels`, `gmail_list_drafts` | `gmail_create_draft`, `gmail_create_reply_draft`, `gmail_update_draft`, `gmail_update_user_draft`, `gmail_modify_labels`, `gmail_create_label` |
| Calendar | `calendar_list_calendars`, `calendar_list_events`, `calendar_search_events`, `calendar_get_event` | `calendar_create_event`, `calendar_update_event` |
| Drive | `drive_search`, `drive_recent_files`, `drive_get_metadata`, `drive_read_file` | `drive_create_file`, `drive_create_folder` |

Notes:

- `drive_read_file` exports Google Docs and Slides as plain text and Sheets as CSV (first
  sheet only). Other files (PDF, images, Office files) are saved to the downloads folder.
- Attachments and Drive files are saved to `~/Downloads/gws-mcp` by default. Existing files
  are never overwritten; a numbered copy is created instead.
- Reply drafts are attached to the original conversation (`threadId`, `In-Reply-To`,
  `References`, `Re:` subject).

## Security model

**Two layers protect write access.** A write tool only works when both are true for the
account:

1. `write = true` is set for the account in the config file, **and**
2. Google actually granted the write permissions (scopes) to the stored token.

If no account has `write = true`, write tools are not registered at all and Claude does not
see them. If one account has write on and another off, the tools are visible but refuse to
act on the read-only account.

**Scopes requested from Google:**

| Mode | Scopes |
|---|---|
| Read-only | `gmail.readonly`, `calendar.readonly`, `drive.readonly` |
| Write (added) | `gmail.modify`, `calendar.events`, `drive.file` |

Google has no "drafts only" scope: `gmail.modify` would technically allow sending and
trashing, and `calendar.events` would allow deleting. This server blocks those actions in its
own code. The tools simply do not exist, adding the `TRASH`/`SPAM` labels is refused, and
event status (cancellation) cannot be changed. `drive.file` lets the server write only files
it created itself, so your existing Drive files can never be changed.

**Drafts.** Drafts created by Claude carry a hidden `X-GWS-MCP` header.
`gmail_update_draft` only changes those. To change a draft *you* wrote, Claude must use
`gmail_update_user_draft`, which requires the draft's exact current subject and refuses drafts
with attachments. Set that tool to **"Always ask"** in Claude Desktop (see below) so you
approve every change.

**Calendar.** Creating or updating events never sends invitation or update emails
(`sendUpdates = none`).

**Untrusted content.** Emails, events and files can contain text that tries to instruct an
AI. The server tells Claude to treat such content as data only. Keep write access off unless
you need it.

## Google Cloud setup

Do this once for each Google Workspace organization (you need to be its admin, or have
permission to create Cloud projects). Google renames console menus from time to time; the
names below match the console as of 2026.

### 1. Create a project

1. Open <https://console.cloud.google.com/> and sign in with an account **in the Workspace
   organization** you want to connect.
2. Click the project picker at the top, then **New project**.
3. Name it e.g. `gws-mcp`. Make sure **Organization** is your Workspace organization, then
   click **Create** and select the new project.

### 2. Enable the APIs

1. Go to **APIs & Services → Library**.
2. Search for and **Enable** each of these:
   - **Gmail API**
   - **Google Calendar API**
   - **Google Drive API**

### 3. Configure the consent screen (Internal)

1. Go to **APIs & Services → OAuth consent screen** (shown as **Google Auth Platform**).
   Click **Get started** if prompted.
2. **App information:** app name `gws-mcp`, user support email = your address. Click Next.
3. **Audience:** choose **Internal**. This limits the app to users in your organization,
   needs no Google verification, and keeps refresh tokens from expiring after 7 days.
   (If *Internal* is greyed out, the project is not inside a Workspace organization; go back
   to step 1.)
4. **Contact information:** your email. Agree to the policy and click **Create**.
5. Optional: under **Data access**, click **Add or remove scopes** and add the scopes from the
   [Security model](#security-model) table. The server requests them itself, so this step
   only documents them.

### 4. Create a Desktop OAuth client

1. Go to **Clients** (or **APIs & Services → Credentials → Create credentials → OAuth
   client ID**).
2. **Application type:** **Desktop app**. Name: `gws-mcp desktop`. Click **Create**.
3. Click **Download JSON**. Keep this file private: it identifies your app.

Repeat steps 1-4 in each additional Workspace organization. An Internal app only works for
accounts in its own organization.

## Install

Requirements: macOS (Windows and Linux also work) and [uv](https://docs.astral.sh/uv/).
uv downloads Python 3.12 for this project automatically; your system Python is not changed.

```bash
cd ~/google-workspace-mcp
uv sync            # creates .venv and uv.lock, installs dependencies
uv run gws-mcp --version
```

## Add an account

1. Create the config folder and put the client JSON in it:

   ```bash
   mkdir -p ~/.config/gws-mcp/clients
   mv ~/Downloads/client_secret_*.json ~/.config/gws-mcp/clients/your-company.json
   chmod 600 ~/.config/gws-mcp/clients/your-company.json
   cp ~/google-workspace-mcp/config.example.toml ~/.config/gws-mcp/config.toml
   ```

2. Edit `~/.config/gws-mcp/config.toml`:

   ```toml
   default_account = "work"

   [accounts.work]
   email = "you@your-company.com"
   client_secrets = "~/.config/gws-mcp/clients/your-company.json"
   write = false
   ```

   Aliases are 1-32 characters: lowercase letters, digits, `-` and `_`.

3. Authorize it. A browser window opens; sign in with **that** account and click Allow:

   ```bash
   uv run gws-mcp auth work
   ```

   The token is saved only if the account you signed in with matches `email`. On macOS you
   may be asked to allow access to the Keychain: choose **Always Allow**.

4. Check it:

   ```bash
   uv run gws-mcp accounts
   # * work   you@your-company.com   write=off  authorized
   ```

## Add to Claude Desktop

1. Find the full path of `uv` (Claude Desktop does not use your shell's `PATH`):

   ```bash
   which uv        # e.g. /opt/homebrew/bin/uv
   ```

2. In Claude Desktop open **Settings → Developer → Edit Config**. This opens
   `~/Library/Application Support/Claude/claude_desktop_config.json`. Add the server under
   `mcpServers` (keep any servers already there):

   ```json
   {
     "mcpServers": {
       "google-workspace": {
         "command": "/opt/homebrew/bin/uv",
         "args": [
           "--directory", "/Users/YOUR_USER/google-workspace-mcp",
           "run", "gws-mcp", "serve"
         ]
       }
     }
   }
   ```

   To use a config file elsewhere, add `"env": {"GWS_MCP_CONFIG": "/path/to/config.toml"}`.

3. Quit Claude Desktop completely (Cmd+Q) and open it again. The tools appear under the
   tools/connectors menu in the chat box.

4. Recommended: in the tool permissions, set `gmail_update_user_draft` (and any other write
   tool you want to approve one by one) to **Always ask**.

## Turn write access on or off

**Turn on:**

1. Set `write = true` for the account in `config.toml`.
2. Re-authorize so Google grants the extra permissions:

   ```bash
   uv run gws-mcp auth work
   ```

3. Restart Claude Desktop.

Until step 2 is done, write tools refuse with a message telling you to re-authorize.

**Turn off:**

1. Set `write = false` and restart Claude Desktop. Write tools disappear (if no other account
   has write on) and are refused for this account in any case.
2. Optional, to also drop the permissions at Google: run `uv run gws-mcp auth work` again
   (read-only scopes only), and/or remove the app's access at
   <https://myaccount.google.com/connections>.

## More accounts

Add another `[accounts.<alias>]` block and run `uv run gws-mcp auth <alias>`. Accounts from a
different Workspace organization need their own Cloud project and client JSON (see
[Google Cloud setup](#google-cloud-setup)).

With several accounts, set `default_account` or tell Claude which account to use (e.g.
"search my *home* account"). Claude can call `list_accounts` to see the aliases.

## Token storage options

| Backend | When | Setup |
|---|---|---|
| `keyring` (default) | Desktop: macOS Keychain, Windows Credential Manager | nothing |
| `encrypted_file` | Headless servers without a keyring | see below |

```bash
uv run gws-mcp gen-key            # prints a key; store it like a password
export GWS_MCP_TOKEN_KEY="<key>"
```

```toml
[storage]
backend = "encrypted_file"
encrypted_file_path = "~/.config/gws-mcp/tokens.enc"
```

The file is Fernet-encrypted (AES-128 + HMAC) and written with `0600` permissions. Without
the key it cannot be read.

Access tokens are refreshed automatically with the refresh token and the new token is saved.
If a refresh token is revoked (password change, access removed, admin policy), tools return
"Authorize it with: gws-mcp auth <alias>".

## Troubleshooting

| Symptom | Fix |
|---|---|
| `Config file not found` | Create `~/.config/gws-mcp/config.toml` or set `GWS_MCP_CONFIG`. |
| `OAuth client file not found` | Check `client_secrets` in the config. |
| `Error 403: org_internal` in the browser | You signed in with an account outside the project's organization. Use the right account, or create a project in that organization. |
| `Signed in as X, but account ... is configured for Y` | Sign in with the account in `email` (use a different browser profile if needed). |
| `Access blocked: app not verified` | The consent screen is not *Internal*. |
| `... API has not been used in project ...` | Enable the Gmail, Calendar and Drive APIs (step 2). |
| `re-auth needed` in `gws-mcp accounts` | Run `uv run gws-mcp auth <alias>`. |
| Server not showing in Claude Desktop | Use the absolute path of `uv`; check **Settings → Developer** for errors, or the logs in `~/Library/Logs/Claude/mcp*.log`. |
| Creating a file in an existing Drive folder fails | With `drive.file`, the parent folder may need to be one this server created. Create a folder with `drive_create_folder` and use that. |

Run with more logging: add `"--log-level", "DEBUG"` before `"serve"` in the Claude Desktop
args. Logs never contain tokens or message content.

## Development

```bash
uv sync
uv run pytest            # all Google API calls are mocked; no credentials needed
uv run ruff check . && uv run ruff format --check .
```

Layout:

```
src/gws_mcp/
  __main__.py        CLI: serve | auth <alias> | accounts | gen-key
  config.py          TOML config and account resolution
  scopes.py          read/write scope sets and the scope check
  logging_setup.py   stderr logging with redaction
  auth/              OAuth loopback flow, token storage, refresh
  google_clients.py  per-account API clients
  services/          Google API logic (no MCP dependency)
  tools/             MCP tool wrappers and the write guard
  server.py          builds the transport-agnostic MCP server
  entrypoints/       stdio runner (an HTTP + OAuth runner can be added here)
```

Moving to a server later only needs a new file in `entrypoints/` (Streamable HTTP with MCP
OAuth) plus `backend = "encrypted_file"`; tools and services stay unchanged.
