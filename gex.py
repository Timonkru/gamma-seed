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


def _signed_gex_at(chain, S, r=0.0):
    """GEX je Option bei hypothetischem Spot S ($ pro 1%-Move). Call +, Put -."""
    g = bs_gamma(S, chain["strike"].values, chain["T"].values, chain["iv"].values, r)
    sign = np.where(chain["type"].values == "C", 1.0, -1.0)
    return sign * g * chain["oi"].values * chain["mult"].values * (S ** 2) * 0.01


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
    }
