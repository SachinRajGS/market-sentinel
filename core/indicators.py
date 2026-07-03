"""Technical indicators + volatility-aware move scoring.
The z-score is the heart of the system: a move is judged against THAT asset's
own recent volatility, so 2% on gold screams while 2% on BTC is a shrug."""
import numpy as np


def rsi(series, period=14):
    if series is None or len(series) < period + 1:
        return None
    delta = series.diff().dropna()
    gain = delta.clip(lower=0).ewm(alpha=1 / period, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / period, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    val = 100 - 100 / (1 + rs)
    return round(float(val.iloc[-1]), 1)


def sma(series, window):
    if series is None or len(series) < window:
        return None
    return float(series.rolling(window).mean().iloc[-1])


def daily_vol_pct(series, lookback=90):
    """Std-dev of daily returns (%) over the lookback window."""
    if series is None or len(series) < 20:
        return None
    rets = series.pct_change().dropna().tail(lookback) * 100
    v = float(rets.std())
    return v if v > 0 else None


def move_zscore(day_change_pct, vol_pct):
    """How unusual is today's move for this asset? |z|>=2 notable, >=3 extreme."""
    if day_change_pct is None or not vol_pct:
        return None
    return round(day_change_pct / vol_pct, 2)


def drawdown_pct(series, lookback=252):
    """% below the recent peak — context for buy-the-dip logic."""
    if series is None or len(series) < 20:
        return None
    window = series.tail(lookback)
    return round((window.iloc[-1] / window.max() - 1) * 100, 2)


def snapshot(series, day_change_pct):
    """Compute the full indicator set for one asset."""
    if series is None:
        return {"rsi": None, "sma50": None, "sma200": None, "vol_pct": None,
                "z": None, "drawdown_pct": None, "above_sma200": None}
    s50, s200 = sma(series, 50), sma(series, 200)
    vol = daily_vol_pct(series)
    last = float(series.iloc[-1])
    return {
        "rsi": rsi(series),
        "sma50": s50,
        "sma200": s200,
        "vol_pct": round(vol, 2) if vol else None,
        "z": move_zscore(day_change_pct, vol),
        "drawdown_pct": drawdown_pct(series),
        "above_sma200": (last > s200) if s200 else None,
    }
