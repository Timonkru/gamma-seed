# Gamma-Seed — Gamma-Level für TradingView (Pine Seed) & MT5

Tägliche Berechnung von **Gamma-Flip / Call-Wall / Put-Wall / Max-Pain / Netto-GEX** aus Options-Open-Interest,
publiziert in ein öffentliches GitHub-Repo im **TradingView-Pine-Seed-Format** → in Pine via `request.seed()` lesbar.

**Designprinzip:** provider-agnostisch. DAX/FTSE rechnen wir selbst (gratis, Eurex/ICE), US-Märkte kommen
später über eine bezahlte Quelle (ThetaData/ORATS) — das ist *ein* zusätzliches Provider-Modul, sonst ändert sich nichts.

## Dateien
- `gex.py` — Black-Scholes-Gamma → GEX → Flip/Walls/Max-Pain (provider-agnostisch).
- `providers.py` — Quellen: `synthetic` (Test), `eurex_dax`/`ice_ftse` (gratis, zu verdrahten), `paid_us` (später).
- `build_seed.py` — rechnet je Index die Level, schreibt `data/*.csv` + `symbol_info/krueger_gamma.json`.
- `GammaLevels_seed.pine` — Pine-Indikator, der die Seed-Daten liest und zeichnet.

## Täglicher Lauf
```bash
python build_seed.py          # hängt heutige Zeile je Ticker an, schreibt symbol_info
git add -A && git commit -m "gamma EOD update" && git push
```
(Später per Scheduled Task / cron nach Börsenschluss automatisieren.)

## TradingView-Pine-Seed-Freischaltung (einmalig)
1. Repo **öffentlich** auf GitHub (z. B. `gamma-seed`) mit Ordnern `data/` und `symbol_info/`.
2. Struktur:
   - `symbol_info/<prefix>.json` — beschreibt alle Ticker (siehe generiertes `krueger_gamma.json`).
   - `data/<TICKER>.csv` — Zeilen `YYYYMMDDT,O,H,L,C,Vol` (hier O=H=L=C=Level), täglich.
3. **Aktivierung beantragen** (TradingView prüft/whitelistet das Repo) — aktueller Weg laut TradingView-Doku
   „Pine Seed": Repo nach Spezifikation anlegen und über das TradingView-Formular/den angegebenen Kontakt einreichen.
4. Nach Freischaltung ist die Quelle als **`seed_<githubuser>_<reponame>`** ansprechbar — hier:
   ```pine
   request.seed("seed_Timonkru_gamma-seed", "GOLD_FLIP", close)
   ```
   → im Indikator `GammaLevels_seed.pine` ist `src` bereits auf `seed_Timonkru_gamma-seed` gesetzt.
   Repo: https://github.com/Timonkru/gamma-seed (public, Branch `main`).

> Hinweis: Seed-Daten sind **EOD/daily** und werden bei jedem Push aktualisiert — genau richtig, weil OI
> ohnehin erst nach Börsenschluss publiziert wird.

## DAX/FTSE echt verdrahten (nächster Schritt, gratis)
In `providers.py` die `eurex_dax`/`ice_ftse`-Platzhalter füllen:
1. Tages-OI/Settlement-File ziehen (Eurex ODAX / ICE FTSE-Optionen).
2. Spalten mappen: Strike, Call/Put, OI, Settlement → **IV invertieren** (oder ATM-IV als Näherung).
3. Spot (Cash) + `T=(Expiry-heute)/252`, `mult` (DAX 5 / FTSE 10).
4. `Chain(df, spot, label, currency)` zurückgeben — Rest läuft unverändert.

## US später (bezahlt, ein Modul)
`paid_us(symbol)` mit ThetaData/ORATS/Polygon füllen (QQQ/NDX, SPY/SPX, DIA, GLD; `mult=100`, USD),
dann in `build_seed.CONFIG` die Zeilen `("NDX",...)`, `("GOLD",...)` aktivieren. Sonst nichts ändern.

## MT5-Nutzung (parallel)
`data/*.csv` bzw. eine schlanke `gamma_levels.csv` kann der MT5-EA direkt lesen → Gamma-Level in die
Ausführung (Upwork-Gold-EA), ohne Umweg über TradingView.

> **Vorzeichen-Annahme:** Call-Gamma +, Put-Gamma − (Dealer long Call / short Put). Das ist die übliche,
> aber eine *Modell*-Annahme — verschiedene Anbieter rechnen anders. Bewusst bleiben.
