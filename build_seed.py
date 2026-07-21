"""
Orchestrator: holt je Index die Kette vom Provider -> rechnet GEX-Level -> schreibt sie im
TradingView-Pine-Seed-Format (data/*.csv + symbol_info/) + generiert GammaLevels_auto.pine.

v2 (2026-06-11): STRUKTUR-Karte (7-45 DTE, konsistent zur KasseRL-QC-Historie) und
NAH-Karte (0-5 DTE, das 0DTE-"Tageswetter") werden GETRENNT gerechnet — vorher
dominierte das Verfalls-Gamma die Walls (CW 7 Punkte ueberm Spot = ATM-Strike von
heute, keine Struktur). Dazu: zweite Walls (Strike-Regal), Expected Move (1d),
Flip-ZONE statt binaerem Regime, Veraltet-Warnung im Pine, Alerts.

Jeder Tag = eine neue Zeile je Ticker. Idempotent: heutiges Datum wird ersetzt.
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

STRUCT_MIN_DTE = 7    # Struktur-Karte: wie KasseRL/QC (MIN_DTE=7, MAX_DTE=45)
NEAR_MAX_DTE = 5      # Nah-Karte: 0DTE-Wochen-Verfaelle

CONFIG = [
    ("NQ",   "USD", lambda: P.yf_us("QQQ")),
    ("DOW",  "USD", lambda: P.yf_us("DIA")),
    ("GOLD", "USD", lambda: P.yf_us("GLD")),
    # DAX = direkt auf dem Index (ODAX, mult=5) -> KEIN ETF-Scaling (nicht in INDEX_SYM).
    # Liest neuestes Eurex-File aus data/eurex/; ohne File -> sauberer Skip.
    ("DAX",  "EUR", lambda: P.eurex_dax()),
    # SPAETER: ("SPX", "USD", lambda: P.yf_us("SPY")), ("FTSE", "GBP", lambda: P.ice_ftse())
]

INDEX_SYM = {"NQ": "^NDX", "DOW": "^DJI", "GOLD": "GC=F"}
METRICS = ["FLIP", "CWALL", "PWALL", "CWALL2", "PWALL2", "NCWALL", "NPWALL",
           "NFLIP", "MAXPAIN", "EM1D", "GEXBN", "SPOT",
           "VANNA", "VANNAK", "CHARM", "CHARMK"]
DESC = {"FLIP": "Gamma Flip", "CWALL": "Call Wall", "PWALL": "Put Wall",
        "CWALL2": "Call Wall 2", "PWALL2": "Put Wall 2",
        "NCWALL": "Near Call Wall (0-5d)", "NPWALL": "Near Put Wall (0-5d)",
        "NFLIP": "Near Gamma Flip (0-5d)",
        "MAXPAIN": "Max Pain", "EM1D": "Expected Move 1d",
        "GEXBN": "Net GEX ($bn)", "SPOT": "Underlying Spot",
        "VANNA": "Total Vanna ($M)", "VANNAK": "Vanna Strike",
        "CHARM": "Total Charm ($M)", "CHARMK": "Charm Strike"}

SCALE_KEYS = ("gamma_flip", "call_wall", "call_wall2", "put_wall", "put_wall2",
              "max_pain", "exp_move_1d", "vanna_strike", "charm_strike")


def tv_seed_block(win, spot, day, scale=1.0, aiv=None):
    """Paste-Block fuer das oeffentliche TV-Skript "Gamma Exposure Profile —
    Manual Chain Input": Header + eine Zeile je Strike
    (strike;callOI;putOI;iv;dte).
    win = Ketten-Slice (Struktur ODER Nah), spot in INDEX-PunkTEN, scale = R
    (ETF->Index; skaliert nur die Strikes).
    FIX-HISTORIE 2026-07-20 (Timons Befunde, 2 Runden):
    (1) EINE Mittel-DTE fuer die ganze Karte verschob den DOW-Flip um 368
        Punkte (Gamma ~1/sqrt(T)) und kippte das Regime -> Feld 5 = DTE.
    (2) Auch die Buendelung JE STRIKE blieb -50 Punkte daneben — Haupttreiber
        war die OI-gemischte Call/Put-IV am selben Strike. Jetzt: EINE ZEILE
        PRO OPTION (Calls: k;oi;0;iv;dte / Puts: k;0;oi;iv;dte) — gemessen
        exakt (Diff -0.1 Pkt zur vollen privaten Rechnung). Zeilen werden nach
        |GEX|-Beitrag am Spot sortiert und auf 99.5 %% kumuliertes Gewicht
        getrimmt (DAX: 649 -> 411 Zeilen; haelt den Paste kompakt und
        entfernt Deep-OTM-Rauschen). Header-DTE bleibt Fallback."""
    if win is None or not len(win):
        return None
    tot_oi = float(win["oi"].sum())
    if tot_oi <= 0:
        return None
    dte = float((win["dte"] * win["oi"]).sum() / tot_oi)
    mult = float(win["mult"].iloc[0])
    S = spot / scale if scale else spot
    weighted = []
    for _, r in win.iterrows():
        oi = float(r["oi"])
        if oi <= 0:
            continue
        # Trim-Gewicht ueber ALLE drei Groessen (GEX, Vanna, Charm) — reines
        # GEX-Gewicht warf Zeilen weg, die kaum Gamma, aber relevantes
        # Vanna/Charm tragen (gemessen: -4 % Vanna beim reinen GEX-Trim).
        wg = abs(float(gex.bs_gamma(S, r["strike"], r["T"], r["iv"])) * oi)
        wv = abs(float(gex.bs_vanna(S, r["strike"], r["T"], r["iv"])) * oi)
        wc = abs(float(gex.bs_charm(S, r["strike"], r["T"], r["iv"])) * oi)
        c = oi if r["type"] == "C" else 0.0
        p = oi if r["type"] == "P" else 0.0
        # Feld 5 = T*365, NICHT die Kalender-dte: die Ketten-T-Spalte ist
        # Busdays/252 (KasseRL-Konvention); das Pine rechnet Feld5/365. Nur
        # T*365 reproduziert das private T exakt (dte waere ~8%% daneben —
        # gemessen als -3.7M Vanna / -3.7M Charm).
        weighted.append([0.0, float(r["strike"]), c, p,
                         float(r["iv"]), float(r["T"]) * 365.0, wg, wv, wc,
                         abs(float(r["strike"]) - S)])
    if not weighted:
        return None
    for gi in (6, 7, 8):                            # normiert je Groesse
        m = max(t[gi] for t in weighted) or 1.0
        for t in weighted:
            t[0] += t[gi] / m
    weighted.sort(key=lambda t: -t[0])
    tot_w = sum(t[0] for t in weighted)
    keep, acc = [], 0.0
    for t in weighted:
        keep.append(t)
        acc += t[0]
        if acc >= tot_w * 0.995:
            break
    # ATM-Pflicht: die 6 spot-naechsten Zeilen IMMER mitnehmen — das Pine
    # schaetzt die ATM-IV (Expected Move) als Median dieser Zeilen, exakt wie
    # die private Referenz; der Trim darf sie nicht wegwerfen.
    kept = {id(t) for t in keep}
    for t in sorted(weighted, key=lambda t: t[9])[:6]:
        if id(t) not in kept:
            keep.append(t)
    keep.sort(key=lambda t: (t[1], t[5]))          # nach Strike, dann DTE
    # iv 6 / dte 3 Dezimalen: 1-Dezimal-dte kostete messbar Vanna/Charm
    # (d2-sensitiv): -3.6M/-3.8M auf der DAX-Kette.
    rows = [f"{t[1] * scale:.2f};{t[2]:.0f};{t[3]:.0f};{t[4]:.6f};{t[5]:.3f}"
            for t in keep]
    # aiv-Parameter = atm_iv aus DEMSELBEN compute_levels-Lauf wie das Label
    # (eine Quelle!). Eigene Neuberechnung nur als Fallback: am ATM liegen
    # viele Zeilen mit identischer Distanz — welche 6 der Median sieht, haengt
    # sonst an der Sortier-Reihenfolge (nicht wohldefiniert bei Ties).
    if aiv is None:
        atm = win.loc[(win["strike"] - S).abs().sort_values().index[:6], "iv"]
        aiv = float(atm.median()) if len(atm) else None
    hdr = f"#spot={spot:.2f};dte={dte:.1f};mult={mult:g};date={day}"
    if aiv:
        # ATM-IV der vollen Kette (auch OI=0-Zeilen tragen IV-Info) — das
        # Seed-Format transportiert nur OI>0; ohne aiv weicht der EM ~10% ab.
        hdr += f";aiv={aiv:.4f}"
    return hdr + "\n" + "\n".join(rows)


def write_tv_seed(prefix, df, struct, near, today):
    """Seed-Datei fuers oeffentliche GEX Profile. Als FUNKTION an beiden
    Pfaden (voller Lauf UND --eu) - vorher schrieb nur der volle Lauf;
    der --eu-Morgenlauf liess die Seeds auf Vortags-Stand (Befund 21.07.:
    DAX.txt trug noch date=2026-07-20 im Alt-Format)."""
    try:
        R = float(struct.get("R") or 1.0)
        tvdir = ROOT / "tv_seed"; tvdir.mkdir(exist_ok=True)
        sb = tv_seed_block(df[df["dte"] >= STRUCT_MIN_DTE], struct["spot"], today, R,
                           aiv=struct.get("atm_iv"))
        nb = tv_seed_block(df[df["dte"] <= NEAR_MAX_DTE], struct["spot"], today, R,
                           aiv=(near or {}).get("atm_iv"))
        if sb:
            out = "=== STRUCTURE (7-45 DTE) — Feld 1 ===\n" + sb
            if nb:
                out += "\n\n=== NEAR (0-5 DTE) — Feld 2 ===\n" + nb
            (tvdir / f"{prefix}.txt").write_text(out + "\n", encoding="utf-8")
    except Exception as e:
        print(f"[warn] {prefix}: TV-Seed fehlgeschlagen ({e})")


def append_row(ticker, d, value):
    f = DATA / f"{ticker}.csv"
    stamp = d.strftime("%Y%m%d") + "T"
    rows = []
    if f.exists():
        rows = [ln.strip() for ln in f.read_text().splitlines() if ln.strip()]
        rows = [r for r in rows if not r.startswith(stamp)]
    v = round(float(value or 0.0), 2)
    rows.append(f"{stamp},{v},{v},{v},{v},0")
    rows.sort()
    f.write_text("\n".join(rows) + "\n")


def write_symbol_info(tickers, meta):
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
    (SYM / "gamma-seed.json").write_text(json.dumps(info, indent=2))


AUTO_TEMPLATE = r'''//@version=6
// Gamma Levels v3 (Auto) [KruegerAlgorithms] - AUTO-GENERATED by build_seed.py (DO NOT edit)
// STRUCTURE map (7-45 DTE) = thick lines | NEAR map (0-5 DTE) = dotted = daily weather/pinning
// v3: Vanna/Charm strikes + VIX regime in the label (context, unvalidated - not a signal).
// Template is deliberately pure ASCII (the .bat rituals copy via `clip` = ANSI).
// Daily BEFORE US open: `python build_seed.py` -> paste the whole file into the Pine editor -> Save.
indicator("Gamma Levels v3 (Auto) [KruegerAlgorithms]", overlay = true)

// ===== DAILY LEVELS in INDEX POINTS (auto-generated __DATE__) =====
__LEVELS__
// ==================================================================

idx        = input.string("Auto", "Index", options = ["Auto", "NQ", "DOW", "GOLD", "DAX", "FTSE"])
offset     = input.float(0.0, "Manual offset (points, broker basis)")
neutralPct = input.float(0.3, "Flip zone (+/- %)", minval = 0.05, step = 0.05)
showReg    = input.bool(true, "Regime background (green/red/grey)")

grpS = "STRUCTURE map (7-45 DTE) - stable daily lines"
showFlip = input.bool(true,  "FLIP - yellow, thick",                     group = grpS)
showCW   = input.bool(true,  "CALL WALL - red, thick",                   group = grpS)
showPW   = input.bool(true,  "PUT WALL - green, thick",                  group = grpS)
showCW2  = input.bool(true,  "CALL WALL 2 (strike shelf) - red, dashed",    group = grpS)
showPW2  = input.bool(true,  "PUT WALL 2 (strike shelf) - green, dashed",   group = grpS)

grpN = "NEAR map (0-5 DTE) - 0DTE daily weather/pinning"
showNCW  = input.bool(true,  "0DTE CALL WALL - orange, dotted",          group = grpN)
showNPW  = input.bool(true,  "0DTE PUT WALL - teal, dotted",             group = grpN)
showNF   = input.bool(false, "0DTE FLIP - yellow, dotted",               group = grpN)

grpX = "Other"
showEM   = input.bool(true,  "EXPECTED MOVE +/-1 day - blue, dotted",    group = grpX)
showMP   = input.bool(false, "MAX PAIN - grey, dotted",                  group = grpX)

grpV = "FLOW & VIX (context, unvalidated - not a trade signal)"
showVanna = input.bool(true,  "VANNA strike - purple, dotted",           group = grpV)
showCharm = input.bool(true,  "CHARM strike - aqua, dotted",             group = grpV)
showVix   = input.bool(true,  "VIX regime in label (CBOE:VIX)",          group = grpV)

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
off(x) => x > 0 ? x + offset : x

flip  = off(pick(NQ_FLIP, DOW_FLIP, GOLD_FLIP, DAX_FLIP, FTSE_FLIP))
cw    = off(pick(NQ_CW,   DOW_CW,   GOLD_CW,   DAX_CW,   FTSE_CW))
pw    = off(pick(NQ_PW,   DOW_PW,   GOLD_PW,   DAX_PW,   FTSE_PW))
cw2   = off(pick(NQ_CW2,  DOW_CW2,  GOLD_CW2,  DAX_CW2,  FTSE_CW2))
pw2   = off(pick(NQ_PW2,  DOW_PW2,  GOLD_PW2,  DAX_PW2,  FTSE_PW2))
ncw   = off(pick(NQ_NCW,  DOW_NCW,  GOLD_NCW,  DAX_NCW,  FTSE_NCW))
npw   = off(pick(NQ_NPW,  DOW_NPW,  GOLD_NPW,  DAX_NPW,  FTSE_NPW))
nflip = off(pick(NQ_NF,   DOW_NF,   GOLD_NF,   DAX_NF,   FTSE_NF))
mp    = off(pick(NQ_MP,   DOW_MP,   GOLD_MP,   DAX_MP,   FTSE_MP))
spotL = pick(NQ_SPOT, DOW_SPOT, GOLD_SPOT, DAX_SPOT, FTSE_SPOT)
em    = pick(NQ_EM,   DOW_EM,   GOLD_EM,   DAX_EM,   FTSE_EM)
van   = pick(NQ_VAN,  DOW_VAN,  GOLD_VAN,  DAX_VAN,  FTSE_VAN)     // USD millions, sign = dealer convention
vank  = off(pick(NQ_VANK, DOW_VANK, GOLD_VANK, DAX_VANK, FTSE_VANK))
chm   = pick(NQ_CHM,  DOW_CHM,  GOLD_CHM,  DAX_CHM,  FTSE_CHM)
chmk  = off(pick(NQ_CHMK, DOW_CHMK, GOLD_CHMK, DAX_CHMK, FTSE_CHMK))

// ---- VIX regime (yesterday's daily close = confirmed, no repaint) ----
// Tertiles relative to the last 250 trading days; tilt per validated finding:
// high/rising -> decision day (trend OR whipsaw), low/falling -> chop.
[vix1, vix2, vp33, vp67] = request.security("CBOE:VIX", "D",
     [close[1], close[2],
      ta.percentile_linear_interpolation(close[1], 250, 33.333),
      ta.percentile_linear_interpolation(close[1], 250, 66.667)],
     ignore_invalid_symbol = true)
vixReg  = na(vix1) or na(vp33) ? "n/a" : vix1 <= vp33 ? "LOW" : vix1 >= vp67 ? "HIGH" : "MID"
vixDir  = na(vix1) or na(vix2) ? "" : vix1 > vix2 + 0.05 ? "rising" : vix1 < vix2 - 0.05 ? "falling" : "flat"
vixTilt = vixReg == "n/a" ? "" :
     (vixReg == "HIGH" or vixDir == "rising") ? "decision tilt (trend/whipsaw, little chop)" :
     (vixReg == "LOW" and vixDir != "rising") ? "chop tilt" : "neutral"

distPct = flip > 0 ? (close - flip) / flip * 100 : na
reg = flip <= 0 ? -99 : math.abs(distPct) < neutralPct ? 0 : distPct > 0 ? 1 : -1
bgcolor(showReg and reg != -99 ? (reg == 1 ? color.new(color.green, 93) : reg == -1 ? color.new(color.red, 93) : color.new(color.gray, 90)) : na)

levTime = timestamp("GMT", LEV_Y, LEV_M, LEV_D, 23, 59)
isStale = (timenow - levTime) > 1000 * 60 * 60 * 36

var line  lF = na, var line lC = na, var line lP = na, var line lC2 = na, var line lP2 = na
var line  lNC = na, var line lNP = na, var line lNF = na, var line lM = na
var line  lE1 = na, var line lE2 = na
var line  lVA = na, var line lCH = na
var label lab = na
if barstate.islast
    line.delete(lF), line.delete(lC), line.delete(lP), line.delete(lC2), line.delete(lP2)
    line.delete(lNC), line.delete(lNP), line.delete(lNF), line.delete(lM)
    line.delete(lE1), line.delete(lE2)
    line.delete(lVA), line.delete(lCH)
    label.delete(lab)
    x1 = bar_index - 400
    if showFlip and flip > 0
        lF := line.new(x1, flip, bar_index, flip, color = color.yellow, width = 2, extend = extend.right)
    if showCW and cw > 0
        lC := line.new(x1, cw, bar_index, cw, color = color.red, width = 2, extend = extend.right)
    if showPW and pw > 0
        lP := line.new(x1, pw, bar_index, pw, color = color.green, width = 2, extend = extend.right)
    if showCW2 and cw2 > 0
        lC2 := line.new(x1, cw2, bar_index, cw2, color = color.new(color.red, 45), width = 1, extend = extend.right, style = line.style_dashed)
    if showPW2 and pw2 > 0
        lP2 := line.new(x1, pw2, bar_index, pw2, color = color.new(color.green, 45), width = 1, extend = extend.right, style = line.style_dashed)
    if showNCW and ncw > 0
        lNC := line.new(x1, ncw, bar_index, ncw, color = color.orange, width = 1, extend = extend.right, style = line.style_dotted)
    if showNPW and npw > 0
        lNP := line.new(x1, npw, bar_index, npw, color = color.teal, width = 1, extend = extend.right, style = line.style_dotted)
    if showNF and nflip > 0
        lNF := line.new(x1, nflip, bar_index, nflip, color = color.new(color.yellow, 35), width = 1, extend = extend.right, style = line.style_dotted)
    if showMP and mp > 0
        lM := line.new(x1, mp, bar_index, mp, color = color.gray, width = 1, extend = extend.right, style = line.style_dotted)
    if showEM and em > 0 and spotL > 0
        lE1 := line.new(x1, spotL + em + offset, bar_index, spotL + em + offset, color = color.new(color.blue, 55), width = 1, extend = extend.right, style = line.style_dotted)
        lE2 := line.new(x1, spotL - em + offset, bar_index, spotL - em + offset, color = color.new(color.blue, 55), width = 1, extend = extend.right, style = line.style_dotted)
    if showVanna and vank > 0
        lVA := line.new(x1, vank, bar_index, vank, color = color.new(color.purple, 40), width = 1, extend = extend.right, style = line.style_dotted)
    if showCharm and chmk > 0
        lCH := line.new(x1, chmk, bar_index, chmk, color = color.new(color.aqua, 45), width = 1, extend = extend.right, style = line.style_dotted)
    regTxt = reg == 1 ? "LONG GAMMA (pin/reversion)" : reg == -1 ? "SHORT GAMMA (trend/amplify)" : reg == 0 ? "FLIP ZONE (no signal)" : "no data"
    flowTxt = (van != 0.0 or chm != 0.0) ?
         "\nVanna " + (van > 0 ? "+" : "") + str.tostring(van, "#.#") + "M (vol down = " + (van > 0 ? "BUY" : "SELL") + ")" + (vank > 0 ? " @" + str.tostring(vank, format.mintick) : "") +
         "  |  Charm " + (chm > 0 ? "+" : "") + str.tostring(chm, "#.#") + "M (" + (chm > 0 ? "time = buy support" : "time = sell pressure") + ")" + (chmk > 0 ? " @" + str.tostring(chmk, format.mintick) : "") : ""
    vixTxt = showVix and vixReg != "n/a" ?
         "\nVIX " + str.tostring(vix1, "#.##") + " (" + vixReg + ", " + vixDir + ") -> " + vixTilt : ""
    txt = sel + " - " + regTxt + (flip > 0 ? "  Flip " + str.tostring(flip, format.mintick) + " (" + str.tostring(distPct, "#.##") + "%)" : "") + flowTxt + vixTxt + "\nLevels as of " + LEV_DATE + (isStale ? "  !! STALE - run build_seed !!" : "")
    lab := label.new(bar_index, high, txt, style = label.style_label_left, color = isStale ? color.new(color.orange, 10) : reg == 1 ? color.new(color.green, 25) : reg == -1 ? color.new(color.red, 25) : color.new(color.gray, 25), textcolor = color.white, size = size.small)

// ===== ALERTS (selectable in the alert dialog) =====
alertcondition(ta.crossover(close, flip),  "Gamma: Flip cross UP",   "Spot crosses the gamma flip UPWARD -> towards long gamma/pinning")
alertcondition(ta.crossunder(close, flip), "Gamma: Flip cross DOWN", "Spot crosses the gamma flip DOWNWARD -> short gamma/amplify")
alertcondition(ta.crossunder(close, pw),   "Gamma: Put wall BREAK",  "Put wall broken -> trapdoor open (amplify risk)")
alertcondition(ta.crossover(close, pw),    "Gamma: Put wall RECLAIM", "Put wall reclaimed from below -> reversal signature (dealer buybacks)")
alertcondition(ta.crossover(close, cw),    "Gamma: Call wall break UP", "Call wall exceeded -> usually magnet/pin, rarely follow-through")
'''


def gen_auto_pine(levels, today, note=""):
    order = ["NQ", "DOW", "GOLD", "DAX", "FTSE"]
    zero = {k: 0.0 for k in ["flip", "cw", "pw", "cw2", "pw2", "ncw", "npw",
                             "nflip", "mp", "spot", "em",
                             "van", "vank", "chm", "chmk"]}
    lines = []
    for k in order:
        v = {**zero, **levels.get(k, {})}
        for name, key in [("FLIP", "flip"), ("CW", "cw"), ("PW", "pw"),
                          ("CW2", "cw2"), ("PW2", "pw2"), ("NCW", "ncw"),
                          ("NPW", "npw"), ("NF", "nflip"), ("MP", "mp"),
                          ("SPOT", "spot"), ("EM", "em"),
                          ("VAN", "van"), ("VANK", "vank"),
                          ("CHM", "chm"), ("CHMK", "chmk")]:
            lines.append(f"{k}_{name} = {v[key]:.2f}")
    lines.append(f'LEV_DATE = "{today}{note}"')
    lines.append(f"LEV_Y = {today.year}")
    lines.append(f"LEV_M = {today.month}")
    lines.append(f"LEV_D = {today.day}")
    pine = AUTO_TEMPLATE.replace("__LEVELS__", "\n".join(lines)).replace(
        "__DATE__", str(today))
    (ROOT / "GammaLevels_auto.pine").write_text(pine, encoding="utf-8")
    return ROOT / "GammaLevels_auto.pine"


def g(lv, key):
    return (lv or {}).get(key) or 0.0


def main():
    today = date.today()
    tickers, meta, copyrows = [], {}, []
    print(f"=== Gamma-Seed-Build v2  {today} ===\n")
    for prefix, ccy, thunk in CONFIG:
        try:
            ch = thunk()
            # SANITY-GATE 2026-07-13: Montag-vor-US-Open lieferte Yahoo kollabierte
            # IVs (Median 0.031, 44% der Kette IV<=0.01) -> Flip/CW/PW klebten am
            # ATM, EM1d ±1 Punkt, und der Muell wurde eingefroren. Degenerierte
            # Kette => Markt skippen, gespeicherte Level bleiben stehen.
            if "iv" in ch.df.columns and "dte" in ch.df.columns:
                _s = ch.df[ch.df["dte"] >= STRUCT_MIN_DTE]
                _med_iv = float(_s["iv"].median()) if len(_s) else 0.0
                if _med_iv < 0.05:
                    print(f"[DEGENERIERT] {prefix}: Median-IV {_med_iv:.3f} < 0.05 "
                          f"(Kette stale — Wochenende/vor US-Open?). Geskippt, alte Level bleiben.")
                    continue
        except Exception as e:
            print(f"[skip] {prefix}: {e}")
            continue
        df = ch.df
        struct = gex.compute_levels(df[df["dte"] >= STRUCT_MIN_DTE], ch.spot)
        near = gex.compute_levels(df[df["dte"] <= NEAR_MAX_DTE], ch.spot)
        if struct is None:
            print(f"[skip] {prefix}: keine Struktur-Kette")
            continue

        # ETF-Level -> Index-Punkte (Verhaeltnis Index/ETF, taggleich)
        isym = INDEX_SYM.get(prefix)
        if isym:
            try:
                ispot = P.index_spot(isym)
                R = ispot / struct["spot"]
                for lv in (struct, near):
                    if lv is None:
                        continue
                    for kk in SCALE_KEYS:
                        if lv.get(kk) is not None:
                            lv[kk] = lv[kk] * R
                struct["etf_spot"] = struct["spot"]
                struct["spot"] = ispot
                struct["R"] = round(R, 4)
            except Exception as e:
                print(f"[warn] {prefix}: Index-Spot {isym} fehlgeschlagen ({e})")

        copyrows.append((prefix, struct, near))

        write_tv_seed(prefix, df, struct, near, today)

        print(f"{prefix:5s} spot {struct['spot']:.0f} | {struct['regime'].upper():7s} "
              f"| Flip {g(struct,'gamma_flip'):.0f} ({struct['dist_to_flip_pct'] or 0:+.2f}%) "
              f"| CW {g(struct,'call_wall'):.0f}/{g(struct,'call_wall2'):.0f} "
              f"| PW {g(struct,'put_wall'):.0f}/{g(struct,'put_wall2'):.0f} "
              f"| EM1d ±{g(struct,'exp_move_1d'):.0f} "
              f"| Nah-CW {g(near,'call_wall'):.0f} Nah-PW {g(near,'put_wall'):.0f}")

        vals = {"FLIP": g(struct, "gamma_flip"), "CWALL": g(struct, "call_wall"),
                "PWALL": g(struct, "put_wall"), "CWALL2": g(struct, "call_wall2"),
                "PWALL2": g(struct, "put_wall2"), "NCWALL": g(near, "call_wall"),
                "NPWALL": g(near, "put_wall"), "NFLIP": g(near, "gamma_flip"),
                "MAXPAIN": g(struct, "max_pain"),
                "EM1D": g(struct, "exp_move_1d"),
                "GEXBN": struct["total_gex"] / 1e9, "SPOT": struct["spot"],
                "VANNA": (struct.get("total_vanna") or 0.0) / 1e6,
                "VANNAK": g(struct, "vanna_strike"),
                "CHARM": (struct.get("total_charm") or 0.0) / 1e6,
                "CHARMK": g(struct, "charm_strike")}
        for m in METRICS:
            tk = f"{prefix}_{m}"
            tickers.append(tk)
            meta[tk] = (f"{prefix} {DESC[m]}", ccy, 1 if m == "GEXBN" else 100)
            append_row(tk, today, vals[m])

    if tickers:
        write_symbol_info(tickers, meta)
        print(f"\nGeschrieben: {len(tickers)} Ticker -> {DATA}")

    lines = [f"=== GAMMA-LEVEL v2  {today}  (Struktur 7-45 DTE | Nah 0-5 DTE) ==="]
    for prefix, s, n in copyrows:
        lines.append(
            f"{prefix:5s} STRUKT | {s['regime'].upper():7s} | Flip {g(s,'gamma_flip'):.2f} "
            f"| CW {g(s,'call_wall'):.2f} (2nd {g(s,'call_wall2'):.2f}) "
            f"| PW {g(s,'put_wall'):.2f} (2nd {g(s,'put_wall2'):.2f}) "
            f"| EM1d ±{g(s,'exp_move_1d'):.2f} | Spot {s['spot']:.2f}")
        if s.get("total_vanna") is not None:
            lines.append(
                f"{prefix:5s} FLOW   | Vanna {s['total_vanna']/1e6:+.0f}M ({s.get('vanna_flow','?')} "
                f"@{g(s,'vanna_strike'):.0f}) | Charm {s['total_charm']/1e6:+.0f}M "
                f"({s.get('charm_flow','?')} @{g(s,'charm_strike'):.0f})")
        if n:
            lines.append(
                f"{prefix:5s} NAH    | CW {g(n,'call_wall'):.2f} | PW {g(n,'put_wall'):.2f} "
                f"| Flip {g(n,'gamma_flip'):.2f}")
    block = "\n".join(lines)
    print("\n" + block)
    (ROOT / "today_levels.txt").write_text(block + "\n", encoding="utf-8")

    # SANITY-GATE 2026-07-13: mit gespeicherten Leveln starten und nur frische
    # Maerkte ueberschreiben — geskippte (degenerierte) behalten so ihre alten
    # Linien im Pine, statt komplett zu verschwinden.
    levels = load_stored_levels()
    for p, s, n in copyrows:
        levels[p] = {"flip": g(s, "gamma_flip"), "cw": g(s, "call_wall"),
                     "pw": g(s, "put_wall"), "cw2": g(s, "call_wall2"),
                     "pw2": g(s, "put_wall2"), "ncw": g(n, "call_wall"),
                     "npw": g(n, "put_wall"), "nflip": g(n, "gamma_flip"),
                     "mp": g(s, "max_pain"),
                     "spot": s["spot"], "em": g(s, "exp_move_1d"),
                     "van": (s.get("total_vanna") or 0.0) / 1e6,
                     "vank": g(s, "vanna_strike"),
                     "chm": (s.get("total_charm") or 0.0) / 1e6,
                     "chmk": g(s, "charm_strike")}
    auto = gen_auto_pine(levels, today)
    print(f"\nAUTO-Indikator v2 regeneriert -> {auto}")
    print("   => Datei komplett in den TradingView-Pine-Editor kopieren (1x taeglich, vor US-Open).")


def load_stored_levels():
    """Letzte gespeicherte Tages-Level aus data/*.csv (fuer regen/intraday)."""
    m2k = {"FLIP": "flip", "CWALL": "cw", "PWALL": "pw", "CWALL2": "cw2",
           "PWALL2": "pw2", "NCWALL": "ncw", "NPWALL": "npw", "NFLIP": "nflip",
           "MAXPAIN": "mp", "SPOT": "spot", "EM1D": "em",
           "VANNA": "van", "VANNAK": "vank", "CHARM": "chm", "CHARMK": "chmk"}
    levels = {}
    for f in DATA.glob("*.csv"):
        parts = f.stem.split("_", 1)
        if len(parts) != 2 or parts[1] not in m2k:
            continue
        prefix, metric = parts
        last = [ln for ln in f.read_text().splitlines() if ln.strip()][-1]
        levels.setdefault(prefix, {k: 0.0 for k in m2k.values()})
        levels[prefix][m2k[metric]] = float(last.split(",")[1])
    return levels


def intraday_update():
    """NACHMITTAGS-RITUAL: nur die 0DTE-Linien aus dem HEUTIGEN Volumen
    aktualisieren (die einzige Zutat, die sich intraday wirklich erneuert).
    Struktur-Karte bleibt eingefroren. Kein Schreiben in die Tages-CSVs."""
    from datetime import datetime
    today = date.today()
    levels = load_stored_levels()
    print(f"=== 0DTE-Volumen-Update {datetime.now():%H:%M} ===")
    for prefix, ccy, thunk in CONFIG:
        if prefix not in levels:
            continue
        try:
            ch = P.yf_us({"NQ": "QQQ", "DOW": "DIA", "GOLD": "GLD"}[prefix],
                         max_days=1)
        except Exception as e:
            print(f"[skip] {prefix}: {e}")
            continue
        df = ch.df[ch.df["vol"] > 0]
        if df.empty:
            print(f"[skip] {prefix}: kein 0DTE-Volumen")
            continue
        try:
            R = P.index_spot(INDEX_SYM[prefix]) / ch.spot
        except Exception:
            R = 1.0
        calls = df[df["type"] == "C"].groupby("strike")["vol"].sum()
        puts = df[df["type"] == "P"].groupby("strike")["vol"].sum()
        ncw = float(calls.idxmax()) * R if len(calls) else 0.0
        npw = float(puts.idxmax()) * R if len(puts) else 0.0
        levels[prefix]["ncw"] = ncw
        levels[prefix]["npw"] = npw
        print(f"{prefix:5s} 0DTE-Volumen-Walls: CW {ncw:.0f} | PW {npw:.0f} "
              f"(Call-Vol {calls.sum():,.0f} / Put-Vol {puts.sum():,.0f})")
    out = gen_auto_pine(levels, today, note=" +0DTE volume update")
    print(f"\nPine aktualisiert -> {out} (nur gepunktete Linien neu, "
          f"Struktur unveraendert). In den Pine-Editor kopieren.")


def eu_morning_update():
    """MORGEN-RITUAL (~08:30 Berlin, vor DAX-Open 09:00): NUR DAX frisch von der
    Eurex-API (EOD-Settlement/OI von gestern, ueber Nacht publiziert). US-Level
    bleiben die gespeicherten vom letzten 14:00-Lauf — kein yfinance-Fetch, kein
    Repaint-Risiko (die Eurex-Quelle updated eh nur 1x/Tag)."""
    today = date.today()
    levels = load_stored_levels()
    try:
        ch = P.eurex_dax()
    except Exception as e:
        print(f"[FEHLER] DAX: {e}")
        return
    df = ch.df
    struct = gex.compute_levels(df[df["dte"] >= STRUCT_MIN_DTE], ch.spot)
    near = gex.compute_levels(df[df["dte"] <= NEAR_MAX_DTE], ch.spot)
    if struct is None:
        print("[FEHLER] DAX: keine Struktur-Kette")
        return
    write_tv_seed("DAX", df, struct, near, today)
    # FIX 2026-07-13: Vanna/Charm-Metriken (12.07. in METRICS ergaenzt) fehlten im
    # EU-Pfad -> KeyError 'VANNA'. vals + levels spiegeln jetzt exakt main() (Z. 302ff).
    vals = {"FLIP": g(struct, "gamma_flip"), "CWALL": g(struct, "call_wall"),
            "PWALL": g(struct, "put_wall"), "CWALL2": g(struct, "call_wall2"),
            "PWALL2": g(struct, "put_wall2"), "NCWALL": g(near, "call_wall"),
            "NPWALL": g(near, "put_wall"), "NFLIP": g(near, "gamma_flip"),
            "MAXPAIN": g(struct, "max_pain"), "EM1D": g(struct, "exp_move_1d"),
            "GEXBN": struct["total_gex"] / 1e9, "SPOT": struct["spot"],
            "VANNA": (struct.get("total_vanna") or 0.0) / 1e6,
            "VANNAK": g(struct, "vanna_strike"),
            "CHARM": (struct.get("total_charm") or 0.0) / 1e6,
            "CHARMK": g(struct, "charm_strike")}
    for m in METRICS:
        append_row(f"DAX_{m}", today, vals[m])
    levels["DAX"] = {"flip": g(struct, "gamma_flip"), "cw": g(struct, "call_wall"),
                     "pw": g(struct, "put_wall"), "cw2": g(struct, "call_wall2"),
                     "pw2": g(struct, "put_wall2"), "ncw": g(near, "call_wall"),
                     "npw": g(near, "put_wall"), "nflip": g(near, "gamma_flip"),
                     "mp": g(struct, "max_pain"), "spot": struct["spot"],
                     "em": g(struct, "exp_move_1d"),
                     "van": (struct.get("total_vanna") or 0.0) / 1e6,
                     "vank": g(struct, "vanna_strike"),
                     "chm": (struct.get("total_charm") or 0.0) / 1e6,
                     "chmk": g(struct, "charm_strike")}
    print(f"DAX   spot {struct['spot']:.0f} | {struct['regime'].upper():7s} "
          f"| Flip {g(struct,'gamma_flip'):.0f} ({struct['dist_to_flip_pct'] or 0:+.2f}%) "
          f"| CW {g(struct,'call_wall'):.0f}/{g(struct,'call_wall2'):.0f} "
          f"| PW {g(struct,'put_wall'):.0f}/{g(struct,'put_wall2'):.0f} "
          f"| EM1d ±{g(struct,'exp_move_1d'):.0f} "
          f"| Nah-CW {g(near,'call_wall'):.0f} Nah-PW {g(near,'put_wall'):.0f}")
    if struct.get("total_vanna") is not None:
        print(f"DAX   FLOW | Vanna {struct['total_vanna']/1e6:+.0f}M ({struct['vanna_flow']} "
              f"@{g(struct,'vanna_strike'):.0f}) | Charm {struct['total_charm']/1e6:+.0f}M "
              f"({struct['charm_flow']} @{g(struct,'charm_strike'):.0f})")
    out = gen_auto_pine(levels, today, note=" EU morning run (US = previous day)")
    print(f"\nPine aktualisiert -> {out}")
    print("   => In den Pine-Editor kopieren. US-Linien = Stand Vortag, um 14:00 vollen Lauf machen.")


if __name__ == "__main__":
    import sys
    if "--intraday" in sys.argv:
        intraday_update()
    elif "--eu" in sys.argv:
        eu_morning_update()
    else:
        main()
