# Google Sheets Export Setup Guide

This guide walks through setting up Google Cloud credentials to enable direct export of fleet carrier data to Google Sheets.

## Overview

The `--export google` option allows edapitool to write cargo data directly to a Google Sheet, making it easy to build VLOOKUP-based tracking spreadsheets that automatically update.

**Template spreadsheet**: [Carrier Cargo Tracker Template](https://docs.google.com/spreadsheets/d/1WACbf6u81fLIWsJVXsxUqYyIGZ0OCckN-Qb1FBgHAy0/edit?usp=sharing) - Make a copy to get started quickly!

**Prerequisites:**
- A Google account
- A Google Sheet to export to (or use the template above)
- ~10 minutes for initial setup

**Note**: Google Sheets API is free for personal use with generous quotas.

## Step 1: Create or Select a Google Cloud Project

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Click the project dropdown at the top of the page
3. Either:
   - Select an existing project, OR
   - Click "New Project" to create one (any name works, e.g., "ED Fleet Tracker")

## Step 2: Enable the Google Sheets API

1. In your project, go to **APIs & Services** → **Library**
2. Search for "Google Sheets API"
3. Click on it and click **Enable**
4. Wait ~30 seconds for it to propagate

**Direct link** (replace PROJECT_NUMBER with yours):
```
https://console.developers.google.com/apis/api/sheets.googleapis.com/overview?project=PROJECT_NUMBER
```

## Step 3: Configure OAuth Consent Screen

Before creating credentials, you must configure the OAuth consent screen:

1. Go to **APIs & Services** → **OAuth consent screen**
2. Select **External** user type (unless you have Google Workspace)
3. Click **Create**

### Branding Tab
Fill in the required fields:
- **App name**: `ED Fleet Tracker` (or any name)
- **User support email**: Your email
- **Developer contact email**: Your email

Click **Save and Continue**

### Scopes Tab
- Click **Add or Remove Scopes**
- Search for and add:
  - `https://www.googleapis.com/auth/spreadsheets`
  - `https://www.googleapis.com/auth/drive.file`
- Click **Update**, then **Save and Continue**

### Test Users Tab (Important!)
Since the app isn't verified, you must add yourself as a test user:

1. Click **+ Add Users**
2. Enter your Google email address (the one you'll authenticate with)
3. Click **Add**
4. Click **Save and Continue**

## Step 4: Create OAuth 2.0 Credentials

1. Go to **APIs & Services** → **Credentials**
2. Click **+ Create Credentials** → **OAuth client ID**
3. Select **Desktop app** as the application type
4. Name it (e.g., "ED API Tool Desktop")
5. Click **Create**

### Download the Credentials

1. In the OAuth 2.0 Client IDs list, find your new client
2. Click the download icon (⬇️) to download the JSON file
3. Save/rename it to: `~/.ed_gsheet_credentials.json`

**On Windows:**
```cmd
move client_secret_XXXXX.json C:\Users\YourUsername\.ed_gsheet_credentials.json
```

**On Mac/Linux:**
```bash
mv ~/Downloads/client_secret_*.json ~/.ed_gsheet_credentials.json
```

## Step 5: First-Time Authentication

Run the export command:

```bash
edapitool carrier --export google --sheet-id YOUR_SHEET_ID --client-id YOUR_FRONTIER_CLIENT_ID
```

### Finding Your Sheet ID

The Sheet ID is in the Google Sheets URL:
```
https://docs.google.com/spreadsheets/d/SHEET_ID_IS_HERE/edit
```

Example:
```
https://docs.google.com/spreadsheets/d/1aBcDeFgHiJkLmNoPqRsTuVwXyZ0123456789ABC/edit
                                      ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
                                      This is your Sheet ID
```

### OAuth Flow

1. A browser window opens to Google's login page
2. Select your Google account (must be a test user you added!)
3. You'll see a warning "Google hasn't verified this app" - click **Continue**
4. Grant access to Google Sheets
5. Browser shows "The authentication flow has completed"
6. Return to terminal - export should complete

### Token Storage

After successful auth, a token is saved to:
- `~/.ed_gsheet_token.json`

Future exports will use this token automatically (no browser needed).

## Usage Examples

### Basic Export

```bash
# Export cargo to Google Sheets
edapitool carrier --export google --sheet-id YOUR_SHEET_ID --client-id YOUR_CLIENT_ID
```

### Include Stolen/Mission Cargo

```bash
# Include cargo that's normally filtered out
edapitool carrier --export google --sheet-id SHEET_ID --include stolen,mission --client-id YOUR_CLIENT_ID
```

### Multiple Export Formats

```bash
# Export to both CSV and Google Sheets
edapitool carrier --export csv,google --sheet-id SHEET_ID --client-id YOUR_CLIENT_ID
```

### Google Sheets CSV (No API Required)

If you prefer to import manually:
```bash
# Creates a Google Sheets-formatted CSV with formulas
edapitool carrier --export gsheet --client-id YOUR_CLIENT_ID
```

Then File → Import in Google Sheets.

## Output Format

The Google Sheets export creates this layout:

| Row | A | B | C | D | E |
|-----|---|---|---|---|---|
| 1 | | | | | |
| 2 | | Display Name | Quantity | Unit Price | Total Value |
| 3 | | TOTAL | =SUM(C4:C) | | =SUM(E4:E) |
| 4 | | Aluminium | 1751 | 2122 | =C4*D4 |
| 5 | | Meta-Alloys | 6 | 14659 | =C5*D5 |
| ... | | ... | ... | ... | ... |

**Key features:**
- Column A empty for margin/formatting
- Row 1 empty for spacing
- Row 3 has formula-based totals
- Data rows have formulas for Total Value
- Sorted alphabetically by commodity name
- Filtered (no stolen/mission cargo by default)

## Troubleshooting

### "Access blocked: App has not completed the Google verification process"

You forgot to add yourself as a test user:
1. Go to **APIs & Services** → **OAuth consent screen**
2. Click **Audience** in the left sidebar
3. Under Test Users, click **+ Add Users**
4. Add your email address

### "Google Sheets API has not been used in project X"

Enable the API:
1. Go to **APIs & Services** → **Library**
2. Search "Google Sheets API"
3. Click **Enable**

### "No credentials found at ~/.ed_gsheet_credentials.json"

Download credentials:
1. Go to **APIs & Services** → **Credentials**
2. Find your OAuth 2.0 Client ID
3. Click the download icon
4. Save to `~/.ed_gsheet_credentials.json`

### "The site can't be reached" after OAuth

This happens if the local callback server times out. Just run the command again - it usually works on retry.

### Token Expired

Delete the token file and re-authenticate:
```bash
rm ~/.ed_gsheet_token.json
# Then run export again
```

## Security Notes

### Credential Files

| File | Contains | Sensitivity |
|------|----------|-------------|
| `~/.ed_gsheet_credentials.json` | OAuth client ID/secret | Medium - don't share publicly |
| `~/.ed_gsheet_token.json` | Access/refresh tokens | High - grants Sheets access |

**Never commit these files to git!**

### Scopes Requested

The tool requests minimal scopes:
- `spreadsheets` - Read/write spreadsheet data
- `drive.file` - Access only files created by or opened with the app

It cannot access your entire Google Drive or other spreadsheets you haven't explicitly opened with it.

## For Production/Distribution

If distributing this tool publicly, you would need to:

1. **Verify your OAuth consent screen** with Google
2. Update scopes documentation
3. Consider using a service account for automated workflows

For personal use, test user mode is sufficient.

## Quick Reference

```bash
# Install with Google Sheets support
pip install edapitool[gsheets]

# One-time setup
# 1. Enable Sheets API in Google Cloud Console
# 2. Create OAuth credentials (Desktop app)
# 3. Download JSON to ~/.ed_gsheet_credentials.json
# 4. Add yourself as test user in OAuth consent screen

# Export to Google Sheets
edapitool carrier --export google --sheet-id SHEET_ID --client-id CLIENT_ID

# Credentials/tokens location
~/.ed_gsheet_credentials.json  # OAuth client credentials
~/.ed_gsheet_token.json        # Saved auth tokens
```
