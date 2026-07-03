"""Unified fetchers for all asset classes. Every function fails soft (returns None)
so one broken source never kills the dashboard or the alert run."""
import json
import time
import requests
import yfinance as yf

UA = {"User-Agent": "Mozilla/5.0 (market-sentinel)"}
GRAMS_PER_TROY_OZ = 31.1034768


# ---------- Yahoo Finance (stocks, indices, metals futures, USD/INR) ----------

def yahoo_quote(symbol: str):
    """Last price, previous close and day % for one Yahoo symbol."""
    try:
        t = yf.Ticker(symbol)
        info = t.fast_info
        price = float(info["last_price"])
        prev = float(info["previous_close"])
        return {
            "symbol": symbol,
            "price": price,
            "prev_close": prev,
            "day_change_pct": (price / prev - 1) * 100 if prev else 0.0,
            "currency": str(info.get("currency", "")),
        }
    except Exception:
        return None


def yahoo_batch(symbols, period="1y"):
    """ONE threaded download for many symbols -> {symbol: close Series}.
    Today's daily candle updates intraday, so the last value is near-live.
    Far kinder to Yahoo rate limits than per-symbol calls."""
    if not symbols:
        return {}
    try:
        df = yf.download(symbols, period=period, interval="1d",
                         auto_adjust=True, group_by="ticker",
                         threads=True, progress=False)
        out = {}
        for s in symbols:
            try:
                ser = (df[s]["Close"] if len(symbols) > 1 else df["Close"]).dropna()
                if len(ser) >= 2:
                    out[s] = ser
            except Exception:
                pass
        return out
    except Exception:
        return {}


def yahoo_history(symbol: str, period="6mo", interval="1d"):
    """Daily close history as a pandas Series (for vol, RSI, SMAs)."""
    try:
        df = yf.Ticker(symbol).history(period=period, interval=interval, auto_adjust=True)
        if df is None or df.empty:
            return None
        return df["Close"].dropna()
    except Exception:
        return None


def usdinr():
    q = yahoo_quote("USDINR=X")
    return q["price"] if q else None


# ---------- Precious metals (COMEX futures -> INR per 10g / per kg) ----------

def metals_inr(fx: float):
    """Gold INR/10g and Silver INR/kg from COMEX USD/oz. Note: excludes Indian
    import duty & local premium, so ~6-9% below MCX; trend/alerts unaffected."""
    out = {}
    for sym, name, mult in (("GC=F", "gold", 10 / GRAMS_PER_TROY_OZ),
                            ("SI=F", "silver", 1000 / GRAMS_PER_TROY_OZ)):
        q = yahoo_quote(sym)
        if q and fx:
            out[name] = {
                "symbol": sym,
                "usd_oz": q["price"],
                "inr": q["price"] * fx * mult,
                "unit": "INR/10g" if name == "gold" else "INR/kg",
                "day_change_pct": q["day_change_pct"],
            }
    return out


# ---------- Crypto (CoinGecko: USD + INR natively) ----------

def crypto_quotes(ids=("bitcoin", "ethereum")):
    try:
        r = requests.get(
            "https://api.coingecko.com/api/v3/simple/price",
            params={"ids": ",".join(ids), "vs_currencies": "usd,inr",
                    "include_24hr_change": "true"},
            headers=UA, timeout=20)
        r.raise_for_status()
        d = r.json()
        return {
            cid: {
                "usd": v["usd"],
                "inr": v["inr"],
                "day_change_pct": v.get("usd_24h_change", 0.0),
            } for cid, v in d.items()
        }
    except Exception:
        return {}


def crypto_history(cid: str, days=180):
    """Daily USD closes from CoinGecko for indicators."""
    try:
        r = requests.get(
            f"https://api.coingecko.com/api/v3/coins/{cid}/market_chart",
            params={"vs_currency": "usd", "days": days, "interval": "daily"},
            headers=UA, timeout=20)
        r.raise_for_status()
        import pandas as pd
        prices = r.json()["prices"]
        s = pd.Series([p[1] for p in prices],
                      index=[pd.to_datetime(p[0], unit="ms") for p in prices])
        return s
    except Exception:
        return None


# ---------- Mutual funds (mfapi.in — free AMFI mirror, daily NAV) ----------

def mf_latest(scheme_code: int):
    try:
        r = requests.get(f"https://api.mfapi.in/mf/{scheme_code}/latest",
                         headers=UA, timeout=20)
        r.raise_for_status()
        d = r.json()
        nav = float(d["data"][0]["nav"])
        return {"scheme_code": scheme_code,
                "name": d["meta"]["scheme_name"],
                "nav": nav, "date": d["data"][0]["date"]}
    except Exception:
        return None


def mf_history(scheme_code: int, n=250):
    try:
        r = requests.get(f"https://api.mfapi.in/mf/{scheme_code}",
                         headers=UA, timeout=25)
        r.raise_for_status()
        import pandas as pd
        rows = r.json()["data"][:n]
        s = pd.Series([float(x["nav"]) for x in reversed(rows)],
                      index=[pd.to_datetime(x["date"], format="%d-%m-%Y")
                             for x in reversed(rows)])
        return s
    except Exception:
        return None


def mf_search(query: str):
    """Find scheme codes by fund name."""
    try:
        r = requests.get("https://api.mfapi.in/mf/search",
                         params={"q": query}, headers=UA, timeout=20)
        r.raise_for_status()
        return r.json()
    except Exception:
        return []
