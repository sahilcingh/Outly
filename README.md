# B2B Prospecting Agent (starter)

Pipeline today: **Search → Scrape → Clean → Chunk → Draft (Gemini) → Save to SQLite**.

## Setup (Python)

Create a virtualenv, then install dependencies:

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

Create your env file:

```bash
copy .env.example .env
```

Set `GEMINI_API_KEY` in `.env`.

## Run

Full pipeline (requires `GEMINI_API_KEY`):

```bash
python main.py "Acme Corp"
```

**Dynamic prospecting context** (optional; prompts adapt to these strings; no hardcoded ICP in code):

- Defaults if omitted: industry `B2B Company`, job title `Decision Maker`.

```bash
python main.py "Acme Corp" --industry "Healthcare SaaS" --job-title "Chief Medical Officer"
python main.py "Acme Corp" --sequence --industry "Manufacturing" --job-title "Head of Operations"
```

Skip drafting (only search/scrape/clean/chunk):

```bash
python main.py "Acme Corp" --no-draft
```

Limit URLs:

```bash
python main.py "Acme Corp" --top 3
```

Review workflow:

```bash
python main.py --list
python main.py --approve 1
python main.py --mark-sent 1
```

## Data

- Drafts DB is stored at `data/drafts.db` (created automatically).
- Do not commit `.env` or `data/` (see `.gitignore`).

