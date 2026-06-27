"""Einmal-Diagnose: Wie viel der Level-Verschiebung ist Methodik, wie viel Markt?
Ein Snapshot, drei Berechnungen: ALT (0-60 DTE, T/365) | STRUKT (7-45) | NAH (0-5).
Vergleich gegen die Morgen-Werte (alte Methode) = reiner Markt-Drift."""
import gex
import providers as P

MORNING = {  # today_levels.txt von heute frueh (alte Methode)
    "NQ": {"flip": 29078.13, "cw": 29091.48, "pw": 28968.22},
    "DOW": {"flip": 50871.81, "cw": 50931.03, "pw": 50831.16},
}

for sym, pfx, isym in [("QQQ", "NQ", "^NDX"), ("DIA", "DOW", "^DJI")]:
    ch = P.yf_us(sym, max_days=60)
    df = ch.df
    R = P.index_spot(isym) / ch.spot

    old = df.copy()
    old["T"] = old["dte"].apply(lambda d: max(d, 0.5)) / 365.0
    variants = {
        "ALT (0-60, /365) JETZT": gex.compute_levels(old, ch.spot),
        "STRUKT (7-45) JETZT": gex.compute_levels(df[(df["dte"] >= 7) & (df["dte"] <= 45)], ch.spot),
        "NAH (0-5) JETZT": gex.compute_levels(df[df["dte"] <= 5], ch.spot),
    }
    m = MORNING[pfx]
    print(f"\n=== {pfx} (Index-Punkte, Spot jetzt {ch.spot * R:.0f}) ===")
    print(f"  {'ALT heute FRUEH':24s} Flip {m['flip']:9.1f} | CW {m['cw']:9.1f} | PW {m['pw']:9.1f}")
    for name, lv in variants.items():
        if lv is None:
            continue
        f = (lv["gamma_flip"] or 0) * R
        c = (lv["call_wall"] or 0) * R
        p = (lv["put_wall"] or 0) * R
        print(f"  {name:24s} Flip {f:9.1f} | CW {c:9.1f} | PW {p:9.1f}")
