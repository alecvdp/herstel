# Herstel

Recovery meetings tracker — a Streamlit web app for logging and reviewing recovery meetings.

## Setup

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Data

All data is stored locally in the `data/` directory (gitignored):

- `data/meetings_log.csv` — your meeting attendance log
- `data/config.json` — settings (sobriety date, fellowship list)

The app creates these files automatically on first run. You can export your data as CSV, JSON, or Markdown from within the app.
