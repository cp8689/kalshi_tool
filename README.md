# Speech Word Market Model

Estimate **P(word appears in next speech)** using rolling 4-week transcript stats and recent news narrative signals, then compare to Kalshi prediction market prices to identify potential betting edges.

## Goal

- Compute a model probability for each tracked word (e.g. "border", "china", "tariff").
- Compare to Kalshi contract prices (e.g. "Will Trump say 'border'?").
- Output **edge** = model probability − market probability; flag opportunities when edge > 10%.

---

## Quick start

Run everything from the **repo root** (this directory).

### 1. Setup (once)

```bash
python3 -m venv .venv
source .venv/bin/activate    # macOS/Linux; Windows: .venv\Scripts\activate
pip install -r requirements.txt
python -c "import nltk; nltk.download('stopwords')"   # once
```

Without a venv, use `pip install -r requirements.txt` and `python` if they’re on your PATH.

### 2. Commands

| Command | What it does |
|--------|----------------|
| `python main.py` | Run the full pipeline (ingest → weekly model → narrative → Kalshi → edges) and write `output/*.csv`. |
| `python main.py --run-pipeline` | Same as above. |
| `python main.py --dashboard` | Launch the Streamlit dashboard (top edges, word probabilities, weekly trends). |
| `python main.py --config /path/to/config.json` | Run the pipeline with a custom config file. |
| `python scripts/fetch_transcripts.py` | Clear existing transcript/news/market data (keeps samples), then fetch transcripts (White House briefings, YouTube, transcript URLs from `data/transcript_sources.json`). |
| `python scripts/fetch_transcripts.py --dry-run` | List what would be fetched; no files deleted or written. |
| `python scripts/fetch_transcripts.py --output-dir path/to/dir` | Write fetched transcripts to a different directory. |
| `streamlit run scripts/dashboard.py` | Same as `python main.py --dashboard` (run dashboard directly). |

### 3. Typical workflow

```bash
python scripts/fetch_transcripts.py   # fetch latest transcripts (clears then downloads)
python main.py                        # run pipeline, update model and output CSVs
python main.py --dashboard            # open dashboard (or: streamlit run scripts/dashboard.py)
```

The repo includes sample transcripts, news, and Kalshi market data so the pipeline and dashboard work without fetching.

---

## Project structure

```
kalshi_tool/                    # repo root
├── config.json                 # Tracked words, weights, multipliers (see Configuration)
├── main.py                     # CLI: run pipeline or launch dashboard
├── requirements.txt
├── README.md
├── .gitignore
├── data/
│   ├── transcripts/            # Input .txt / .json; output: processed_transcripts.json
│   ├── news/                   # Input .json; output: processed_news.json
│   └── markets/                # Input .json or .csv (Kalshi contracts)
├── output/
│   ├── word_probabilities.csv
│   └── kalshi_edges.csv
└── scripts/
    ├── ingest_transcripts.py   # Module 1: load & tokenize transcripts
    ├── ingest_news.py          # Module 5 (ingest): load news
    ├── tokenizer.py            # Module 2: lowercase, strip punctuation, stopwords
    ├── weekly_stats.py         # Module 3: 4-week P(word | week)
    ├── probability_model.py    # Module 4: recency-weighted baseline
    ├── narrative_model.py      # Module 5: news multipliers, cap 0.95
    ├── kalshi_parser.py        # Module 6: parse markets, extract word + prob
    ├── edge_detector.py        # Module 7: edge = model − market, flag > 0.10
    ├── scheduler.py            # Module 8: run_pipeline()
    ├── dashboard.py            # Module 10: Streamlit UI
    ├── schemas.py              # Data contracts (bonus)
    ├── speech_length_model.py  # Stub (bonus)
    ├── topic_model.py          # Stub (bonus)
    └── alerting.py             # Stub (bonus)
```

---

## Install

From the **repo root**:

1. **Create and activate a venv** (so `pip` and `python` point to the venv):
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate   # macOS/Linux; on Windows: .venv\Scripts\activate
   ```
2. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```
3. **NLTK stopwords** (once):
   ```bash
   python -c "import nltk; nltk.download('stopwords')"
   ```

If you see **`zsh: command not found: pip`**, the venv is not activated. Run `source .venv/bin/activate` from the repo root, then run `pip` again. Do not run `activate_this.py` or `activate.bat` as a script—use `source .venv/bin/activate` so the shell picks up the venv.

---

## Configuration

Edit **`config.json`** at the repo root.

| Key | Description |
|-----|-------------|
| **`tracked_words`** | List of words to predict (e.g. border, china, tariff). |
| **`stopwords`** | Extra stopwords to remove when tokenizing (optional; NLTK English stopwords are always included). |
| **`recency_weights`** | Four weights for the last 4 weeks, most recent first. Must sum to 1. |
| **`news_multipliers`** | Narrative adjustment by mention count in last 48h: `"0"`, `"1"`, `"3"`, `"5"` (5+ mentions). |
| **`edge_threshold`** | Flag opportunities when edge > this value (default `0.10`). |
| **`reference_date`** | (Optional) `YYYY-MM-DD` for "today" when defining the last 4 weeks. Omit to use current date. **Must be on or after your latest transcript date**—otherwise those transcripts fall outside the 4-week window and won't affect `model_probability`. |

**Example `config.json`:**

```json
{
  "reference_date": "2025-03-08",
  "tracked_words": [
    "border",
    "china",
    "tariff",
    "immigration",
    "crime",
    "economy",
    "inflation",
    "energy",
    "biden",
    "military"
  ],
  "stopwords": [],
  "recency_weights": [0.1, 0.2, 0.3, 0.4],
  "news_multipliers": {
    "0": 0.9,
    "1": 1.1,
    "3": 1.4,
    "5": 1.8
  },
  "edge_threshold": 0.10
}
```

- **0 mentions** → multiplier 0.9  
- **1–2 mentions** → 1.1  
- **3–4 mentions** → 1.4  
- **5+ mentions** → 1.8  

Then: **P_adjusted = min(0.95, P_final × multiplier)**.

---

## Pipeline (how it runs)

When you run `python main.py` from the repo root:

1. **Ingest transcripts** — Read `data/transcripts/`, parse date from filenames, tokenize, write `processed_transcripts.json`.
2. **Weekly stats** — Bucket speeches into last 4 weeks; compute P(word | week) = speeches_containing_word / total_speeches per week.
3. **Baseline model** — P_final = 0.4×week4 + 0.3×week3 + 0.2×week2 + 0.1×week1 (configurable weights).
4. **Ingest news** — Read `data/news/`, write `processed_news.json`.
5. **Narrative adjustment** — Count tracked-word mentions in last 48h; apply multiplier (0.9 / 1.1 / 1.4 / 1.8); P_adjusted = min(0.95, P_final × multiplier).
6. **Ingest Kalshi** — Parse `data/markets/`, extract word and market probability from contract names.
7. **Edge detection** — edge = model_probability − market_probability; flag when edge > 0.10.
8. **Export** — Write `output/word_probabilities.csv` and `output/kalshi_edges.csv`.

### Modules at a glance

| Module | Role |
|--------|------|
| `ingest_transcripts.py` | Read transcripts (manual + optional YouTube), parse date from filename, tokenize, save JSON. |
| `tokenizer.py` | Lowercase, remove punctuation and stopwords, return token list (no I/O). |
| `weekly_stats.py` | Bucket transcripts into 4 rolling weeks; P(word \| week) = speeches_with_word / total_speeches. |
| `probability_model.py` | Recency-weighted baseline: P_final = w1×week1 + … + w4×week4. |
| `ingest_news.py` | Read news from `data/news/`, write `processed_news.json`. |
| `narrative_model.py` | Count word mentions in last 48h news, apply multiplier, P_adjusted = min(0.95, P_final × multiplier). |
| `kalshi_parser.py` | Parse Kalshi JSON/CSV; extract word from contract name; output word + market_probability. |
| `edge_detector.py` | edge = model_probability − market_probability; flag when edge > threshold. |
| `scheduler.py` | `run_pipeline(config_path, base_dir)` runs all steps and writes CSVs. |
| `dashboard.py` | Streamlit: top edges, probability distribution, weekly trends. |

---

## Data inputs

### Adding transcripts

1. **Manual files**: Put transcript text files in **`data/transcripts/`** with names like `YYYY-MM-DD_source.txt` (e.g. `2025-02-15_rally.txt`). The date prefix is required; the rest is the source label.
2. **JSON**: You can also add JSON files with `date`, `text`, and optional `source`/`body`.
3. **YouTube**: Save captions as text or JSON in the same folder with a date in the filename, or use the fetch script below.

**Fetching Kalshi-relevant transcripts (State of the Union / major speeches / press)**  
Kalshi’s word markets refer to events like “next major speech” and State of the Union. You can fetch those transcripts with:

```bash
python scripts/fetch_transcripts.py
```

The script **deletes existing data** before fetching: all transcript `.txt` and `processed_transcripts.json` in `data/transcripts/`; all news `.json` and `processed_news.json` in `data/news/` (keeps `sample_*.json`, `example*.json`); all market `.json`/`.csv` in `data/markets/` (keeps `kalshi_sample.json`, `*example*`). Each run then fetches transcripts only (news/markets are cleared; add or fetch those separately if needed). Use `--dry-run` to preview without deleting or writing.

- **Config**: Edit **`data/transcript_sources.json`**.
  - **Per-item sources**: In `sources`, each entry needs `date` (`YYYY-MM-DD`), `source` (label), and either **`youtube_url`** or **`transcript_url`**.
  - **White House Briefings & Statements**: Set **`whitehouse_briefings`** to scrape [whitehouse.gov/briefings-statements](https://www.whitehouse.gov/briefings-statements/). Use `"url": "https://www.whitehouse.gov/briefings-statements/"` and optionally `"max_items": 25`. The script fetches the listing, then each linked statement/remarks page, and saves them as `YYYY-MM-DD_slug.txt` in `data/transcripts/`.
- **YouTube**: Uses **yt-dlp** (install separately: `pip install yt-dlp` or `brew install yt-dlp`) to download captions and save as `YYYY-MM-DD_source.txt` in `data/transcripts/`.
- **Transcript URL**: Fetches the page with `requests` and extracts main text (e.g. official or news SOTU transcript pages).
- **Dry run**: `python scripts/fetch_transcripts.py --dry-run` to list what would be fetched without writing files.

After adding or fetching files, **run the full pipeline** so the model updates: `python main.py`. That regenerates **`data/transcripts/processed_transcripts.json`** and recomputes weekly stats and **model_probability**. If you use **reference_date** in config, set it to a date on or after your newest transcript (e.g. **2026-03-08** if you have Feb–Mar 2026 White House briefings); otherwise those transcripts are excluded from the 4-week window.

### Adding news

Put news items in **`data/news/`** as JSON with `date` (`YYYY-MM-DD`) and `text` (or `body`/`content`). The narrative model uses only items from the **last 48 hours** (by date).

### Adding Kalshi market data

Put Kalshi data in **`data/markets/`** as JSON or CSV.

- **JSON**: Array of objects, or object with `"markets"` array. Each object: `contract_name` (or `title`/`name`) and `market_probability` (or `last_price`/`yes_bid`, 0–1).
- **CSV**: Columns `contract_name` (or `title`/`name`) and `market_probability` (or `last_price`/`yes_bid`).

The parser matches **tracked words** in the contract title (including quoted words).

---

## CLI reference

Run all commands from the **repo root**.

| Command | Description |
|---------|-------------|
| `python main.py` | Run the full pipeline (default), then exit. |
| `python main.py --run-pipeline` | Same: ingest → weekly model → news → narrative → Kalshi → edges → export. |
| `python main.py --dashboard` | Launch the Streamlit dashboard (blocks until you stop it). |
| `python main.py --config /path/to/config.json` | Use a custom config file. |

Dashboard alternative:

```bash
streamlit run scripts/dashboard.py
```

The app reads **`output/`** in the repo root.

---

## Output files

Written to **`output/`** after each pipeline run.

**`word_probabilities.csv`**

| Column | Description |
|--------|-------------|
| `word` | Tracked word. |
| `week1` | P(word \| week) for the most recent 7 days. |
| `week2` | P(word \| week) for the prior 7 days. |
| `week3` | P(word \| week) for the week before that. |
| `week4` | P(word \| week) for the oldest of the 4 weeks. |
| `model_probability` | Final model probability (after narrative adjustment, cap 0.95). |
| `model_probability_baseline` | Baseline before narrative (optional column). |

**`kalshi_edges.csv`**

| Column | Description |
|--------|-------------|
| `word` | Tracked word. |
| `market_probability` | Probability from Kalshi contract (0–1). |
| `model_probability` | Model probability. |
| `edge` | model_probability − market_probability. Positive = model sees word as more likely than market. |
| `flagged` | `True` when edge > `edge_threshold` (e.g. 0.10). |

**Edge percentage:** `edge_pct = edge × 100`. Example: edge +0.17 → +17% edge.

---

## Dashboard

```bash
python main.py --dashboard
```

or

```bash
streamlit run scripts/dashboard.py
```

Shows: **top edges** (sorted by edge), **flagged opportunities** (edge > threshold), **word probability distribution** (bar chart), **weekly trends** (line chart for week1–week4).

---

## How edge detection works

- **Model probability**: Recency-weighted average of P(word | week) over the last 4 weeks, then multiplied by a narrative factor (0.9–1.8) from news mentions in the last 48 hours. Capped at 0.95.
- **Market probability**: From Kalshi contract data (e.g. last price or yes bid).
- **Edge** = model probability − market probability. Positive edge = model thinks the word is more likely than the market.
- **Flagged**: Contracts where edge > `edge_threshold` (default 0.10) are highlighted as potential opportunities.

---

## Scheduling (daily run)

Example cron (run at 9:00 daily from repo root):

```bash
0 9 * * * cd /path/to/kalshi_tool && python main.py
```

---

## Dependencies

From **`requirements.txt`**:

- **pandas** — DataFrames for weekly stats, probabilities, edges.
- **python-dateutil** — Date parsing.
- **nltk** — English stopwords (run `nltk.download('stopwords')` once).
- **requests** — Optional: fetch URLs (e.g. captions).
- **beautifulsoup4** — Optional: parse HTML in news files.
- **streamlit** — Dashboard.

Optional for **fetching transcripts** from YouTube: **yt-dlp** (`pip install yt-dlp` or `brew install yt-dlp`).

Install: `pip install -r requirements.txt`

---

## Bonus / future features

The codebase is structured to support:

- **Real-time speech transcription**: Ingest script can accept a live transcript path or callback.
- **Speech length prediction**: Optional metadata (word count / duration) and a separate model stub.
- **Topic modeling**: Stub for a module that consumes token lists and outputs topic weights.
- **Multi-speaker models**: Config can include `speaker_id` or filter by source.
- **Trading alerts**: Stub for reading `kalshi_edges.csv` and sending email/webhook when edge exceeds a threshold.

See **`scripts/schemas.py`** for data contracts and extension points.

---

## Troubleshooting

| Issue | Fix |
|-------|-----|
| **`zsh: command not found: pip`** | Activate the venv first: `source .venv/bin/activate` (from repo root). Then `pip` and `python` use the venv. |
| **`permission denied: .../activate_this.py`** or **`activate.bat`** | Don’t run those as scripts. Use `source .venv/bin/activate` (macOS/Linux) so your current shell gets the venv’s PATH. |
| **`python: command not found`** | Use `python3` to create the venv and run the app, or after activating the venv use `python`. |
| **`Could not find platform independent libraries`** / **`No module named 'encodings'`** | The venv is broken (base Python moved or venv recreated with a different interpreter). Recreate it: `deactivate 2>/dev/null; rm -rf .venv && python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt`. Then run NLTK download with the venv’s Python: `python -c "import nltk; nltk.download('stopwords')"`. |
