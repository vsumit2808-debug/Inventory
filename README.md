# StockWise - Inventory Sentinel (Python + Django + MySQL)

> The quiet backend job a warehouse team relies on every morning. Nobody
> notices it until it's missing - and then stock quietly runs out.

StockWise reads your stock file (CSV), compares **current quantity** against
each item's **reorder threshold**, flags anything running low, and generates
a clean **"restock needed" report** - on screen, as a web dashboard, and as
TXT/CSV files your team can automate on. Full **CRUD** is included, the
whole stack is **Python (Django) + MySQL only** (zero front-end JavaScript),
and it runs unchanged on **macOS, Windows and Linux**.

On top of the core job, two AI techniques are built in - **NLP** and **RAG** -
both running 100% inside Python (details and business rationale in
[Where the AI is used](#where-the-ai-is-used-nlp-rag--nlg)).

---

## Features

| Area | What you get |

| Low-stock engine | Loop over stock rows (dicts) -> conditional compare qty vs threshold -> collect restock list (services/stock.py) |
| Daily report | Console table + dated TXT + CSV + stable `latest_restock_report.*` for automation (`python manage.py check_stock`) |
| CRUD | Create / read / update / delete items, plus audited +/- stock adjustments with reasons |
| CSV in/out | Import with flexible headers ("Item Name" / "item" / "Current Quantity" / "qty" ...), fuzzy duplicate detection; export current stock |
| NLP assistant | Ask "which items are running low?" in plain English; intents + entity extraction; every question logged |
| RAG Q&A | Open-ended questions answered from retrieved inventory records, with visible sources |
| NLG briefing | One-sentence morning summary on the dashboard and in the console report |
| Alert history | Every daily snapshot stored in `StockAlert` for audit |
| Admin site | Django admin for all models out of the box |

---

## Tech stack (and why)

* **Python 3.10+ / Django 4.2-5.x** - the entire application. Templates are
  Django's own template language; the UI uses one CSS file and **zero
  JavaScript**, so the "Python only" promise is literal.
* **MySQL** via **PyMySQL** - a *pure-Python* MySQL driver. No compiler, no
  C dependencies, so installation is identical on Mac/Windows/Linux.
  (`cryptography` is included only because MySQL 8's default
  `caching_sha2_password` auth requires it.)
* **SQLite demo mode** - `DB_ENGINE=sqlite` gives an instant, zero-setup
  demo database using Python's built-in sqlite3. Useful for trying the app
  before pointing it at MySQL.
* No external AI APIs by default - NLP/RAG run in-process (optional LLM hook
  documented below).

---

## Quickstart

### 1. Get the code + virtual environment

**macOS / Linux**
```bash
cd stockwise
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

**Windows (PowerShell)**
```powershell
cd stockwise
py -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### 2. Choose a database

**Option A - instant demo (no MySQL install needed):**
```bash
# macOS/Linux                 |  Windows (PowerShell)
export DB_ENGINE=sqlite       |  $env:DB_ENGINE = "sqlite"
```

**Option B - MySQL (the real stack):**

Install MySQL once:
* **macOS**: `brew install mysql && brew services start mysql`
* **Ubuntu/Debian Linux**: `sudo apt install mysql-server && sudo systemctl start mysql`
* **Windows**: run the [MySQL Installer](https://dev.mysql.com/downloads/installer/)
  (choose Server 8.x + default config), or use XAMPP/WAMP's MySQL.

Create the database (one time):
```sql
CREATE DATABASE stockwise CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'stockwise'@'%' IDENTIFIED BY 'choose-a-password';
GRANT ALL PRIVILEGES ON stockwise.* TO 'stockwise'@'%';
FLUSH PRIVILEGES;
```

Then copy `.env.example` to `.env` and set:
```
DB_ENGINE=mysql
DB_NAME=stockwise
DB_USER=stockwise
DB_PASSWORD=choose-a-password
DB_HOST=127.0.0.1
DB_PORT=3306
```

### 3. Migrate, seed, run

```bash
python manage.py migrate
python manage.py seed_demo          # loads data/sample_stock.csv (15 items, 6 flagged)
python manage.py runserver
```
Open http://127.0.0.1:8000 - the dashboard already shows low-stock flags,
the morning briefing and the restock table.

Have your own CSV? `python manage.py import_csv path/to/file.csv` (add
`--update` to update matching items instead of skipping duplicates).

---

## The daily job

```bash
python manage.py check_stock
```

What happens, in order:
1. Loops through every active item, compares `quantity <= reorder_threshold`
   and collects everything that needs restocking (pure dict logic in
   `inventory/services/stock.py::evaluate_rows`).
2. Writes `StockAlert` snapshots (history/audit).
3. Prints a formatted console report.
4. Writes `reports/restock_report_YYYY-MM-DD.txt`, `.csv` and stable
   `latest_restock_report.*` copies.
5. Optional: `--email` sends it (configure `EMAIL_*` + `STOCK_ALERT_EMAIL_TO`).
6. Exit code: `0` = all healthy, `2` = restock needed (handy for scripts).

Flags: `--quiet` (summary only), `--no-files`, `--report-dir <path>`, `--no-exit`.

### Scheduling

**macOS / Linux (cron)** - every day 07:00:
```cron
0 7 * * * cd /path/to/stockwise && .venv/bin/python manage.py check_stock --quiet >> reports/cron.log 2>&1
```

**Linux (systemd timer alternative)**
```ini
# /etc/systemd/system/stockwise.service
[Service]
WorkingDirectory=/path/to/stockwise
ExecStart=/path/to/stockwise/.venv/bin/python manage.py check_stock
```

**Windows Task Scheduler**
```powershell
schtasks /create /tn "StockWise Daily Check" /sc daily /st 07:00 /tr ^
  "cmd /c cd /d C:\path\to\stockwise && .venv\Scripts\python.exe manage.py check_stock --quiet"
```
(or use Task Scheduler's GUI: Daily action -> start program
`.venv\Scripts\python.exe` -> arguments `manage.py check_stock --quiet` ->
start-in the project folder.)

---

## CSV format

Headers are matched flexibly (case/spacing/synonyms):

| Canonical field | Accepted headers (examples) |
|---|---|
| name | `Item Name`, `item`, `product`, `name` |
| quantity | `Current Quantity`, `qty`, `stock`, `on hand` |
| reorder_threshold | `Reorder Threshold`, `threshold`, `reorder level`, `min` |
| reorder_quantity | `Reorder Quantity`, `order quantity` |
| unit_price | `Unit Price`, `price`, `cost` |
| sku / category / supplier / location / notes | as expected |

Minimum viable file:
```csv
Item Name,Current Quantity,Reorder Threshold
A4 Paper,120,50
Ballpoint Pens,8,40
```

**Fuzzy duplicate guard (NLP):** an incoming row whose name is >= 87%
similar to an existing item (e.g. "A4 Paper" vs "A4 paper ream") is skipped
with a warning, or updates that item with `--update` / the web checkbox -
so re-imports never silently double your stock.

---

## Where the AI is used (NLP, RAG & NLG)

Both techniques run **inside Python, offline, at zero per-query cost**; no
inventory data leaves your server. An optional LLM hook is documented below.

### 1. NLP - natural-language questions & smart matching
* **Where:** Assistant page (`inventory/nlp/intent.py`,
  `inventory/nlp/assistant.py`) and CSV import (`inventory/services/csvio.py`).
* **How:** free-text questions are classified into an *intent*
  (low-stock, item quantity, item status, category, overview, help) with a
  weighted pattern classifier; *entities* (which item/category) are resolved
  with fuzzy matching (`difflib` + token-set similarity). The intent+entity
  pair is answered directly from live MySQL data - exact numbers, exact rows.
  The same fuzzy matcher de-duplicates CSV imports.
* **Meaning:** staff don't learn query syntax - they ask in plain English.
* **Benefit to you:** faster answers on the floor; fewer import mistakes;
  `QueryLog` shows what the team asks most (future automation candidates).
* **Benefit to client:** less training, fewer duplicate-stock errors, an
  assistant that works on day one.

### 2. RAG - retrieval-augmented generation for open questions
* **Where:** `inventory/rag/index.py` (dependency-free TF-IDF vector index),
  `retriever.py` (top-k retrieval over live items), `generator.py`
  (grounded answer synthesis).
* **How:** every active item becomes a document bundling its facts (name,
  SKU, category, supplier, location, quantity, threshold, status, notes).
  A question is vectorised the same way; the k most similar records are
  retrieved; the answer is generated *strictly from those records* and shown
  with its **sources** (items + relevance scores). Example: *"who supplies
  the laser toner and where is it stored?"* -> retrieves the toner record ->
  "PrintSupply Ltd - stored at: Storage B - Cabinet 1".
* **Why RAG here:** it lets users ask questions nobody pre-programmed, while
  staying grounded - the generator cannot invent stock levels because it
  only sees retrieved rows, and the UI shows which rows produced the answer.
* **Benefit to you:** answers to "unscripted" questions without writing new
  reports; auditability via visible sources.
* **Benefit to client:** no hallucinated numbers, no data leaving their
  infrastructure, no per-query API cost.

### 3. NLG - the morning briefing
* **Where:** `inventory/nlp/summary.py` - dashboard card + `check_stock`
  console output.
* **How:** counters (healthy/low/out, biggest shortfalls) are rendered into
  one readable sentence with deterministic templates (same data -> same
  words -> auditable).
* **Benefit:** managers get a status paragraph before coffee; no table
  required.

### Optional LLM upgrade (still pure Python)
Set in `.env` to refine RAG wording with any OpenAI-compatible API:
```
RAG_LLM_ENABLED=1
RAG_LLM_BASE_URL=https://api.openai.com/v1
RAG_LLM_API_KEY=sk-...
RAG_LLM_MODEL=gpt-4o-mini
```
Retrieval and grounding are unchanged; the offline template synthesiser
remains the automatic fallback if the API errors.

---

## Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `DB_ENGINE` | `mysql` | `mysql` or `sqlite` (instant demo) |
| `DB_NAME/USER/PASSWORD/HOST/PORT` | `stockwise/root//127.0.0.1/3306` | MySQL connection |
| `DJANGO_SECRET_KEY` | dev key | set a real one in production |
| `DJANGO_DEBUG` | `1` | set `0` in production |
| `DJANGO_ALLOWED_HOSTS` | `*` | comma-separated hosts |
| `TIME_ZONE` | `Asia/Kolkata` | any IANA zone |
| `CURRENCY_SYMBOL` | `$` | used in reports/UI |
| `REPORT_DIR` | `./reports` | where daily reports are written |
| `EMAIL_*`, `STOCK_ALERT_EMAIL_TO` | unset | optional report email |
| `RAG_LLM_*` | unset | optional LLM for RAG wording |

---

## Testing

```bash
python manage.py test
```
25 tests cover the low-stock engine (boundary `qty == threshold`), CRUD via
the test client, CSV aliases + fuzzy dedupe, the `check_stock` job (files +
alerts, same-day de-dup), intent classification, entity extraction, RAG
retrieval/grounding, and the assistant flow.

---

## Troubleshooting

* **`Building wheel for cryptography ... error` / `openssl-sys` / Rust errors
  during `pip install -r requirements.txt`** - your Python/platform has no
  prebuilt wheel for the newest `cryptography` release, so pip tried to
  compile it from source (needs Rust + OpenSSL). The project already caps
  `cryptography<49` to force prebuilt wheels. If you still hit it, run:
  ```bash
  pip install "cryptography>=41,<49"
  ```
  or skip the package entirely with one of these:
  * demo without MySQL: `export DB_ENGINE=sqlite` (Windows PowerShell:
    `$env:DB_ENGINE = "sqlite"`) - cryptography is not used at all;
  * switch your MySQL user to native auth:
    `ALTER USER 'stockwise'@'%' IDENTIFIED WITH mysql_native_password BY 'yourpassword';`
  * use a mature Python (3.12 or 3.13) for the venv - wheels exist for every platform.
  StockWise also raises a friendly `stockwise.W001` warning at startup when
  MySQL is configured but cryptography is missing.
* **`Can't connect to MySQL server`** - MySQL isn't running, or creds/host
  wrong. Test: `mysql -u stockwise -p -h 127.0.0.1 stockwise`. In a hurry?
  `export DB_ENGINE=sqlite` to demo without MySQL.
* **`cryptography is required for sha256_password/caching_sha2_password`**
  - `pip install "cryptography<49"` (see first bullet).
* **Windows PowerShell blocks venv activation** -
  `Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser`.
* **`No module named MySQLdb`** - make sure you run from the project root so
  `stockwise/__init__.py` (the PyMySQL shim) is loaded; it is automatic.
* **Port already in use** - `python manage.py runserver 127.0.0.1:8001`.

## Production notes (brief)

Set `DJANGO_DEBUG=0`, a strong `DJANGO_SECRET_KEY`, real
`DJANGO_ALLOWED_HOSTS`, run `python manage.py collectstatic` and serve
`staticfiles/` with any web server (nginx/IIS/Caddy); run the app under
gunicorn (`Linux/macOS`) or waitress (`Windows`). Both are pure Python:
`pip install gunicorn` / `pip install waitress`.

## Project structure

```
stockwise/
  manage.py
  requirements.txt
  .env.example                  # copy to .env
  data/sample_stock.csv         # demo stock file
  reports/                      # generated TXT/CSV reports land here
  stockwise/                    # project settings (MySQL via env vars)
  inventory/
    models.py                   # Item, StockMovement, StockAlert, QueryLog
    views.py / urls.py / forms.py
    services/stock.py           # low-stock engine + report builder
    services/csvio.py           # CSV import/export + fuzzy dedupe
    nlp/intent.py               # intent classifier + entity extraction
    nlp/assistant.py            # hybrid NLP -> RAG pipeline
    nlp/summary.py              # NLG morning briefing
    rag/index.py                # pure-Python TF-IDF index
    rag/retriever.py            # documents from live items + top-k search
    rag/generator.py            # grounded synthesis (+ optional LLM hook)
    management/commands/check_stock.py    # the daily sentinel
    management/commands/import_csv.py
    management/commands/seed_demo.py
    templates/inventory/        # zero-JS templates
    static/inventory/styles.css
```
