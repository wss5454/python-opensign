# WallaceSign (Python)

E-signature platform with **MySQL/SQLite**, per-document URLs, per-signer sign URLs, and signature widgets.

## Features

- MySQL or SQLite persistence
- Unique **document URL** per document (`/d/{token}`)
- Unique **sign URL** per signer (`/sign/{token}`)
- Per-signer **widgets** (page + x/y/w/h) for signature placement
- PDF.js signing view with canvas overlays on each widget
- Multi-signer roles: `signer`, `approver`, `viewer`
- Optional sequential signing + audit trail
- Admin login
- Email signature requests via SMTP (Bluehost-compatible)

## Database mode

Set in `.env`:

```env
# true  → SQLite (default, local file wallacesign.db)
# false → MySQL server
WALLACESIGN_USE_SQLITE=true
```

## MySQL setup

Only needed when `WALLACESIGN_USE_SQLITE=false`.

1. Start MySQL Server.
2. As root, run:

```bash
mysql -u root -p < scripts/setup_mysql.sql
```

3. Copy env file and set:

```env
WALLACESIGN_USE_SQLITE=false
WALLACESIGN_MYSQL_USER=wallacesign
WALLACESIGN_MYSQL_PASSWORD=wallacesign
WALLACESIGN_MYSQL_DATABASE=wallacesign
```

Default app DB user from the SQL script:

- host: `127.0.0.1`
- user: `wallacesign`
- password: `wallacesign`
- database: `wallacesign`

## Quick start

```bash
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
python run.py
```

Open [http://127.0.0.1:8000/login](http://127.0.0.1:8000/login)

Default admin credentials (from `.env`):

- Email: `admin@wallacesign.local`
- Password: `admin123`

Signing links (`/sign/...`) and public document links (`/d/...`) do not require login.

## Widget format

Each signer can own one or more widgets:

```json
"widgets": [
  {
    "type": "signature",
    "page": 1,
    "x": 20,
    "y": 75,
    "w": 30,
    "h": 10
  }
]
```

- `page` — 1-based PDF page number
- `x`, `y`, `w`, `h` — percentages of page width/height (WallaceSign style), origin **top-left**
- Values above `100` (e.g. `244`) are treated as a 0–1000 scale and divided by 10

On the signer’s page, a canvas is drawn exactly over each widget so they sign in-place on the document.

## URLs

| Kind | Path | Purpose |
|------|------|---------|
| Document URL | `/d/{public_token}` | Public document status + download |
| Sign URL | `/sign/{access_token}` | That signer’s signing session |

## Create document (multipart)

- `title`, `description`, `sequential`
- `file` — PDF
- `signers_json` example:

```json
[
  {
    "name": "Alice",
    "email": "alice@example.com",
    "role": "signer",
    "widgets": [
      {"type": "signature", "page": 1, "x": 20, "y": 75, "w": 30, "h": 10}
    ]
  }
]
```

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `WALLACESIGN_USE_SQLITE` | `true` | `true` = SQLite, `false` = MySQL |
| `WALLACESIGN_ADMIN_EMAIL` | `admin@wallacesign.local` | Admin login email |
| `WALLACESIGN_ADMIN_PASSWORD` | `admin123` | Admin login password |
| `WALLACESIGN_ADMIN_NAME` | `Admin` | Admin display name |
| `WALLACESIGN_SQLITE_PATH` | `./wallacesign.db` | SQLite file path |
| `WALLACESIGN_MYSQL_HOST` | `127.0.0.1` | MySQL host |
| `WALLACESIGN_MYSQL_PORT` | `3306` | MySQL port |
| `WALLACESIGN_MYSQL_USER` | `wallacesign` | MySQL user |
| `WALLACESIGN_MYSQL_PASSWORD` | `wallacesign` | MySQL password |
| `WALLACESIGN_MYSQL_DATABASE` | `wallacesign` | MySQL database |
| `WALLACESIGN_PORT` | `8000` | HTTP port |
| `WALLACESIGN_SECRET_KEY` | (dev value) | Session signing secret |
| `WALLACESIGN_PUBLIC_BASE_URL` | _(empty)_ | Public app URL used in email links (e.g. `https://sign.wallace1.com`) |
| `WALLACESIGN_MAIL_ENABLED` | `false` | Set `true` to email signers when a document is sent |
| `WALLACESIGN_SMTP_HOST` | _(empty)_ | SMTP host (Bluehost: `mail.wallace1.com`) |
| `WALLACESIGN_SMTP_PORT` | `465` | SMTP port (`465` SSL or `587` TLS) |
| `WALLACESIGN_SMTP_USE_SSL` | `true` | Use SMTP_SSL (port 465) |
| `WALLACESIGN_SMTP_USE_TLS` | `false` | Use STARTTLS (port 587) |
| `WALLACESIGN_SMTP_USER` | _(empty)_ | SMTP username (full email address) |
| `WALLACESIGN_SMTP_PASSWORD` | _(empty)_ | Email account password |
| `WALLACESIGN_MAIL_FROM` | `office@wallace1.com` | From address |
| `WALLACESIGN_MAIL_FROM_NAME` | `Wallace` | From display name |

## Email (signature links)

When `WALLACESIGN_MAIL_ENABLED=true`, sending a document emails each signer a unique `/sign/{token}` link from `office@wallace1.com` (or your configured from address).

For sequential documents, only the current signer is emailed; the next signer is emailed after the previous one completes.

Bluehost example:

```env
WALLACESIGN_MAIL_ENABLED=true
WALLACESIGN_PUBLIC_BASE_URL=https://your-app-host
WALLACESIGN_SMTP_HOST=mail.wallace1.com
WALLACESIGN_SMTP_PORT=465
WALLACESIGN_SMTP_USE_SSL=true
WALLACESIGN_SMTP_USER=office@wallace1.com
WALLACESIGN_SMTP_PASSWORD=your-email-account-password
WALLACESIGN_MAIL_FROM=office@wallace1.com
WALLACESIGN_MAIL_FROM_NAME=Wallace
```

Copy `.env.example` to `.env` and fill in the mailbox password. Restart the app after changing env vars.
