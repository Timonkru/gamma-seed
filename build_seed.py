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
    (SYM / "gamma-seed.json").write_text(json.dumps(info, indent=2))   # Dateiname = Repo-Name (Pine-Seed-Regel)


AUTO_TEMPLATE = r'''//@version=5
// Gamma Levels (Auto)  [KruegerAlgorithms]  — AUTO-GENERIERT von build_seed.py (NICHT haendisch editieren)
// Erkennt das Chart-Symbol automatisch (US30 / US100 / Gold; DAX/FTSE sobald Daten) und zeigt die passenden Gamma-Level.
// Taeglich: `python build_seed.py` laufen lassen -> diese Datei komplett in den Pine-Editor kopieren -> Save.
// Danach durch die Charts flippen: stellt sich von selbst ein.
indicator("Gamma Levels (Auto) [KruegerAlgorithms]", overlay = true)

// ===== TAGES-LEVEL (auto-generiert, __DATE__) =====
__LEVELS__
// ==================================================

idx     = input.string("Auto", "Index", options = ["Auto", "NQ", "DOW", "GOLD", "DAX", "FTSE"])
rescale = input.bool(true, "Auf Chart umskalieren (ETF -> CFD/Futures)")
showMP  = input.bool(true, "Max Pain zeigen")
showReg = input.bool(true, "Regime-Hintergrund")

t = str.upper(syminfo.ticker)
detect() =>
    r = "NONE"
    if str.contains(t,"NAS") or str.contains(t,"US100") or str.contains(t,"USTEC") or str.contains(t,"NDX") or str.contains(t,"USTECH")
        r := "NQ"
    else if str.contains(t,"US30") or str.contains(t,"WS30") or str.contains(t,"DJ") or str.contains(t,"DOW")
        r := "DOW"
    else if str.contains(t,"XAU") or str.contains(t,"GOLD")
        r := "GOLD"
    else if str.contains(t,"GER") or str.contains(t,"DAX") or str.contains(t,"DE40") or str.contains(t,"DE30")
        r := "DAX"
    else if str.contains(t,"UK100") or str.contains(t,"FTSE")
        r := "FTSE"
    r
sel = idx == "Auto" ? detect() : idx

pick(nq, dw, gd, dx, ft) => sel == "NQ" ? nq : sel == "DOW" ? dw : sel == "GOLD" ? gd : sel == "DAX" ? dx : sel == "FTSE" ? ft : 0.0
flipI = pick(NQ_FLIP, DOW_FLIP, GOLD_FLIP, DAX_FLIP, FTSE_FLIP)
cwI   = pick(NQ_CW,   DOW_CW,   GOLD_CW,   DAX_CW,   FTSE_CW)
pwI   = pick(NQ_PW,   DOW_PW,   GOLD_PW,   DAX_PW,   FTSE_PW)
mpI   = pick(NQ_MP,   DOW_MP,   GOLD_MP,   DAX_MP,   FTSE_MP)
spotI = pick(NQ_SPOT, DOW_SPOT, GOLD_SPOT, DAX_SPOT, FTSE_SPOT)

k = rescale and spotI > 0 ? close / spotI : 1.0
flip = flipI * k
cw   = cwI * k
pw   = pwI * k
mp   = mpI * k

plot(flipI > 0 ? flip : na, "Gamma Flip", color.yellow, 2)
plot(cwI  > 0 ? cw   : na, "Call Wall",  color.red,    2)
plot(pwI  > 0 ? pw   : na, "Put Wall",   color.green,  2)
plot(showMP and mpI > 0 ? mp : na, "Max Pain", color.gray, 1, style = plot.style_circles)

refSpot = rescale and spotI > 0 ? spotI : close
longG = flipI > 0 and refSpot > flipI
bgcolor(showReg and flipI > 0 ? (longG ? color.new(color.green, 92) : color.new(color.red, 92)) : na)

var label lab = na
if barstate.islast
    label.delete(lab)
    txt = flipI <= 0 ? (sel == "NONE" ? "Kein Gamma fuer dieses Symbol" : sel + ": keine Daten (spaeter)") : sel + " — " + (longG ? "LONG (Pin/Reversion)" : "SHORT (Trend/Amplify)") + "  Flip " + str.tostring(flip, format.mintick)
    lab := label.new(bar_index, high, txt, style = label.style_label_left, color = flipI <= 0 ? color.new(color.gray, 30) : (longG ? color.new(color.green, 20) : color.new(color.red, 20)), textcolor = color.white, size = size.small)
'''


def gen_auto_pine(levels, today):
    """Schreibt GammaLevels_auto.pine mit den heutigen Leveln aller Indizes (fehlende = 0)."""
    order = ["NQ", "DOW", "GOLD", "DAX", "FTSE"]
    lines = []
    for k in order:
        f, cw, pw, mp, sp = levels.get(k, (0, 0, 0, 0, 0))
        lines.append(f"{k}_FLIP = {f:.2f}")
        lines.append(f"{k}_CW   = {cw:.2f}")
        lines.append(f"{k}_PW   = {pw:.2f}")
        lines.append(f"{k}_MP   = {mp:.2f}")
        lines.append(f"{k}_SPOT = {sp:.2f}")
    pine = AUTO_TEMPLATE.replace("__LEVELS__", "\n".join(lines)).replace("__DATE__", str(today))
    (ROOT / "GammaLevels_auto.pine").write_text(pine, encoding="utf-8")
    return ROOT / "GammaLevels_auto.pine"


def main():
    today = date.today()
    tickers, meta, copyrows = [], {}, []
    print(f"=== Gamma-Seed-Build  {today} ===\n")
    for prefix, ccy, thunk in CONFIG:
        try:
            ch = thunk()
        except NotImplementedError as e:
            print(f"[skip] {prefix}: {e}"); continue
        lv = gex.compute_levels(ch.df, ch.spot)
        copyrows.append((prefix, lv))
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
        print(f"symbol_info -> {SYM/'gamma-seed.json'}")

    # ---- COPY-BLOCK fuer den Manual-Input-Pine-Indikator ----
    lines = [f"=== GAMMA-LEVEL {today} — in 'Gamma Levels (Manual)' eintippen ==="]
    for prefix, lv in copyrows:
        lines.append(
            f"{prefix:5s} | Flip {lv['gamma_flip']:.2f} | CallWall {lv['call_wall']:.2f} | "
            f"PutWall {lv['put_wall']:.2f} | MaxPain {lv['max_pain']:.2f} | ETF-Spot {lv['spot']:.2f} "
            f"| Regime {lv['regime'].upper()}")
    block = "\n".join(lines)
    print("\n" + block)
    (ROOT / "today_levels.txt").write_text(block + "\n", encoding="utf-8")

    # ---- AUTO-Pine generieren (Symbol-Erkennung, alle Indizes) ----
    levels = {p: (lv["gamma_flip"], lv["call_wall"], lv["put_wall"], lv["max_pain"], lv["spot"]) for p, lv in copyrows}
    auto = gen_auto_pine(levels, today)
    print(f"\nAUTO-Indikator regeneriert -> {auto}")
    print("   => komplette Datei in den TradingView-Pine-Editor kopieren (1x/Tag). Erkennt US30/US100/Gold automatisch.")


if __name__ == "__main__":
    main()
