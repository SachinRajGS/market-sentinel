"""Market Sentinel — live dashboard (Streamlit Community Cloud).
Targets set here are saved to config/alerts.json in your GitHub repo (via
GITHUB_TOKEN secret) so the Actions alert engine picks them up automatically."""
import base64
import json
import os

import pandas as pd
import requests
import streamlit as st
from streamlit_autorefresh import st_autorefresh

from alert_engine import gather_assets, fmt_inr, load_json, ROOT
from core.indicators import snapshot
from core.recommend import recommend

st.set_page_config(page_title="Market Sentinel", page_icon="📊", layout="wide")
st_autorefresh(interval=120_000, key="auto")  # refresh every 2 min

ALERTS_PATH = "config/alerts.json"


# ---------- alerts.json persistence (GitHub repo if secrets set, else local) ----------

def gh_conf():
    try:
        return st.secrets["GITHUB_TOKEN"], st.secrets["GITHUB_REPO"]  # e.g. "user/market-sentinel"
    except Exception:
        return None, None


def read_alerts():
    token, repo = gh_conf()
    if token:
        r = requests.get(f"https://api.github.com/repos/{repo}/contents/{ALERTS_PATH}",
                         headers={"Authorization": f"Bearer {token}"}, timeout=15)
        if r.ok:
            d = r.json()
            return json.loads(base64.b64decode(d["content"])), d["sha"]
    return load_json(os.path.join(ROOT, ALERTS_PATH), {"settings": {}, "targets": []}), None


def write_alerts(cfg, sha):
    token, repo = gh_conf()
    body = json.dumps(cfg, indent=2)
    if token:
        r = requests.put(
            f"https://api.github.com/repos/{repo}/contents/{ALERTS_PATH}",
            headers={"Authorization": f"Bearer {token}"},
            json={"message": "Update alert targets from dashboard",
                  "content": base64.b64encode(body.encode()).decode(),
                  **({"sha": sha} if sha else {})}, timeout=15)
        return r.ok
    with open(os.path.join(ROOT, ALERTS_PATH), "w") as f:
        f.write(body)
    return True


# ---------- data ----------

@st.cache_data(ttl=90, show_spinner="Fetching live prices…")
def get_assets():
    assets = gather_assets()
    for a in assets:
        a["ind"] = snapshot(a["series"], a["day_change_pct"])
        a["rec"] = recommend(a["name"], a["cls"], a["day_change_pct"], a["ind"])
    return assets


assets = get_assets()
by_key = {a["key"]: a for a in assets}

# ---------- header ----------
st.title("📊 Market Sentinel")
st.caption("US stocks in USD · Indian stocks, MFs & metals in INR · crypto in both · "
           "volatility-aware signals. Educational, not financial advice.")

cols = st.columns(4)
for col, key in zip(cols, ["USDINR", "^NSEI", "bitcoin", "gold"]):
    a = by_key.get(key)
    if a:
        col.metric(a["name"], a["display"],
                   f"{a['day_change_pct']:+.2f}%" if a["day_change_pct"] is not None else None)

# ---------- recommendations ----------
recs = sorted([a for a in assets if a["rec"]], key=lambda a: -a["rec"]["severity"])
if recs:
    st.subheader("⚡ Current signals")
    for a in recs:
        r = a["rec"]
        icon = {3: "🚨", 2: "⚠️", 1: "💡"}.get(r["severity"], "ℹ️")
        with st.expander(f"{icon} {r['title']}", expanded=r["severity"] >= 2):
            st.write(r["advice"])
            st.caption(r["disclaimer"])
else:
    st.success("No unusual moves right now — markets are behaving normally for each asset's volatility profile.")

# ---------- tables per asset class ----------
CLS = [("us_stock", "🇺🇸 US Stocks"), ("in_stock", "🇮🇳 Indian Stocks"),
       ("mutual_fund", "📈 Mutual Funds"), ("crypto", "🪙 Crypto"),
       ("metal", "🥇 Metals"), ("fx", "💱 FX")]
tabs = st.tabs([label for _, label in CLS])
for (cls, _), tab in zip(CLS, tabs):
    rows = [a for a in assets if a["cls"] == cls]
    if not rows:
        tab.info("Nothing in this class — edit config/watchlist.json.")
        continue
    df = pd.DataFrame([{
        "Asset": a["name"],
        "Price": a["display"],
        "Day %": round(a["day_change_pct"], 2) if a["day_change_pct"] is not None else None,
        "Move vs normal (z)": a["ind"]["z"],
        "RSI": a["ind"]["rsi"],
        "Daily vol %": a["ind"]["vol_pct"],
        "Trend": None if a["ind"]["above_sma200"] is None
                 else ("▲ above 200-DMA" if a["ind"]["above_sma200"] else "▼ below 200-DMA"),
        "Off 1y peak %": a["ind"]["drawdown_pct"],
    } for a in rows])
    tab.dataframe(df, use_container_width=True, hide_index=True)

# ---------- chart ----------
st.subheader("📉 Price history")
sel = st.selectbox("Asset", [a["key"] for a in assets],
                   format_func=lambda k: by_key[k]["name"])
s = by_key[sel]["series"]
if s is not None:
    st.line_chart(s, height=300)
else:
    st.info("No history available for this asset.")

# ---------- sidebar: alert targets ----------
st.sidebar.header("🔔 Email alert targets")
cfg, sha = read_alerts()

for i, t in enumerate(cfg.get("targets", [])):
    name = by_key.get(t["asset"], {}).get("name", t["asset"])
    c1, c2 = st.sidebar.columns([4, 1])
    c1.write(f"**{name}** — {t['type'].replace('_', ' ')} "
             f"{t['value']}{'%' if t['type'] == 'pct_move' else ''}"
             f"{' (' + t.get('currency', '') + ')' if t.get('currency') else ''}")
    if c2.button("✕", key=f"del{i}"):
        cfg["targets"].pop(i)
        write_alerts(cfg, sha)
        st.rerun()

with st.sidebar.form("add_target"):
    st.write("**Add target**")
    asset = st.selectbox("Asset", [a["key"] for a in assets],
                         format_func=lambda k: by_key[k]["name"])
    typ = st.selectbox("Condition", ["price_above", "price_below", "pct_move"],
                       format_func=lambda x: {"price_above": "Price rises above",
                                              "price_below": "Price falls below",
                                              "pct_move": "Daily move exceeds ±%"}[x])
    val = st.number_input("Value", min_value=0.0, format="%.4f")
    cur = st.selectbox("Currency (crypto only)", ["usd", "inr"])
    note = st.text_input("Note (shown in the email)")
    if st.form_submit_button("Save target") and val > 0:
        t = {"asset": asset, "type": typ, "value": val}
        if by_key[asset]["cls"] == "crypto":
            t["currency"] = cur
        if note:
            t["note"] = note
        cfg.setdefault("targets", []).append(t)
        ok = write_alerts(cfg, sha)
        st.sidebar.success("Saved — the alert engine will use it on its next run."
                           if ok else "Save failed — check GITHUB_TOKEN secret.")
        st.rerun()

st.sidebar.divider()
s_cfg = cfg.get("settings", {})
an = st.sidebar.toggle("Volatility anomaly alerts", value=s_cfg.get("anomaly_alerts", True))
te = st.sidebar.toggle("Technical signal alerts", value=s_cfg.get("technical_alerts", True))
cd = st.sidebar.slider("Alert cooldown (hours)", 1, 24, int(s_cfg.get("cooldown_hours", 6)))
if st.sidebar.button("Save settings"):
    cfg["settings"] = {"anomaly_alerts": an, "technical_alerts": te, "cooldown_hours": cd}
    write_alerts(cfg, sha)
    st.sidebar.success("Settings saved.")

st.sidebar.caption("Alerts are checked every ~15 min by GitHub Actions, "
                   "even when this dashboard is closed.")
