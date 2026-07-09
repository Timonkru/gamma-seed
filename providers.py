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
def yf_us(symbol="QQQ", currency="USD", max_days=45, min_days=0, mult=100.0):
    """
    Gratis echte Optionskette via yfinance (US-ETFs): QQQ(NQ) / DIA(Dow) / GLD(Gold) / SPY.
    Liefert ALLE Verfaelle bis max_days inkl. 'dte'-Spalte — der Aufrufer trennt
    Struktur-Karte (dte>=7) und Nah-Karte (dte<=5). T in Handelstagen/252,
    konsistent zur QC-Historie (KasseRL).
    """
    import yfinance as yf
    import numpy as np
    from datetime import datetime, timezone
    import pandas as pd
    tk = yf.Ticker(symbol)
    # Letzte NICHT-NaN Schlusszeile (yfinance haengt intraday eine NaN-Kerze an)
    _h = tk.history(period="5d")["Close"].dropna()
    if len(_h) == 0:
        raise RuntimeError(f"yf_us({symbol}): kein gueltiger Spot-Close (Netz/Markt zu?).")
    spot = float(_h.iloc[-1])
    today = datetime.now(timezone.utc).date()
    rows = []
    for exp in tk.options:
        ed = datetime.strptime(exp, "%Y-%m-%d").date()
        dte = (ed - today).days
        if dte < min_days or dte > max_days:
            continue
        T = max(np.busday_count(today, ed), 0.5) / 252.0
        oc = tk.option_chain(exp)
        for d, typ in [(oc.calls, "C"), (oc.puts, "P")]:
            s = d[["strike", "openInterest", "impliedVolatility", "volume"]].copy()
            s["volume"] = s["volume"].fillna(0.0)
            s = s.dropna(subset=["strike", "openInterest", "impliedVolatility"])
            # Volumen > 0 reicht: intraday geoeffnete 0DTE-Positionen haben OI=0!
            s = s[((s["openInterest"] > 0) | (s["volume"] > 0))
                  & (s["impliedVolatility"] > 0)]
            for _, r in s.iterrows():
                rows.append((float(r["strike"]), typ, float(r["openInterest"]),
                             float(r["impliedVolatility"]), T, mult, dte,
                             float(r["volume"])))
    if not rows:
        raise RuntimeError(f"yf_us({symbol}): keine Optionsdaten erhalten (Netz/Markt zu?).")
    df = pd.DataFrame(rows, columns=["strike", "type", "oi", "iv", "T", "mult",
                                     "dte", "vol"])
    return Chain(df=df, spot=spot, label=symbol, currency=currency)


# ---------- Index-Spot (zur Umrechnung ETF-Level -> Index-Punkte) ----------
def index_spot(symbol):
    """Letzter Schluss des echten Index/Underlyings (^NDX, ^DJI, GC=F ...) via yfinance.
    yfinance liefert fuer Index-Symbole (^NDX/^DJI) oft eine abschliessende NaN-Kerze
    (die laufende, noch nicht abgeschlossene Zeile) -> erst die NaN-Schlusskurse
    verwerfen, dann den letzten guten Close nehmen, sonst wird R = NaN."""
    import yfinance as yf
    h = yf.Ticker(symbol).history(period="5d")
    close = h["Close"].dropna() if len(h) else h.get("Close", [])
    if len(close) == 0:
        raise RuntimeError(f"index_spot({symbol}): kein gueltiger Close (leer/alles NaN)")
    return float(close.iloc[-1])


# ---------- DAX (Eurex ODAX) — GRATIS aus Eurex-Tagesfile, IV selbst invertieren ----------
from pathlib import Path as _Path

# Spalten-Mapping: erst Fuzzy-Suche, dann diese Overrides (sobald das echte File-Format
# bekannt ist, hier die exakten Eurex-Spaltennamen eintragen -> dann ist es gelockt).
EUREX_COLMAP = {
    "strike": None,      # z.B. "StrikePrice" / "Basispreis"
    "cp": None,          # Call/Put-Indikator, z.B. "PutOrCall" / "C/P"
    "oi": None,          # Open Interest
    "price": None,       # Daily Settlement Price
    "expiry": None,      # Verfalldatum / Maturity
}


def _find_col(raw_cols, keys, override=None):
    if override and override in raw_cols:
        return override
    low = {c.lower().strip(): c for c in raw_cols}
    for k in keys:
        for lc, orig in low.items():
            if k in lc:
                return orig
    return None


def _norm_cp(v):
    s = str(v).strip().upper()
    if s.startswith("C") or s in ("1", "CALL"):
        return "C"
    if s.startswith("P") or s in ("0", "-1", "PUT"):
        return "P"
    return None


def _eurex_api(url):
    import json
    import urllib.request
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    return json.load(urllib.request.urlopen(req, timeout=30))


def eurex_dax(path=None, spot=None, mult=5.0, currency="EUR",
              max_days=45, min_days=0, product_id=70044):
    """
    DAX-Optionen (ODAX) — GRATIS direkt von der oeffentlichen Eurex-Statistik-API
    (dieselben EOD-Daten wie der 'Statistics'-Tab der Produktseite, entdeckt 2026-07-06):
      Uebersicht: eurex.com/api/v1/overallstatistics/70044
                  -> Verfaelle (W/M) + DAX-Schlusskurs + juengster Handelstag
      Detail:     ...?filtertype=detail&productdate=YYYYMMDD&busdate=YYYYMMDD&contracttype=X
                  -> je Strike: OI, Volumen, Daily-Settlement-Preis (Call+Put)
    IV je Strike aus dem Settlement invertiert (gex.implied_vol; T der Inversion ab
    busdate, T der Gamma-Berechnung ab HEUTE). KEIN ETF-Scaling (Strikes = Indexpunkte,
    mult=5). Kein Account/Token noetig. path=<csv> erzwingt den alten Datei-Modus;
    bei Web-Fehler wird automatisch auf ein vorhandenes File zurueckgefallen.
    """
    if path is not None:
        return _eurex_dax_file(path, spot, mult, currency, max_days, min_days)
    try:
        return _eurex_dax_web(spot, mult, currency, max_days, min_days, product_id)
    except Exception as e:
        d = _Path(__file__).resolve().parent / "data" / "eurex"
        files = sorted(d.glob("*.csv")) if d.exists() else []
        if files:
            print(f"[warn] eurex_dax: Web-API fehlgeschlagen ({e}) -> Datei-Fallback {files[-1].name}")
            return _eurex_dax_file(files[-1], spot, mult, currency, max_days, min_days)
        raise


def _eurex_dax_web(spot, mult, currency, max_days, min_days, product_id):
    import time
    import gex
    from datetime import datetime, timezone

    base = f"https://www.eurex.com/api/v1/overallstatistics/{product_id}"
    ov = _eurex_api(base)
    hdr = ov["header"]
    if spot is None:
        spot = float(hdr["underlyingClosingPrice"])
    # juengster Handelstag: "03-07-2026 12:00" -> 20260703
    d_, m_, y_ = hdr["tradingDates"][0].split(" ")[0].split("-")
    busdate = f"{y_}{m_}{d_}"
    bus_d = pd.Timestamp(f"{y_}-{m_}-{d_}").date()
    today = datetime.now(timezone.utc).date()

    rows = []
    for rm in ov["dataRows"]:
        exp_s = str(rm["date"])
        ctype = str(rm.get("contractType", "M"))
        if ctype == "F":                                   # Flex ueberspringen
            continue
        if float(rm.get("callOpenInterest", 0)) + float(rm.get("putOpenInterest", 0)) <= 0:
            continue
        exp = pd.Timestamp(exp_s).date()
        dte = (exp - today).days
        if dte < min_days or dte > max_days:
            continue
        T_gamma = max(np.busday_count(today, exp), 0.5) / 252.0    # fuer Gamma (ab heute)
        T_inv = max(np.busday_count(bus_d, exp), 0.5) / 252.0      # fuer IV (ab Datenstand)
        det = _eurex_api(f"{base}?filtertype=detail&productdate={exp_s}"
                         f"&busdate={busdate}&contracttype={ctype}")
        for key, typ in (("dataRowsCall", "C"), ("dataRowsPut", "P")):
            for r in det.get(key, []):
                K = float(r.get("strike", 0) or 0)
                oi = float(r.get("openInterest", 0) or 0)
                vol = float(r.get("volume", 0) or 0)
                px = float(r.get("dSettle", 0) or 0)
                if K <= 0 or (oi <= 0 and vol <= 0) or px <= 0:
                    continue
                iv = gex.implied_vol(px, spot, K, T_inv, typ)
                rows.append((K, typ, oi, iv, T_gamma, mult, dte, vol))
        time.sleep(0.25)                                   # API nicht hammern

    if not rows:
        raise RuntimeError("eurex_dax_web: keine Optionsreihen erhalten (API-Format geaendert?)")
    df = pd.DataFrame(rows, columns=["strike", "type", "oi", "iv", "T", "mult", "dte", "vol"])
    near = df.loc[(df["strike"] - spot).abs().sort_values().index[:12], "iv"].dropna()
    atm_iv = float(near.median()) if len(near) else 0.18
    df["iv"] = df["iv"].fillna(atm_iv)
    print(f"[eurex] ODAX via Web-API: {len(df)} Reihen, {df['dte'].nunique()} Verfaelle, "
          f"Spot {spot:.0f} (Stand {busdate})")
    return Chain(df=df, spot=float(spot), label="DAX(ODAX)", currency=currency)


def _eurex_dax_file(path, spot=None, mult=5.0, currency="EUR",
                    max_days=45, min_days=0, third_friday_only=False):
    """Datei-Modus (Fallback): Eurex-ODAX-Tagesfile (Strike, Call/Put, Settlement, OI,
    Expiry) einlesen. IV aus Settlement invertiert wie im Web-Modus."""
    import gex
    from datetime import datetime, timezone
    raw = pd.read_csv(path, sep=None, engine="python")
    cols = list(raw.columns)
    c_strike = _find_col(cols, ["strike", "exercise", "basispreis"], EUREX_COLMAP["strike"])
    c_cp = _find_col(cols, ["putorcall", "call/put", "c/p", "p/c", "optiontype", "callput", "type"], EUREX_COLMAP["cp"])
    c_oi = _find_col(cols, ["open interest", "openinterest", "open_interest", "oi"], EUREX_COLMAP["oi"])
    c_px = _find_col(cols, ["settlement", "settle", "dailysettle", "settlpric", "price"], EUREX_COLMAP["price"])
    c_exp = _find_col(cols, ["expiry", "expiration", "maturity", "verfall", "matdate", "contractdate"], EUREX_COLMAP["expiry"])
    missing = [n for n, c in [("strike", c_strike), ("cp", c_cp), ("oi", c_oi),
                              ("price", c_px), ("expiry", c_exp)] if c is None]
    if missing:
        raise RuntimeError(
            f"eurex_dax: Spalten {missing} nicht erkannt. Datei-Spalten = {cols}. "
            "Trag die echten Namen in EUREX_COLMAP ein (oben in providers.py).")

    if spot is None:
        spot = index_spot("^GDAXI")
    today = datetime.now(timezone.utc).date()

    rows = []
    for _, r in raw.iterrows():
        cp = _norm_cp(r[c_cp])
        if cp is None:
            continue
        try:
            K = float(r[c_strike]); oi = float(r[c_oi]); px = float(r[c_px])
        except (TypeError, ValueError):
            continue
        if oi <= 0 or K <= 0:
            continue
        ed = pd.to_datetime(r[c_exp], errors="coerce", dayfirst=False)
        if pd.isna(ed):
            continue
        ed = ed.date()
        dte = (ed - today).days
        if dte < min_days or dte > max_days:
            continue
        if third_friday_only and not (15 <= ed.day <= 21 and ed.weekday() == 4):
            continue
        T = max(np.busday_count(today, ed), 0.5) / 252.0
        rows.append((K, cp, oi, px, T, mult, dte))

    if not rows:
        raise RuntimeError(f"eurex_dax: keine gueltigen Zeilen aus {path} (Filter/Format?).")
    df = pd.DataFrame(rows, columns=["strike", "type", "oi", "price", "T", "mult", "dte"])

    # IV je Strike aus Settlement invertieren; Fallback = flache ATM-IV
    df["iv"] = [gex.implied_vol(p, spot, k, t, ty)
                for p, k, t, ty in zip(df["price"], df["strike"], df["T"], df["type"])]
    near = df.loc[(df["strike"] - spot).abs().sort_values().index[:8], "iv"].dropna()
    atm_iv = float(near.median()) if len(near) else 0.18
    df["iv"] = df["iv"].fillna(atm_iv)
    df["vol"] = 0.0
    df = df.drop(columns=["price"])
    return Chain(df=df, spot=float(spot), label="DAX(ODAX)", currency=currency)


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
