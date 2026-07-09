"""
Self-Test der DAX-Erweiterung OHNE echtes Eurex-File: erzeugt ein synthetisches
ODAX-Tagesfile (Eurex-aehnliche Spalten + Settlement-PREISE statt IV), laesst es durch
eurex_dax() laufen (IV-Inversion!) und rechnet die GEX-Level. Geplant: Call-Wall 19000,
Put-Wall 18000 -> muessen wieder rauskommen. Beweist Parser + IV-Inversion + GEX end-to-end.
"""
from datetime import date, timedelta
from pathlib import Path
import numpy as np
import pandas as pd

import gex
import providers as P

ROOT = Path(__file__).resolve().parent
SPOT = 18500.0
CWALL, PWALL = 19000.0, 18000.0
today = date.today()


def make_synth_file():
    strikes = np.arange(16000.0, 21000.0 + 1, 100.0)
    rng = np.random.default_rng(7)
    rows = []
    for dte in (3, 28):                         # eine Nah- + eine Struktur-Verfall
        exp = today + timedelta(days=dte)
        T = max(np.busday_count(today, exp), 0.5) / 252.0
        for K in strikes:
            m = abs(K - SPOT) / SPOT
            iv = 0.13 + 0.6 * m                 # Smile
            base = 2000 * np.exp(-((K - SPOT) / (SPOT * 0.04)) ** 2)
            cb = 9000 * np.exp(-((K - CWALL) / 150.0) ** 2)
            pb = 9000 * np.exp(-((K - PWALL) / 150.0) ** 2)
            for typ, oi in (("Call", base + cb + rng.integers(0, 300)),
                            ("Put", base + pb + rng.integers(0, 300))):
                px = gex.bs_price(SPOT, float(K), T, iv, typ[0])   # Settlement-Preis
                rows.append({"StrikePrice": K, "PutOrCall": typ,
                             "OpenInterest": round(float(oi)),
                             "DailySettlementPrice": round(px, 2),
                             "ExpiryDate": exp.isoformat()})
    d = ROOT / "data" / "eurex"; d.mkdir(parents=True, exist_ok=True)
    f = d / f"_SELFTEST_ODAX_{today:%Y%m%d}.csv"
    pd.DataFrame(rows).to_csv(f, index=False)
    return f


def main():
    f = make_synth_file()
    print(f"Synthetisches Eurex-File: {f.name}  ({sum(1 for _ in open(f))-1} Zeilen)\n")
    ch = P.eurex_dax(path=f, spot=SPOT)
    print(f"Chain: {len(ch.df)} Optionen | Spot {ch.spot:.0f} | mult {ch.df['mult'].iloc[0]:.0f}"
          f" | {ch.currency} | IV-Range {ch.df['iv'].min():.2f}-{ch.df['iv'].max():.2f}\n")

    struct = gex.compute_levels(ch.df[ch.df["dte"] >= 7], ch.spot)
    near = gex.compute_levels(ch.df[ch.df["dte"] <= 5], ch.spot)
    print("STRUKTUR (7-45 DTE):")
    print(f"  Regime {struct['regime'].upper()} | Flip {struct['gamma_flip']:.0f} "
          f"| Call-Wall {struct['call_wall']:.0f} | Put-Wall {struct['put_wall']:.0f} "
          f"| MaxPain {struct['max_pain']:.0f} | EM1d ±{struct['exp_move_1d']:.0f} "
          f"| GEX {struct['total_gex']/1e9:+.2f}bn")
    print(f"NAH (0-5 DTE): Call-Wall {near['call_wall']:.0f} | Put-Wall {near['put_wall']:.0f}\n")

    ok = abs(struct["call_wall"] - CWALL) <= 200 and abs(struct["put_wall"] - PWALL) <= 200
    print(f"{'OK' if ok else 'FEHLER'}: geplante CW {CWALL:.0f}/PW {PWALL:.0f} "
          f"-> erkannt {struct['call_wall']:.0f}/{struct['put_wall']:.0f}")
    f.unlink()      # Self-Test-File wieder weg
    print("(Self-Test-File geloescht)")


if __name__ == "__main__":
    main()
