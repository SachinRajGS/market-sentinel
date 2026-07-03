"""Market Sentinel alert engine — run by GitHub Actions on a cron.
Fetches all watchlist assets, evaluates user targets + volatility-aware
anomalies + technical signals, dedupes via state file, emails via Gmail."""
import json
import os
import sys
from datetime import datetime, timezone, timedelta

from core import data_sources as ds
from core.indicators import snapshot
from core.recommend import recommend
from core.emailer import send_alert_email

ROOT = os.path.dirname(os.path.abspath(__file__))
STATE_PATH = os.path.join(ROOT, "state", "alert_state.json")


def load_json(path, default):
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return default


def fmt_inr(x):
    """Indian digit grouping: ₹12,34,567.89."""
    neg = x < 0
    x = abs(round(x, 2))
    whole = int(x)
    dec = int(round((x - whole) * 100))
    s = str(whole)
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        s = ",".join(([head] if head else []) + groups + [tail])
    return f"{'-' if neg else ''}₹{s}.{dec:02d}"


GRAMS_PER_TROY_OZ = 31.1034768
METAL_SPECS = {"gold": ("GC=F", 10 / GRAMS_PER_TROY_OZ, "INR/10g"),
               "silver": ("SI=F", 1000 / GRAMS_PER_TROY_OZ, "INR/kg")}


def gather_assets():
    """Uniform records: key, name, cls, price, display, day_change_pct, series.
    All Yahoo symbols are fetched in ONE batched download (rate-limit friendly:
    the watchlist has ~70 symbols and the cron runs every 15 min)."""
    wl = load_json(os.path.join(ROOT, "config", "watchlist.json"), {})
    assets = []

    # -- one batch for everything Yahoo-listed --
    syms = ([s["symbol"] for s in wl.get("us_stocks", [])]
            + [s["symbol"] for s in wl.get("in_stocks", [])]
            + ([spec[0] for spec in METAL_SPECS.values()] if wl.get("metals") else [])
            + (["USDINR=X"] if wl.get("usdinr") or wl.get("metals") else []))
    hist = ds.yahoo_batch(syms)

    def last_and_change(ser):
        return float(ser.iloc[-1]), (float(ser.iloc[-1] / ser.iloc[-2]) - 1) * 100

    fx_ser = hist.get("USDINR=X")
    fx = float(fx_ser.iloc[-1]) if fx_ser is not None else 84.0

    for s in wl.get("us_stocks", []):
        ser = hist.get(s["symbol"])
        if ser is not None:
            price, chg = last_and_change(ser)
            assets.append(dict(key=s["symbol"], name=s["name"], cls="us_stock",
                               price=price, display=f"${price:,.2f}",
                               day_change_pct=chg, series=ser))

    for s in wl.get("in_stocks", []):
        ser = hist.get(s["symbol"])
        if ser is not None:
            price, chg = last_and_change(ser)
            assets.append(dict(key=s["symbol"], name=s["name"], cls="in_stock",
                               price=price, display=fmt_inr(price),
                               day_change_pct=chg, series=ser))

    for m in wl.get("mutual_funds", []):
        latest = ds.mf_latest(m["scheme_code"])
        if latest:
            hist = ds.mf_history(m["scheme_code"])
            chg = None
            if hist is not None and len(hist) >= 2:
                chg = (hist.iloc[-1] / hist.iloc[-2] - 1) * 100
            assets.append(dict(key=str(m["scheme_code"]), name=m["name"],
                               cls="mutual_fund", price=latest["nav"],
                               display=f"{fmt_inr(latest['nav'])} (NAV {latest['date']})",
                               day_change_pct=chg, series=hist))

    ids = [c["id"] for c in wl.get("crypto", [])]
    cq = ds.crypto_quotes(ids) if ids else {}
    for c in wl.get("crypto", []):
        q = cq.get(c["id"])
        if q:
            assets.append(dict(key=c["id"], name=c["name"], cls="crypto",
                               price=q["usd"],
                               display=f"${q['usd']:,.0f} / {fmt_inr(q['inr'])}",
                               day_change_pct=q["day_change_pct"],
                               series=ds.crypto_history(c["id"]),
                               price_inr=q["inr"]))

    if wl.get("metals"):
        for name, (sym, mult, unit) in METAL_SPECS.items():
            ser = hist.get(sym)
            if ser is not None:
                usd, chg = last_and_change(ser)
                inr = usd * mult * fx
                assets.append(dict(key=name, name=name.capitalize(),
                                   cls="metal", price=inr,
                                   display=f"{fmt_inr(inr)} ({unit})",
                                   day_change_pct=chg, series=ser))

    if wl.get("usdinr") and fx_ser is not None:
        price, chg = last_and_change(fx_ser)
        assets.append(dict(key="USDINR", name="USD/INR", cls="fx",
                           price=price, display=f"₹{price:.3f}",
                           day_change_pct=chg, series=fx_ser))
    return assets


def eval_targets(assets, targets):
    hits = []
    by_key = {a["key"]: a for a in assets}
    for t in targets:
        a = by_key.get(t["asset"])
        if not a:
            continue
        price = a.get("price_inr") if t.get("currency") == "inr" and "price_inr" in a else a["price"]
        typ, val = t["type"], float(t["value"])
        fired, desc = False, ""
        if typ == "price_above" and price >= val:
            fired, desc = True, f"crossed ABOVE your target {val:,.2f} (now {a['display']})"
        elif typ == "price_below" and price <= val:
            fired, desc = True, f"dropped BELOW your target {val:,.2f} (now {a['display']})"
        elif typ == "pct_move" and a["day_change_pct"] is not None and abs(a["day_change_pct"]) >= val:
            fired, desc = True, f"moved {a['day_change_pct']:+.2f}% today (your threshold: ±{val}%)"
        if fired:
            hits.append({"severity": 0, "id": f"target:{t['asset']}:{typ}:{val}",
                         "title": f"🎯 {a['name']} {desc}",
                         "advice": t.get("note", "Target you set has been hit — review your plan for this asset.")})
    return hits


def main():
    cfg = load_json(os.path.join(ROOT, "config", "alerts.json"), {})
    settings = cfg.get("settings", {})
    state = load_json(STATE_PATH, {"fired": {}})
    now = datetime.now(timezone.utc)
    cooldown = timedelta(hours=float(settings.get("cooldown_hours", 6)))

    assets = gather_assets()
    if not assets:
        print("No asset data fetched — aborting without alerting.")
        sys.exit(0)

    alerts = eval_targets(assets, cfg.get("targets", []))

    for a in assets:
        ind = snapshot(a["series"], a["day_change_pct"])
        a["ind"] = ind
        if settings.get("anomaly_alerts", True) or settings.get("technical_alerts", True):
            rec = recommend(a["name"], a["cls"], a["day_change_pct"], ind)
            if rec:
                if rec["severity"] == 1 and not settings.get("technical_alerts", True):
                    continue
                if rec["severity"] >= 2 and not settings.get("anomaly_alerts", True):
                    continue
                rec["id"] = f"rec:{a['key']}:{rec['severity']}"
                alerts.append(rec)

    # Deduplicate via cooldown state
    fresh = []
    for al in alerts:
        last = state["fired"].get(al["id"])
        if last and now - datetime.fromisoformat(last) < cooldown:
            continue
        fresh.append(al)
        state["fired"][al["id"]] = now.isoformat()

    # prune old state
    state["fired"] = {k: v for k, v in state["fired"].items()
                      if now - datetime.fromisoformat(v) < timedelta(days=7)}

    headline = [f"{a['name']}: {a['display']} ({a['day_change_pct']:+.2f}%)"
                for a in assets if a["day_change_pct"] is not None][:6]

    if fresh:
        print(f"Sending {len(fresh)} alert(s):")
        for al in fresh:
            print(" -", al["title"])
        send_alert_email(fresh, headline)
    else:
        print("No new alerts this run.")

    os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
    with open(STATE_PATH, "w") as f:
        json.dump(state, f, indent=1)


if __name__ == "__main__":
    main()
