"""
GEX-Kern: Black-Scholes-Gamma -> Gamma Exposure -> Flip / Call-Wall / Put-Wall / Max-Pain.
Provider-agnostisch: bekommt eine standardisierte Optionskette und den Spot, rechnet die Level.

Standardisierte Kette (pandas.DataFrame), Spalten:
    strike  : float   Ausuebungspreis
    type    : 'C'/'P'
    oi      : float   Open Interest (Kontrakte)
    iv      : float   Implied Vol (dezimal, z.B. 0.15)
    T       : float   Restlaufzeit in Jahren
    mult    : float   Kontrakt-Multiplikator (DAX 5, FTSE 10, SPX 100, ...)

Vorzeichen-Konvention (Standard, ABER eine Annahme!): Dealer long Call-Gamma, short Put-Gamma
-> Call-GEX positiv, Put-GEX negativ. Flip = Spot, an dem Gesamt-GEX das Vorzeichen wechselt.
"""
import numpy as np


def _npdf(x):
    return np.exp(-0.5 * x * x) / np.sqrt(2.0 * np.pi)


def bs_gamma(S, K, T, sigma, r=0.0):
    S = np.asarray(S, float); K = np.asarray(K, float)
    T = np.asarray(T, float); sigma = np.asarray(sigma, float)
    with np.errstate(divide="ignore", invalid="ignore"):
        d1 = (np.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * np.sqrt(T))
        g = _npdf(d1) / (S * sigma * np.sqrt(T))
    return np.where(np.isfinite(g), g, 0.0)


# ---- Black-Scholes Preis + IV-Inversion (fuer Quellen mit Settlement-PREIS statt IV,
#      z.B. Eurex/ICE). Spot-basiert, r=0 -> konsistent zur Gamma-Konvention oben. ----
import math


def _Ncdf(x):
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def bs_price(S, K, T, sigma, typ, r=0.0):
    """Europaeischer BS-Preis (Call/Put). sigma<=0 oder T<=0 -> innerer Wert."""
    if sigma <= 0 or T <= 0 or S <= 0 or K <= 0:
        return max(S - K, 0.0) if typ == "C" else max(K - S, 0.0)
    d1 = (math.log(S / K) + (r + 0.5 * sigma * sigma) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    if typ == "C":
        return S * _Ncdf(d1) - K * math.exp(-r * T) * _Ncdf(d2)
    return K * math.exp(-r * T) * _Ncdf(-d2) - S * _Ncdf(-d1)


def implied_vol(price, S, K, T, typ, r=0.0, lo=1e-4, hi=5.0, tol=1e-5, it=80):
    """IV per Bisektion aus dem Optionspreis. None wenn kein Wurzel-Bracket
    (Preis unter innerem Wert / numerisch unmoeglich)."""
    if price is None or T <= 0 or S <= 0 or K <= 0:
        return None
    intrinsic = max(S - K, 0.0) if typ == "C" else max(K - S, 0.0)
    if price <= intrinsic + 1e-9:
        return None
    fa = bs_price(S, K, T, lo, typ, r) - price
    fb = bs_price(S, K, T, hi, typ, r) - price
    if fa * fb > 0:
        return None
    a, b = lo, hi
    for _ in range(it):
        m = 0.5 * (a + b)
        fm = bs_price(S, K, T, m, typ, r) - price
        if abs(fm) < tol:
            return m
        if fa * fm < 0:
            b = m
        else:
            a, fa = m, fm
    return 0.5 * (a + b)


def _signed_gex_at(chain, S, r=0.0):
    """GEX je Option bei hypothetischem Spot S ($ pro 1%-Move). Call +, Put -."""
    g = bs_gamma(S, chain["strike"].values, chain["T"].values, chain["iv"].values, r)
    sign = np.where(chain["type"].values == "C", 1.0, -1.0)
    return sign * g * chain["oi"].values * chain["mult"].values * (S ** 2) * 0.01


# ---- Charm & Vanna (2nd-order Greeks, r=0). Bei q=r=0 sind Vanna und Charm fuer
#      Call und Put desselben Strikes IDENTISCH -> Dealer-Aggregation nutzt dieselbe
#      Vorzeichen-Konvention wie GEX (long Call, short Put). Nur ein Modell-Schaetzer! ----
def _d1d2(S, K, T, sigma, r=0.0):
    with np.errstate(divide="ignore", invalid="ignore"):
        srt = sigma * np.sqrt(T)
        d1 = (np.log(S / K) + (r + 0.5 * sigma ** 2) * T) / srt
        d2 = d1 - srt
    return d1, d2, srt


def bs_vanna(S, K, T, sigma, r=0.0):
    """dDelta/dVol (= dVega/dSpot). Positiv OTM-Call/ITM-Put-seitig. Pro 1.0 Vol (dezimal)."""
    S = np.asarray(S, float); K = np.asarray(K, float)
    T = np.asarray(T, float); sigma = np.asarray(sigma, float)
    d1, d2, _ = _d1d2(S, K, T, sigma, r)
    with np.errstate(divide="ignore", invalid="ignore"):
        v = -_npdf(d1) * d2 / sigma
    return np.where(np.isfinite(v), v, 0.0)


def bs_charm(S, K, T, sigma, r=0.0):
    """dDelta/dt (Zeit vergeht, T sinkt), pro JAHR. r=0 -> phi(d1)*d2/(2T)."""
    S = np.asarray(S, float); K = np.asarray(K, float)
    T = np.asarray(T, float); sigma = np.asarray(sigma, float)
    d1, d2, srt = _d1d2(S, K, T, sigma, r)
    with np.errstate(divide="ignore", invalid="ignore"):
        c = -_npdf(d1) * (2.0 * r * T - d2 * srt) / (2.0 * T * srt)
    return np.where(np.isfinite(c), c, 0.0)


def _signed_vanna_at(chain, S, r=0.0):
    """Dealer-Vanna-Exposure je Option: $-Delta-Verschiebung pro 1 Vol-PUNKT (0.01)."""
    v = bs_vanna(S, chain["strike"].values, chain["T"].values, chain["iv"].values, r)
    sign = np.where(chain["type"].values == "C", 1.0, -1.0)
    return sign * v * chain["oi"].values * chain["mult"].values * S * 0.01


def _signed_charm_at(chain, S, r=0.0):
    """Dealer-Charm-Exposure je Option: $-Delta-Verschiebung pro HANDELSTAG (Jahr/252)."""
    c = bs_charm(S, chain["strike"].values, chain["T"].values, chain["iv"].values, r)
    sign = np.where(chain["type"].values == "C", 1.0, -1.0)
    return sign * c * chain["oi"].values * chain["mult"].values * S / 252.0


def total_vanna(chain, S, r=0.0):
    return float(_signed_vanna_at(chain, S, r).sum())


def total_charm(chain, S, r=0.0):
    return float(_signed_charm_at(chain, S, r).sum())


def _dominant_strike(chain, vals):
    """Strike mit der groessten |aggregierten| Exposure (die 'Wall')."""
    agg = {}
    for k, v in zip(chain["strike"].values, vals):
        agg[k] = agg.get(k, 0.0) + v
    if not agg:
        return None
    return float(max(agg, key=lambda k: abs(agg[k])))


def total_gex(chain, S, r=0.0):
    return float(_signed_gex_at(chain, S, r).sum())


def gamma_flip(chain, spot, r=0.0, lo=0.80, hi=1.20, n=900):
    """Spot, an dem Gesamt-GEX = 0 (naechste Nullstelle zum aktuellen Spot)."""
    grid = np.linspace(spot * lo, spot * hi, n)
    vals = np.array([total_gex(chain, s, r) for s in grid])
    sign = np.sign(vals)
    cross = np.where(np.diff(sign) != 0)[0]
    if len(cross) == 0:
        return None
    # Nullstelle naechst am Spot, linear interpoliert
    best = None
    for i in cross:
        x0, x1 = grid[i], grid[i + 1]; y0, y1 = vals[i], vals[i + 1]
        z = x0 - y0 * (x1 - x0) / (y1 - y0)
        if best is None or abs(z - spot) < abs(best - spot):
            best = z
    return float(best)


def per_strike_gex(chain, spot, r=0.0):
    gex = _signed_gex_at(chain, spot, r)
    out = {}
    for k, v in zip(chain["strike"].values, gex):
        out[k] = out.get(k, 0.0) + v
    return out  # {strike: net_gex}


def max_pain(chain):
    """Strike, der die Gesamt-Auszahlung an Optionskaeufer minimiert (klassisch)."""
    strikes = np.unique(chain["strike"].values)
    K = chain["strike"].values; oi = chain["oi"].values
    isC = chain["type"].values == "C"; mult = chain["mult"].values
    best_E, best_pain = None, None
    for E in strikes:
        callpay = np.maximum(E - K[isC], 0) * oi[isC] * mult[isC]
        putpay = np.maximum(K[~isC] - E, 0) * oi[~isC] * mult[~isC]
        pain = callpay.sum() + putpay.sum()
        if best_pain is None or pain < best_pain:
            best_pain, best_E = pain, E
    return float(best_E)


def compute_levels(chain, spot, r=0.0, neutral_pct=0.3):
    chain = chain.copy()
    chain = chain[(chain["oi"] > 0) & (chain["iv"] > 0) & (chain["T"] > 0)]
    if len(chain) < 4:
        return None
    psg = per_strike_gex(chain, spot, r)
    strikes = np.array(sorted(psg))
    netg = np.array([psg[k] for k in strikes])
    # Call-Wall = groesster positiver GEX-Strike; Put-Wall = negativster.
    # Zweite Walls = naechstgroesste Cluster (das "Strike-Regal" dahinter).
    cw = cw2 = pw = pw2 = None
    pos = np.argsort(netg)
    if (netg > 0).any():
        cw = float(strikes[pos[-1]])
        rest = [strikes[j] for j in pos[::-1][1:]
                if netg[j] > 0 and abs(strikes[j] - cw) > 1e-9]
        cw2 = float(rest[0]) if rest else None
    if (netg < 0).any():
        pw = float(strikes[pos[0]])
        rest = [strikes[j] for j in pos[1:]
                if netg[j] < 0 and abs(strikes[j] - pw) > 1e-9]
        pw2 = float(rest[0]) if rest else None
    tg = total_gex(chain, spot, r)
    flip = gamma_flip(chain, spot, r)
    # Regime mit Flip-ZONE: nahe am Flip ist kein Signal, sondern Niemandsland
    if flip is None:
        regime = "long" if tg > 0 else "short"
    else:
        d = (spot - flip) / spot * 100
        regime = "neutral" if abs(d) < neutral_pct else ("long" if d > 0 else "short")
    # Expected Move (1 Tag) aus ATM-IV: spot * iv * sqrt(1/252)
    atm = chain.loc[(chain["strike"] - spot).abs().sort_values().index[:6], "iv"]
    atm_iv = float(atm.median()) if len(atm) else None
    em_1d = (spot * atm_iv / np.sqrt(252.0)) if atm_iv else None
    # Charm & Vanna (Netto-Dealer-Flow-Richtung + dominanter Strike)
    tv = total_vanna(chain, spot, r)
    tc = total_charm(chain, spot, r)
    vanna_strike = _dominant_strike(chain, _signed_vanna_at(chain, spot, r))
    charm_strike = _dominant_strike(chain, _signed_charm_at(chain, spot, r))
    return {
        "spot": float(spot),
        "total_gex": tg,
        "regime": regime,
        "gamma_flip": flip,
        "call_wall": cw, "call_wall2": cw2,
        "put_wall": pw, "put_wall2": pw2,
        "max_pain": max_pain(chain),
        "atm_iv": (round(atm_iv, 4) if atm_iv else None),
        "exp_move_1d": (round(em_1d, 2) if em_1d else None),
        "dist_to_flip_pct": (round((spot - flip) / spot * 100, 2) if flip else None),
        # Vanna>0: Vol-DOWN -> Dealer KAUFEN (Vanna-Rally-Treibstoff im Grind);
        #          Vol-UP -> Dealer verkaufen (Abwaerts-Beschleuniger).
        "total_vanna": tv,
        "vanna_flow": ("Vol-down=Kauf" if tv > 0 else "Vol-down=Verkauf"),
        "vanna_strike": vanna_strike,
        # Charm>0: mit vergehender Zeit -> Dealer KAUFEN (Stuetze in den Verfall/OPEX).
        "total_charm": tc,
        "charm_flow": ("Zeit=Kauf-Stuetze" if tc > 0 else "Zeit=Verkauf-Druck"),
        "charm_strike": charm_strike,
    }
