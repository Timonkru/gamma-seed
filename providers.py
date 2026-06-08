"""
Provider-Schicht: jede Quelle liefert eine STANDARDISIERTE Optionskette + Spot.
So bleibt der Rest (GEX, Seed-Writer, Pine) gleich — eine neue Quelle = ein neues Modul.

Jetzt aktiv:  synthetic (zum Testen der ganzen Pipeline ohne Datenkauf)
Zu bauen:     eurex_dax, ice_ftse   (GRATIS, eigene Berechnung)
Spaeter:      paid_us (ThetaData/ORATS/Polygon)  -> dropt als EIN Modul ein
"""
from dataclasses import dataclass
import numpy as np
import pandas as pd


@dataclass
class Chain:
    df: pd.DataFrame      # strike,type,oi,iv,T,mult
    spot: float
    label: str
    currency: str = "EUR"


# ---------- TEST-PROVIDER (deterministisch, DAX-/FTSE-aehnlich) ----------
def synthetic(label="DAX", spot=18500.0, mult=5.0, currency="EUR",
              cwall=19000.0, pwall=18000.0, dte=4, seed=7):
    rng = np.random.default_rng(seed)
    strikes = np.arange(round(spot * 0.88, -2), round(spot * 1.12, -2) + 1, 100.0)
    T = dte / 252.0
    rows = []
    for K in strikes:
        moneyness = abs(K - spot) / spot
        iv = 0.13 + 0.6 * moneyness                      # einfacher Smile
        # OI-Cluster: ATM + grosse Call-Wall + grosse Put-Wall
        base = 2000 * np.exp(-((K - spot) / (spot * 0.04)) ** 2)
        callbump = 9000 * np.exp(-((K - cwall) / 150.0) ** 2)
        putbump = 9000 * np.exp(-((K - pwall) / 150.0) ** 2)
        oi_c = base + callbump + rng.integers(0, 400)
        oi_p = base + putbump + rng.integers(0, 400)
        rows.append((K, "C", float(oi_c), float(iv), T, mult))
        rows.append((K, "P", float(oi_p), float(iv), T, mult))
    df = pd.DataFrame(rows, columns=["strike", "type", "oi", "iv", "T", "mult"])
    return Chain(df=df, spot=spot, label=label, currency=currency)


# ---------- US-ETFs (yfinance) — GRATIS, echtes OI + IV ----------
def yf_us(symbol="QQQ", currency="USD", max_days=60, min_days=0, mult=100.0):
    """
    Gratis echte Optionskette via yfinance (US-ETFs): QQQ(NQ) / DIA(Dow) / GLD(Gold) / SPY.
    Aggregiert alle Verfaelle bis max_days Tagen (Front-Gamma dominiert). OI + IV je Strike real.
    """
    import yfinance as yf
    from datetime import datetime, timezone
    import pandas as pd
    tk = yf.Ticker(symbol)
    spot = float(tk.history(period="1d")["Close"].iloc[-1])
    today = datetime.now(timezone.utc).date()
    rows = []
    for exp in tk.options:
        ed = datetime.strptime(exp, "%Y-%m-%d").date()
        dte = (ed - today).days
        if dte < min_days or dte > max_days:
            continue
        T = max(dte, 0.5) / 365.0
        oc = tk.option_chain(exp)
        for d, typ in [(oc.calls, "C"), (oc.puts, "P")]:
            s = d[["strike", "openInterest", "impliedVolatility"]].copy()
            s = s.dropna()
            s = s[(s["openInterest"] > 0) & (s["impliedVolatility"] > 0)]
            for _, r in s.iterrows():
                rows.append((float(r["strike"]), typ, float(r["openInterest"]),
                             float(r["impliedVolatility"]), T, mult))
    if not rows:
        raise RuntimeError(f"yf_us({symbol}): keine Optionsdaten erhalten (Netz/Markt zu?).")
    df = pd.DataFrame(rows, columns=["strike", "type", "oi", "iv", "T", "mult"])
    return Chain(df=df, spot=spot, label=symbol, currency=currency)


# ---------- DAX (Eurex) — bezahlt/spaeter (Databento/MD+S), GRATIS-OI existiert nicht ----------
def eurex_dax(date=None):
    """
    PLAN (noch zu verdrahten, sobald wir das echte Eurex-File haben):
      1) Eurex publiziert taegliche OI/Settlement je Serie (Produkt ODAX = DAX-Optionen).
         Quelle: eurex.com -> Market Data -> Statistics / 'Open Interest' Tagesfiles (CSV),
         oder T7 EOB-Files. -> Spalten: Strike, Call/Put, Settlement-Preis, OI, Expiry.
      2) IV je Strike: aus dem Settlement-Preis per Black-Scholes invertieren (oder ATM-IV
         aus der Naehe nehmen und als Flat anwenden -> erste Naeherung).
      3) Spot = DAX-Cash bei Berechnung; T = (Expiry - heute)/252.
      4) Nur den naechsten relevanten Verfall nehmen (3. Freitag) oder mehrere aggregieren.
      5) Auf Chain-Schema mappen: strike,type,oi,iv,T,mult(=5) -> Chain zurueckgeben.
    Bis dahin: Platzhalter.
    """
    raise NotImplementedError(
        "eurex_dax: Eurex-ODAX-OI-File einlesen (Strike/Call-Put/OI/Settlement/Expiry) "
        "-> IV invertieren -> Chain(mult=5, currency='EUR'). Siehe Docstring."
    )


# ---------- FTSE (ICE) — GRATIS, selbst rechnen ----------
def ice_ftse(date=None):
    """
    PLAN: ICE Futures Europe publiziert OI/Settlement fuer FTSE-100-Optionen (Produkt 'Z').
      Quelle: ice.com -> Report Center / 'Open Interest' & 'Settlement Prices' Tagesfiles.
      Rest identisch zu eurex_dax. mult=10, currency='GBP'.
    """
    raise NotImplementedError(
        "ice_ftse: ICE-FTSE-Optionen OI/Settlement einlesen -> Chain(mult=10, currency='GBP')."
    )


# ---------- US (bezahlte Quelle) — SPAETER, ein Modul ----------
def paid_us(symbol="QQQ", date=None, api_key=None):
    """
    SPAETER: ThetaData / ORATS / Polygon liefern Kette inkl. Greeks/IV direkt.
      -> nur hier den API-Call + Mapping auf das Chain-Schema einbauen, sonst NICHTS aendern.
      QQQ/NDX (NQ), SPY/SPX, DIA (Dow), GLD (Gold).  mult=100, currency='USD'.
    """
    raise NotImplementedError("paid_us: kostenpflichtige Optionskette -> Chain(mult=100, currency='USD').")
