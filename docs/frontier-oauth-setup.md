# Frontier OAuth2 Developer Setup Guide

This guide walks through registering an OAuth2 application with Frontier Developments to access the Elite Dangerous Companion API (CAPI).

**Time required**: ~5-10 minutes

## Overview

The Companion API uses OAuth2 with PKCE (Proof Key for Code Exchange) for authentication. You need to register a "client" application with Frontier before you can authenticate users.

## Step 1: Create a Frontier Developer Account

1. Go to **https://user.frontierstore.net/** and log in with your Frontier account
2. Navigate to the Developer section or go directly to:
   - **https://auth.frontierstore.net/client/signup** (new client registration)
   - **https://user.frontierstore.net/developer** (manage existing clients)

## Step 2: Register Your Application

Fill out the registration form:

| Field | Description | Example |
|-------|-------------|---------|
| **Application Name** | Display name users will see during auth | `ED API Tool` |
| **Description** | What your app does | `Fleet carrier inventory tracking` |
| **Homepage URL** | Your project's website (can be GitHub) | `https://github.com/djdarcy/EDAPITool` |
| **Redirect URI** | Where Frontier sends the auth code | See below |

### Redirect URI - Important!

This is the trickiest part. Frontier's validator is picky about what it accepts.

#### What DOESN'T Work

```
http://localhost:8085/callback     ❌ REJECTED - "Error adding endpoint"
http://127.0.0.1:8085/callback     ❌ REJECTED
http://localhost/callback          ❌ REJECTED (no port, but still http)
```

#### What DOES Work

```
https://localhost/callback         ✅ ACCEPTED
https://localhost:8443/callback    ✅ ACCEPTED (if you need a specific port)
```

**Key insight**: Frontier requires `https://` for the scheme, even for localhost. This is a common source of confusion.

### The Workaround

Even though we register `https://localhost/callback`, our local OAuth server runs on HTTP (port 8085). This still works because:

1. Browser opens Frontier auth page
2. User logs in and approves
3. Frontier redirects to `https://localhost/callback?code=XXX`
4. Browser shows SSL error (expected - we're not running HTTPS locally)
5. **Manual flow**: User copies the URL from browser and pastes it, OR
6. **Auto flow**: Our HTTP server on port 8085 captures it anyway (some browsers follow redirects loosely)

For reliability, edapitool supports both automatic capture and manual code entry (`--manual-auth` flag).

## Step 3: Note Your Client ID

After registration, you'll receive a **Client ID** (UUID format):

```
xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
```

**Important**:
- There is NO client secret for public/native apps (PKCE replaces it)
- Keep your client ID accessible but it's not highly sensitive
- Each client ID has rate limits tied to it

## Step 4: Test Authentication

```bash
# First-time auth (opens browser)
edapitool auth --client-id YOUR_CLIENT_ID

# If automatic redirect doesn't work, use manual mode
edapitool auth --client-id YOUR_CLIENT_ID --manual-auth
```

### Manual Auth Flow

1. Command prints an authorization URL
2. Open URL in browser, log in to Frontier
3. Approve the application
4. Browser redirects to `https://localhost/callback?code=XXXXX`
5. Copy the ENTIRE URL from the browser address bar
6. Paste it back into the terminal
7. Tool extracts the code and exchanges it for tokens

## How OAuth2 + PKCE Works

```
┌─────────────┐                              ┌─────────────────┐
│  edapitool  │                              │ Frontier Auth   │
└──────┬──────┘                              └────────┬────────┘
       │                                              │
       │ 1. Generate code_verifier (random string)    │
       │ 2. Create code_challenge = SHA256(verifier)  │
       │                                              │
       │ 3. Open browser with auth URL ───────────────►
       │    (includes code_challenge)                 │
       │                                              │
       │                              User logs in ◄──┤
       │                              User approves ◄─┤
       │                                              │
       │ 4. Receive auth code ◄───────────────────────┤
       │    (via redirect to localhost)               │
       │                                              │
       │ 5. Exchange code + verifier for tokens ──────►
       │                                              │
       │ 6. Receive access_token + refresh_token ◄────┤
       │                                              │
       │ 7. Use access_token to call CAPI             │
       └──────────────────────────────────────────────┘
```

PKCE prevents authorization code interception attacks - even if someone captures the auth code, they can't exchange it without the original `code_verifier`.

## Token Storage

Tokens are stored locally in:
- `~/.ed_capi_tokens.json` (default)

The file contains:
```json
{
  "access_token": "eyJ...",
  "refresh_token": "eyJ...",
  "expires_at": 1234567890
}
```

**Security note**: This file contains sensitive tokens. Don't share it or commit it to git.

## Token Lifecycle

| Token | Lifespan | Notes |
|-------|----------|-------|
| Access Token | ~4 hours | Used for API calls |
| Refresh Token | ~25 days | Used to get new access tokens |

edapitool automatically refreshes expired access tokens. If the refresh token expires, you'll need to re-authenticate.

## Troubleshooting

### "Error adding endpoint" when registering

- Make sure you're using `https://` not `http://`
- Try `https://localhost/callback` (no port number)

### Browser shows SSL certificate error

- This is expected when using `https://localhost`
- Use `--manual-auth` mode and copy the URL manually
- Or click "Advanced" → "Proceed anyway" in Chrome

### "Token refresh failed"

- Refresh token may have expired (after ~25 days of inactivity)
- Delete `~/.ed_capi_tokens.json` and re-authenticate

### "Rate limited" or slow responses

- Fleet carrier endpoint has 15-minute cooldown
- General CAPI calls should be spaced 1+ minute apart
- Different client IDs have separate rate limits

## API Endpoints

Once authenticated, you can access:

| Endpoint | Description | Cooldown |
|----------|-------------|----------|
| `/profile` | Commander info, credits, rank | ~1 min |
| `/market` | Current station market data | ~1 min |
| `/shipyard` | Current station ships | ~1 min |
| `/fleetcarrier` | Fleet carrier data | **15 min** |

Base URLs:
- Live: `https://companion.orerve.net/`
- Legacy: `https://legacy-companion.orerve.net/`

## References

- [Frontier OAuth2 Instructions](https://hosting.zaonce.net/docs/oauth2/instructions.html)
- [EDMC companion.py](https://github.com/EDCD/EDMarketConnector/blob/main/companion.py) - Reference implementation
- [fd-api CAPI docs](https://github.com/Athanasius/fd-api/blob/main/docs/FrontierDevelopments-CAPI-endpoints.md) - Endpoint documentation

## Example Client Registration

Here's what a successful registration looks like:

```
Application Name: ED API Tool
Description: Fleet carrier inventory tracking and export tool
Homepage: https://github.com/djdarcy/EDAPITool
Redirect URI: https://localhost/callback

→ Client ID: xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
```

This client ID is used with edapitool:
```bash
edapitool carrier --client-id YOUR_CLIENT_ID
```
