"""Rule-based, volatility-aware recommendations.
Educational nudges, not financial advice — every output says so."""

DISCLAIMER = ("Educational signal, not financial advice. "
              "Do your own research before acting.")


def recommend(name, asset_class, day_change_pct, ind):
    """Returns (severity, title, advice) or None.
    severity: 3=extreme move, 2=notable move, 1=technical signal."""
    z = ind.get("z")
    r = ind.get("rsi")
    dd = ind.get("drawdown_pct")
    above200 = ind.get("above_sma200")
    chg = day_change_pct or 0

    recs = []

    # --- Volatility-aware anomaly detection ---
    if z is not None and abs(z) >= 2:
        sev = 3 if abs(z) >= 3 else 2
        direction = "drop" if z < 0 else "surge"
        vol = ind.get("vol_pct")
        title = f"{name}: {'EXTREME' if sev == 3 else 'unusual'} {direction} ({chg:+.2f}%, {abs(z):.1f}x its normal daily move)"
        if z < 0:
            if above200 and (r is None or r < 40):
                advice = ("Sharp dip in an asset still above its 200-day trend. "
                          "Historically such dips in uptrends often recover — a staggered/"
                          "SIP-style add is how long-term investors typically respond. "
                          "Avoid deploying everything at once; the dip can deepen.")
            elif above200 is False:
                advice = ("Sharp drop AND price is below its 200-day average — the "
                          "downtrend may have momentum. Catching falling knives is risky; "
                          "waiting for stabilisation is the conservative play.")
            else:
                advice = ("Unusually large drop for this asset. Check the news for a "
                          "fundamental reason before reacting — price-only signals can't "
                          "see earnings, regulation or macro shocks.")
        else:
            if r is not None and r > 70:
                advice = ("Sharp rise with overbought RSI. If this position has grown "
                          "beyond your target allocation, booking partial profits / "
                          "rebalancing is the disciplined move. Momentum can continue, "
                          "but chasing spikes is where most retail losses happen.")
            else:
                advice = ("Strong surge but not yet overbought. Fine to hold; avoid "
                          "FOMO-buying after a spike — wait for consolidation.")
        recs.append((sev, title, advice))

    # --- Technical signals (only when no anomaly already fired for same side) ---
    if r is not None:
        if r <= 30 and not (z is not None and z <= -2):
            note = " Price is also >15% off its recent peak." if (dd or 0) <= -15 else ""
            recs.append((1, f"{name}: oversold (RSI {r})",
                         "RSI at/below 30 suggests selling pressure may be exhausting."
                         + note + " For quality assets this is often an accumulation "
                         "zone — but confirm fundamentals haven't changed."))
        elif r >= 75 and not (z is not None and z >= 2):
            recs.append((1, f"{name}: overbought (RSI {r})",
                         "RSI at/above 75. Consider trimming if overweight; at minimum, "
                         "avoid adding fresh money at these levels."))

    # --- Deep drawdown awareness ---
    if dd is not None and dd <= -25 and asset_class in ("us_stock", "in_stock", "crypto"):
        recs.append((1, f"{name}: {abs(dd):.0f}% below its 1-year peak",
                     "Deep drawdown. If your thesis is intact this is a long-term "
                     "opportunity zone; if the business/asset has deteriorated, "
                     "averaging down just compounds the mistake. Re-examine the thesis."))

    if not recs:
        return None
    recs.sort(key=lambda x: -x[0])
    sev, title, advice = recs[0]
    extra = [t for _, t, _ in recs[1:]]
    if extra:
        advice += " Also: " + "; ".join(extra) + "."
    return {"severity": sev, "title": title, "advice": advice,
            "disclaimer": DISCLAIMER}
