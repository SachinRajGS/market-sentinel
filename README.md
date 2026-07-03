# 📊 Market Sentinel

Free, always-on investment awareness system:

- **Live dashboard** (Streamlit Community Cloud) — US stocks in USD; Indian stocks, mutual funds, gold & silver in INR; BTC/ETH in USD + INR; USD/INR pair.
- **Email alerts** (GitHub Actions, every ~15 min, 24/7) — your price/percent targets, plus **volatility-aware anomaly detection**: a move is judged against *that asset's own* normal volatility, so a 2% gold move alerts while a 2% BTC move doesn't.
- **Recommendations** — rule-based, context-aware nudges (dip-in-uptrend accumulation, overbought trimming, falling-knife warnings, deep-drawdown thesis checks). Educational, not financial advice.

Total cost: **₹0**. No servers to maintain.

## Architecture

```
GitHub repo (this code + your alert targets)
├── GitHub Actions  → runs alert_engine.py every 15 min → Gmail SMTP → your inbox
└── Streamlit Cloud → hosts app.py dashboard → saves targets back to repo via GitHub API
```

Data: Yahoo Finance (stocks, indices, metals futures, USD/INR), CoinGecko (crypto), mfapi.in / AMFI (mutual fund NAVs, updated once daily after market close).

## Setup (≈15 minutes, one time)

### 1. Push to GitHub
Create a **private** repo (e.g. `market-sentinel`), then from this folder:
```bash
git init && git add -A && git commit -m "initial"
git branch -M main
git remote add origin https://github.com/<YOU>/market-sentinel.git
git push -u origin main
```

### 2. Gmail app password (for alert emails)
1. Enable 2-Step Verification on your Google account.
2. Go to <https://myaccount.google.com/apppasswords> → create app password named `market-sentinel`.
3. Copy the 16-character password.

### 3. GitHub Actions secrets
Repo → **Settings → Secrets and variables → Actions → New repository secret**:

| Secret | Value |
|---|---|
| `GMAIL_USER` | `gbsr1501@gmail.com` |
| `GMAIL_APP_PASSWORD` | the 16-char app password |
| `ALERT_TO` | `gbsr1501@gmail.com` |

Test: repo → **Actions → Market Sentinel Alerts → Run workflow**. Check the log and your inbox.

### 4. Deploy the dashboard
1. <https://share.streamlit.io> → sign in with GitHub → **New app** → pick your repo, main file `app.py`.
2. App → **Settings → Secrets**, paste:
   ```toml
   GITHUB_TOKEN = "<fine-grained PAT with Contents read/write on this repo>"
   GITHUB_REPO = "<YOU>/market-sentinel"
   ```
   (Create the token at GitHub → Settings → Developer settings → Fine-grained tokens. Without it the dashboard still works, but target edits won't persist.)

Done. The dashboard auto-refreshes every 2 min; alerts run round the clock whether or not the dashboard is open.

## Using it

- **Set targets** in the dashboard sidebar (price above/below, or ±% daily move) — saved to `config/alerts.json`, picked up by the next alert run.
- **Edit your watchlist** in `config/watchlist.json` (US/Indian tickers use Yahoo symbols — NSE needs `.NS`; mutual funds use mfapi.in scheme codes — find them at `https://api.mfapi.in/mf/search?q=<fund name>`).
- **Tune alerting** in the sidebar: anomaly alerts, technical alerts, cooldown hours (prevents repeat emails for the same condition).

## Signals explained

| Signal | Meaning |
|---|---|
| **z-score** | Today's move ÷ that asset's 90-day daily volatility. \|z\| ≥ 2 unusual, ≥ 3 extreme |
| **RSI** | ≤ 30 oversold, ≥ 75 overbought |
| **Trend** | Price vs 200-day moving average |
| **Off 1y peak** | Drawdown from 52-week high |

## Known limits (honesty section)

- Prices are near-realtime (Yahoo/CoinGecko, seconds to ~15 min depending on exchange), not tick data.
- MF NAVs update once daily (AMFI publishes at night).
- Gold/silver INR is COMEX × USD/INR — tracks MCX direction closely but sits ~6–9% below Indian retail price (no import duty/premium).
- GitHub Actions cron can drift a few minutes under load.
- Recommendations are rules, not a crystal ball. **Not financial advice.**
