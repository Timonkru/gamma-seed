"""
Orchestrator: holt je Index die Kette vom Provider -> rechnet GEX-Level -> schreibt sie im
TradingView-Pine-Seed-Format (data/*.csv + symbol_info/krueger_gamma.json) -> bereit zum git push.

Jeder Tag = eine neue Zeile je Ticker. Idempotent: heutiges Datum wird nicht doppelt geschrieben.

Konfiguration unten: (PREFIX, provider-thunk).  DAX/FTSE jetzt (synthetic-Demo, spaeter eurex/ice),
US spaeter via paid_us -> einfach Zeile ergaenzen.
"""
from pathlib import Path
from datetime import date
import json
import pandas as pd
import gex
import providers as P

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"; SYM = ROOT / "symbol_info"
DATA.mkdir(exist_ok=True); SYM.mkdir(exist_ok=True)

# (PREFIX, currency, thunk) — thunk liefert providers.Chain
# GRATIS & ECHT (yfinance US-ETFs): NQ via QQQ, Dow via DIA, Gold via GLD.
CONFIG = [
    ("NQ",   "USD", lambda: P.yf_us("QQQ")),
    ("DOW",  "USD", lambda: P.yf_us("DIA")),
    ("GOLD", "USD", lambda: P.yf_us("GLD")),
    # SPAETER (bezahlt, da Gratis-OI fuer Europa nicht existiert):
    # ("DAX",  "EUR", lambda: P.eurex_dax()),   # Databento/MD+S
    # ("FTSE", "GBP", lambda: P.ice_ftse()),    # ICE-Abo
    # Test ohne Netz:
    # ("DAX",  "EUR", lambda: P.synthetic("DAX", 18500, mult=5, currency="EUR")),
]

# je PREFIX diese Ticker (jeweils eine EOD-Wertreihe, O=H=L=C=Level)
METRICS = ["FLIP", "CWALL", "PWALL", "MAXPAIN", "GEXBN", "SPOT"]
DESС = {"FLIP": "Gamma Flip", "CWALL": "Call Wall", "PWALL": "Put Wall",
        "MAXPAIN": "Max Pain", "GEXBN": "Net GEX ($bn)", "SPOT": "Underlying Spot (ETF)"}


def append_row(ticker, d, value):
    f = DATA / f"{ticker}.csv"
    stamp = d.strftime("%Y%m%d") + "T"
    rows = []
    if f.exists():
        rows = [ln.strip() for ln in f.read_text().splitlines() if ln.strip()]
        rows = [r for r in rows if not r.startswith(stamp)]   # heutiges Datum ersetzen
    v = round(float(value), 2)
    rows.append(f"{stamp},{v},{v},{v},{v},0")                 # O,H,L,C,Vol
    rows.sort()
    f.write_text("\n".join(rows) + "\n")


def write_symbol_info(tickers, meta):
    """meta[ticker] = (description, currency, pricescale)."""
    info = {
        "timezone": "Etc/UTC",
        "symbol": tickers,
        "description": [meta[t][0] for t in tickers],
        "currency": [meta[t][1] for t in tickers],
        "pricescale": [meta[t][2] for t in tickers],
        "minmovement": [1] * len(tickers),
        "session": ["24x7"] * len(tickers),
        "type": ["index"] * len(tickers),
    }
    (SYM / "krueger_gamma.json").write_text(json.dumps(info, indent=2))


def main():
    today = date.today()
    tickers, meta = [], {}
    print(f"=== Gamma-Seed-Build  {today} ===\n")
    for prefix, ccy, thunk in CONFIG:
        try:
            ch = thunk()
        except NotImplementedError as e:
            print(f"[skip] {prefix}: {e}"); continue
        lv = gex.compute_levels(ch.df, ch.spot)
        vals = {"FLIP": lv["gamma_flip"], "CWALL": lv["call_wall"], "PWALL": lv["put_wall"],
                "MAXPAIN": lv["max_pain"], "GEXBN": lv["total_gex"] / 1e9, "SPOT": lv["spot"]}
        print(f"{prefix:5s} spot {lv['spot']:.0f} | regime {lv['regime'].upper():5s} "
              f"| flip {lv['gamma_flip']:.0f} ({lv['dist_to_flip_pct']:+.2f}%) "
              f"| call-wall {lv['call_wall']:.0f} | put-wall {lv['put_wall']:.0f} "
              f"| maxpain {lv['max_pain']:.0f} | GEX {lv['total_gex']/1e9:+.2f}bn")
        for m in METRICS:
            t = f"{prefix}_{m}"; tickers.append(t)
            ps = 1 if m in ("GEXBN",) else 100
            meta[t] = (f"{prefix} {DESС[m]}", ccy, ps)
            append_row(t, today, vals[m])
    if tickers:
        write_symbol_info(tickers, meta)
        print(f"\nGeschrieben: {len(tickers)} Ticker -> {DATA}")
        print(f"symbol_info -> {SYM/'krueger_gamma.json'}")
        print("\nNaechster Schritt: git add/commit/push  (siehe README).")


if __name__ == "__main__":
    main()
