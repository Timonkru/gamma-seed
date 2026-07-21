"""
FRAGE: Rechnet das oeffentliche TV-Skript (Gamma Exposure Profile — Manual
    Chain Input) nach dem v1.1-Fix denselben Flip wie das private Tool?

HINTERGRUND (Timons Befund 2026-07-20): tv_seed_block schrieb EINE OI-
    gewichtete Durchschnitts-DTE fuer die ganze Karte. Gamma waechst ~1/sqrt(T)
    — die Mittelung verschob den DOW-Flip um −368 Punkte und kippte das
    angezeigte Regime (privat SHORT, oeffentlich LONG). Fix: Feld 5 = eigene
    OI-gewichtete DTE je Strike-Zeile; das Pine rechnet seit v1.1 per Strike.

METHODE:
    1. DAX-Kette laden (Eurex-Web-API, read-only — KEIN Pine-/CSV-Schreiben,
       die eingefrorene Tageskarte bleibt unberuehrt).
    2. Referenz: gex.gamma_flip auf der VOLLEN Kette (per-Option-T) — identisch
       zur Rechnung des privaten Tools.
    3. tv_seed_block(win) erzeugen, den Block wie das Pine parsen (Header-
       Fallbacks, Feld 4 iv / Feld 5 dte) und den Flip mit der PINE-Logik
       rechnen (120er-Grid ueber min..max Strike, lineare Interpolation,
       Kreuzung naechst am Spot).
    4. PASS, wenn |Differenz| <= max(0.05 % vom Spot, halbe Grid-Schrittweite)
       — die Grid-Aufloesung ist die verbleibende legitime Abweichung.
    Zusatz: derselbe Vergleich mit ABGESCHNITTENEM Feld 5 zeigt den alten
    Fehler (erwartet: deutlich groessere Abweichung — Regressionsnachweis).

CAVEATS: Nur DAX (einzige tokenfreie Quelle); Eurex liefert EOD — der
    Absolutwert kann vom eingefrorenen Tages-Label abweichen, fuer die
    PARITAET beider Rechenwege ist das egal (gleiche Kette auf beiden Seiten).
"""
import math
import sys

import gex
import providers
from build_seed import tv_seed_block, STRUCT_MIN_DTE

TOL_PCT = 0.0005  # 0.05 % vom Spot


def npdf(x):
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


def pine_gamma(S, K, T, sig):
    if T <= 0 or sig <= 0 or S <= 0 or K <= 0:
        return 0.0
    srt = sig * math.sqrt(T)
    d1 = (math.log(S / K) + 0.5 * sig * sig * T) / srt
    return npdf(d1) / (S * srt)


def parse_block(block):
    """Nachbau von f_parse: Header + strike;callOI;putOI[;iv[;dte]]."""
    hdr = {"mult": 1.0, "iv": 0.2}
    rows = []
    for ln in block.strip().split("\n"):
        ln = ln.strip().replace(" ", "")
        if not ln:
            continue
        if ln.startswith("#"):
            for kv in ln[1:].split(";"):
                k, _, v = kv.partition("=")
                if k and v and k != "date":
                    hdr[k] = float(v)
            continue
        p = ln.split(";")
        if len(p) >= 3:
            rows.append((float(p[0]), float(p[1]), float(p[2]),
                         float(p[3]) if len(p) >= 4 else -1.0,
                         float(p[4]) if len(p) >= 5 else -1.0))
    return hdr, rows


def pine_flip(hdr, rows):
    """Nachbau von f_levels/f_totalGex: per-Strike-T, 120er-Grid, Kreuzung
    naechst am Spot."""
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
    best, bd = None, float("inf")
    prev_s, prev_v = lo, total(lo)
    for j in range(1, 121):
        s = lo + (hi - lo) * j / 120.0
        v = total(s)
        if (prev_v < 0 <= v) or (prev_v >= 0 > v):
            x = prev_s + (s - prev_s) * (0 - prev_v) / (v - prev_v)
            if abs(x - spot) < bd:
                bd, best = abs(x - spot), x
        prev_s, prev_v = s, v
    # Stufe 2 (v1.2.1): feiner Rescan +/- 1 Grobschritt um die Kreuzung
    step = (hi - lo) / 120.0
    if best is not None:
        flo, fhi = max(lo, best - step), min(hi, best + step)
        b2, bd2 = None, float("inf")
        prev_s, prev_v = flo, total(flo)
        for j in range(1, 61):
            s2 = flo + (fhi - flo) * j / 60.0
            v2 = total(s2)
            if (prev_v < 0 <= v2) or (prev_v >= 0 > v2):
                x = prev_s + (s2 - prev_s) * (0 - prev_v) / (v2 - prev_v)
                if abs(x - spot) < bd2:
                    bd2, b2 = abs(x - spot), x
            prev_s, prev_v = s2, v2
        if b2 is not None:
            best, step = b2, (fhi - flo) / 60.0
    return best, step


def main():
    print("=" * 72)
    print(" TV-Seed-Paritaetstest — privater Flip vs. Pine-Nachbau (DAX)")
    print("=" * 72)
    chain = providers.eurex_dax()
    spot = chain.spot
    win = chain.df[chain.df["dte"] >= STRUCT_MIN_DTE]

    ref = gex.gamma_flip(win, spot)
    print(f"Referenz (volle Kette, per-Option-T): Flip {ref:,.1f} | Spot {spot:,.1f}")

    block = tv_seed_block(win, spot, "selftest", 1.0)
    if block is None:
        print("FEHLER: tv_seed_block lieferte nichts"); sys.exit(2)
    hdr, rows = parse_block(block)
    has_dte = sum(1 for r in rows if r[4] > 0)
    print(f"Seed-Block: {len(rows)} Strikes, davon {has_dte} mit eigener DTE (Feld 5)")

    flip_new, step = pine_flip(hdr, rows)
    tol = max(spot * TOL_PCT, step / 2.0)
    d_new = flip_new - ref
    ok = abs(d_new) <= tol
    print(f"Pine-Nachbau (per-Strike-DTE):        Flip {flip_new:,.1f} | "
          f"Diff {d_new:+,.1f} | Toleranz ±{tol:,.1f} -> {'PASS' if ok else 'FAIL'}")

    # Regressionsnachweis: Feld 5 abschneiden = alter Zustand
    rows_old = [(k, c, p, iv, -1.0) for k, c, p, iv, _ in rows]
    flip_old, _ = pine_flip(hdr, rows_old)
    print(f"Alter Zustand (eine Mittel-DTE):      Flip {flip_old:,.1f} | "
          f"Diff {flip_old - ref:+,.1f}  <- der behobene Fehler")

    print("-" * 72)
    print("VORBEHALT: nur DAX/Eurex (EOD); Paritaet der Rechenwege, kein")
    print("Vergleich gegen die eingefrorene Tageskarte.")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
