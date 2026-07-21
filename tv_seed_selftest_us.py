"""
FRAGE: Rechnet das oeffentliche GEX Profile nach dem v1.6-Umbau (kompaktes
    Format + doppeltes Budget) auch bei den US-Maerkten dieselben Level wie
    das private Tool? Offene Baustelle war NQ: +561 Punkte Flip-Abweichung,
    weil der Zeichen-Trim bei der grossen, stark degenerierten QQQ-Kette ueber
    80 %% der Zeilen wegwarf.

METHODE (identisch zum DAX-Selftest, nur ueber yfinance):
    1. Kette laden, Struktur-Fenster (>= 7 DTE) schneiden.
    2. Referenz: gex.gamma_flip auf der VOLLEN Kette (per-Option-T), Level mit
       R auf Indexpunkte skaliert — exakt der private Rechenweg.
    3. tv_seed_block erzeugen, wie das Pine parsen, Flip mit der Pine-Logik
       rechnen (120er-Grid + feiner Rescan).
    4. PASS bei |Diff| <= max(0.05 %% vom Spot, halbe Grid-Schrittweite).

AUFRUF: python tv_seed_selftest_us.py [NQ|DOW|GOLD]   (ohne Argument: alle)

CAVEATS: yfinance-Ketten sind tagesabhaengig; nach US-Feiertagen oder bei
    Feed-Ausfaellen degeneriert (IV-Fallback greift dann). Der Test misst die
    PARITAET beider Rechenwege auf derselben Kette, nicht die Datenqualitaet.
"""
import math
import sys

import gex
import providers
from build_seed import tv_seed_block, STRUCT_MIN_DTE

MARKETS = {"NQ": ("QQQ", "^NDX"), "DOW": ("DIA", "^DJI"), "GOLD": ("GLD", "GC=F")}
TOL_PCT = 0.0005


def npdf(x):
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


def pine_gamma(S, K, T, sig):
    if T <= 0 or sig <= 0 or S <= 0 or K <= 0:
        return 0.0
    srt = sig * math.sqrt(T)
    d1 = (math.log(S / K) + 0.5 * sig * sig * T) / srt
    return npdf(d1) / (S * srt)


def parse_block(block):
    hdr = {"mult": 1.0, "iv": 0.2}
    rows = []
    for ln in block.strip().split("\n"):
        ln = ln.strip().replace(" ", "")
        if not ln:
            continue
        if ln.startswith("#"):
            for kv in ln[1:].split(";"):
                k, _, v = kv.partition("=")
                if k and v and k not in ("date", "market", "map"):
                    hdr[k] = float(v)
            continue
        p = ln.split(";")
        if len(p) >= 3:
            rows.append((float(p[0]), float(p[1]), float(p[2]),
                         float(p[3]) if len(p) >= 4 else -1.0,
                         float(p[4]) if len(p) >= 5 else -1.0))
    return hdr, rows


def pine_flip(hdr, rows):
    spot, mult, fiv = hdr["spot"], hdr["mult"], hdr.get("iv", 0.2)
    Thdr = hdr["dte"] / 365.0

    def total(S):
        t = 0.0
        for k, c, p, iv, dt in rows:
            sig = iv if iv > 0 else fiv
            T = dt / 365.0 if dt > 0 else Thdr
            t += pine_gamma(S, k, T, sig) * (c - p) * mult * S * S * 0.01
        return t

    ks = [r[0] for r in rows]
    lo, hi = min(ks), max(ks)
    best, bd, ps, pv = None, float("inf"), lo, total(lo)
    for j in range(1, 121):
        s = lo + (hi - lo) * j / 120.0
        v = total(s)
        if (pv < 0 <= v) or (pv >= 0 > v):
            x = ps + (s - ps) * (0 - pv) / (v - pv)
            if abs(x - spot) < bd:
                bd, best = abs(x - spot), x
        ps, pv = s, v
    step = (hi - lo) / 120.0
    if best is not None:
        flo, fhi = max(lo, best - step), min(hi, best + step)
        b2, bd2, ps, pv = None, float("inf"), flo, total(flo)
        for j in range(1, 61):
            s2 = flo + (fhi - flo) * j / 60.0
            v2 = total(s2)
            if (pv < 0 <= v2) or (pv >= 0 > v2):
                x = ps + (s2 - ps) * (0 - pv) / (v2 - pv)
                if abs(x - spot) < bd2:
                    bd2, b2 = abs(x - spot), x
            ps, pv = s2, v2
        if b2 is not None:
            best, step = b2, (fhi - flo) / 60.0
    return best, step


def run(name):
    etf, idx = MARKETS[name]
    ch = providers.yf_us(etf)
    R = 1.0
    try:
        R = providers.index_spot(idx) / ch.spot
    except Exception as e:
        print(f"  [warn] index_spot({idx}) fehlgeschlagen ({e}) -> R=1")
    win = ch.df[ch.df["dte"] >= STRUCT_MIN_DTE]
    n_chain = int((win["oi"] > 0).sum())
    ref = gex.gamma_flip(win, ch.spot) * R
    spot_idx = ch.spot * R

    block = tv_seed_block(win, spot_idx, "selftest", R, aiv=None, market=name)
    if block is None:
        print(f"{name}: kein Block"); return None
    hdr, rows = parse_block(block)
    flip, step = pine_flip(hdr, rows)
    tol = max(spot_idx * TOL_PCT, step / 2.0)
    d = flip - ref
    ok = abs(d) <= tol
    print(f"{name:5s} Spot {spot_idx:>10,.1f} | Kette {n_chain:5d} Zeilen -> "
          f"Seed {len(rows):4d} ({len(rows)/max(1,n_chain)*100:4.0f} %) | "
          f"{len(block):6d} Zeichen")
    print(f"      Flip privat {ref:>10,.1f} | Seed {flip:>10,.1f} | "
          f"Diff {d:>+8.1f} | Toleranz ±{tol:.1f} -> {'PASS' if ok else 'FAIL'}")
    return ok


def main():
    args = [a.upper() for a in sys.argv[1:]] or list(MARKETS)
    print("=" * 74)
    print(" TV-Seed-Paritaet US-Maerkte (privater Rechenweg vs. Pine-Nachbau)")
    print("=" * 74)
    res = []
    for m in args:
        if m not in MARKETS:
            print(f"unbekannt: {m}"); continue
        try:
            res.append(run(m))
        except Exception as e:
            print(f"{m}: FEHLER {e}")
            res.append(False)
    print("-" * 74)
    print("VORBEHALT: yfinance-Tagesdaten; misst die Paritaet der Rechenwege,")
    print("nicht die Qualitaet der Kette selbst.")
    sys.exit(0 if all(r for r in res if r is not None) else 1)


if __name__ == "__main__":
    main()
