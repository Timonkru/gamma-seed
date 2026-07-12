# Gamma-Seed v3 — Tägliche Gamma-Level für TradingView (DAX / NQ / DOW / GOLD)

Berechnet täglich **Gamma-Flip, Call/Put-Walls, Strike-Regal, Max Pain, Expected
Move** aus echten Options-Daten und generiert den TradingView-Indikator
`GammaLevels_auto.pine` mit eingebrannten Tages-Leveln.

Datenquellen:
- **US** (NQ/DOW/GOLD): yfinance-ETF-Proxies QQQ→NQ, DIA→DOW, GLD→GOLD
- **DAX**: echte **ODAX-Indexoptionen** direkt von der öffentlichen
  Eurex-Statistik-API (Settlement + Open Interest je Strike, gratis, kein
  Account) — IV wird je Strike aus dem Settlement-Preis invertiert.
  Kein ETF-Umweg, Strikes = Indexpunkte. (FTSE: geparkt — ICE schützt seine
  Daten hinter Cloudflare; DAX-Karte dient als EU-Regime-Proxy.)

## Neu in v3 (2026-07-12)

- **Vanna- & Charm-Strike-Linien** (violett/aqua, gepunktet) + **FLOW-Zeile im
  Label**: Gesamt-Vanna/-Charm in $Mio mit Lesart (Vol-runter=Kauf bzw.
  Zeit=Kauf-Stütze/Verkauf-Druck) und dominantem Strike. Gleiche
  Dealer-Vorzeichen-Konvention wie GEX. **Unvalidiert — reiner Modellschätzer,
  Kontext-Schicht, kein Trade-Signal.**
- **VIX-Regime im Label** (`CBOE:VIX`, gestriger Daily-Close = kein Repaint):
  Tertile über 250 Handelstage + Richtung → Tilt-Text
  (hoch/steigend = Entscheidungstag, niedrig/fallend = Chop). Kontext, kein Signal.
- **Template komplett ASCII**: `clip <` in den .bat-Ritualen kopiert ANSI —
  Nicht-ASCII-Zeichen (—, ±) kamen als Zeichensalat in TradingView an. Das
  Template darf nie wieder Nicht-ASCII enthalten.

## Das Drei-Schichten-Modell (Kern von v2, 2026-06-11)

Das alte v1 mischte alle Laufzeiten (0–60 Tage) in eine Karte. Folge: Das
explodierende Gamma der **heute auslaufenden** Optionen („0DTE-Schreihals")
dominierte alles — die Walls klebten am Spot, das Regime-Label war Rauschen,
und die Karte zerfiel im Tagesverlauf von selbst. v2 trennt drei Schichten:

| Schicht | Laufzeiten | Daten | Im Chart | Halbwertszeit |
|---|---|---|---|---|
| **STRUKTUR** | 7–45 DTE | Über-Nacht-OI | dicke Linien (Flip gelb, CW rot, PW grün) + Regal (gestrichelt) | Tage |
| **NAH** | 0–5 DTE | Über-Nacht-OI | gepunktet (orange/türkis, 0DTE-Flip optional) | bis ~Mittag der US-Session |
| **0DTE-VOLUMEN** | 0–1 DTE | **heutiges** per-Strike-Volumen | ersetzt nachmittags die gepunkteten Walls | Rest des Tages |

Die Struktur-Karte ist methodisch identisch zur KasseRL-QC-Historie
(7–45 DTE, T = Handelstage/252) → Live-Level und künftige Agent-Features
sprechen dieselbe Sprache.

## Tägliche Rituale

```bash
# EINFACHSTER WEG: Doppelklick auf die nummerierten .bat-Dateien im Ordner.
# Jede .bat laesst den Lauf laufen und legt den Pine-Code automatisch in die
# ZWISCHENABLAGE -> im TradingView-Pine-Editor nur noch Strg+A, Strg+V, Save.

# 1) 1_gamma_morgen_eu.bat      ~08:30 Berlin (VOR DAX-Open 09:00)
python build_seed.py --eu
#    -> NUR DAX frisch (Eurex-EOD von gestern, ueber Nacht publiziert).
#       US-Linien bleiben Vortags-Stand. Check: "[eurex] ... Stand YYYYMMDD"
#       muss den VORTAG zeigen. Pine einfuegen, EU-Karte einfrieren.

# 2) 2_gamma_mittag_voll.bat    ~14:00 Berlin (nach US-OI-Update ~12:30, VOR US-Open)
python build_seed.py
#    -> rechnet ALLES neu (US frisch; DAX identisch zum Morgenlauf, weil die
#       Eurex-Quelle nur 1x/Tag updated -> KEIN Repaint moeglich).
#    -> Pine einfuegen. Level fuer den Tag EINGEFROREN.

# 3) 3_gamma_0dte_update.bat    optional ~16:45 Berlin (nach der 1. US-Stunde)
python build_seed.py --intraday
#    -> NUR die gepunkteten 0DTE-Walls aus dem HEUTIGEN US-Volumen.
#       Struktur + DAX unangetastet. Label zeigt "+0DTE-Vol-Update".

# Layout-Aenderung ohne Neuberechnung (eingefrorene Level behalten):
python regen_pine.py
```

**Eiserne Regeln:**
- **Nie nach 15:30 Berlin voll neu rechnen.** Ab US-Open werden Spot/IV live —
  eine Neuberechnung gewichtet das gestrige OI dem Preis hinterher
  („preispoliert"/Repainting) und ist als Referenz wertlos. Zwischen ~12:30
  und 15:29 liefert der Build übrigens identische Zahlen (Inputs ändern sich
  in dem Fenster nicht) — 14:00 gibt nur Puffer + frische Karte fürs
  Gold-14:15-Setup.
- Die Pine-Konstanten ändern sich **nie von selbst** — jede Level-Änderung am
  Chart kommt von einem neuen Einfügen. Live ist nur die Einfärbung
  (Regime-Hintergrund, Label) — sie vergleicht den Kurs mit den festen Linien.

## Lese-Spickzettel

- **Spot unter Struktur-Flip = Short-Gamma:** Dealer verstärken Bewegungen →
  Trend-/Expansionstage, große Kerzen, Gap-Risiko. Breaks laufen lassen,
  Addons; jede Rally ist verdächtig, bis der Flip zurückerobert ist.
- **Spot über Struktur-Flip = Long-Gamma:** Dealer dämpfen → Pinning Richtung
  Call-Wall, Mean-Reversion. Ziele statt Trails, Teilgewinne an den Walls.
- **Flip-Zone (±0,3%, grauer Hintergrund):** Niemandsland, kein Signal.
- **Walls:** Long-Gamma = Magnete/Zäune; Short-Gamma = Falltüren, wenn sie
  brechen (dann zählt das **Regal**: CW2/PW2 = nächste Ziel-Zone).
- **Umkehr-Signatur** nach Kaskade: IV-Spitze + **Put-Wall-Reclaim** von unten
  (Alert vorhanden) = Dealer-Rückkäufe laufen an.
- **Expected Move (blau):** vom Optionsmarkt eingepreiste 1-Tages-Spanne;
  Kaskaden-Tage laufen oft das 1,5–2-Fache.
- Alle Linien sind in den Indikator-Einstellungen einzeln schaltbar, jeder
  Schalter benennt Farbe + Stil. Veraltet-Warnung im Label, wenn der Build
  vergessen wurde. 5 Alerts im Alert-Dialog.

## Dateien

- `1_gamma_morgen_eu.bat` / `2_gamma_mittag_voll.bat` / `3_gamma_0dte_update.bat`
  — Doppelklick-Rituale; legen den Pine-Code automatisch in die Zwischenablage
- `build_seed.py` — Orchestrator: EU-Morgenlauf (`--eu`, nur DAX), voller Lauf
  (`main`), 0DTE-Update (`--intraday`), Pine-Generator, Seed-CSV-Writer
- `providers.py` — Datenquellen: yfinance (US-ETFs) + `eurex_dax()` Web-API
  (ODAX gratis; Datei-Modus als Fallback); ICE-FTSE/Paid als Platzhalter
- `eurex_selftest.py` — validiert die Eurex-Datei-Kette (Parser + IV-Inversion)
- `gex.py` — GEX-Mathematik: BS-Gamma → Flip/Walls/Regal/Max-Pain/EM
  (identisch in der KasseRL-QC-Historie verwendet) + Vanna/Charm-Flow
  (`bs_vanna`, `bs_charm`, dominante Strikes)
- `regen_pine.py` — Pine neu bauen ohne Neuberechnung
- `compare_methods.py` — Diagnose: Methodik- vs. Markt-Effekt zerlegen
- `GammaLevels_auto.pine` — AUTO-GENERIERT, nicht händisch editieren
- `today_levels.txt` — Tages-Level als Text (Struktur + Nah je Index)
- `data/*.csv`, `symbol_info/` — Pine-Seed-Format (für späteres
  TradingView-Seed-Whitelisting; aktuell läuft alles über das Auto-Pine)

## Grenzen (ehrlich)

- **0DTE-Blindfleck:** Heute eröffnete 0DTE-Positionen stehen in keinem OI —
  der `--intraday`-Volumen-Proxy ist die Gratis-Näherung (Validierung
  2026-06-10: Volumen-CW 29.167 traf das NQ-Tageshoch 29.17 exakt).
- **Vorzeichen-Konvention** (Dealer long Calls / short Puts) ist eine
  Modell-Annahme — GEX ist eine Schätzung, kein Kontoauszug.
- **DIA** liefert via yfinance öfter keine 0–1-DTE-Daten (`[skip]` ist normal,
  alte Werte bleiben dann stehen).
- ETF-Proxies (QQQ/DIA/GLD) ≈ Index-Gamma; SPX/NDX-Indexoptionen fehlen.
  Skalierung ETF→Index über das Tages-Verhältnis der Schlusskurse.
- Vor US-Open liefert yfinance gestrige Schluss-IVs/Spots — deshalb sind alle
  Vor-Open-Läufe gleichwertig.

## Ausbau-Ideen

- SPY→SPX als vierter US-Index (eine CONFIG-Zeile)
- Die drei .bat-Läufe als Windows-Aufgabe automatisieren
  (08:30 `--eu` / 14:00 voll / 16:45 `--intraday`, werktags)
- OPEX-Karte (nur Monats-Verfall) in der Woche vor dem 3. Freitag
- FTSE aktivieren, falls je gewünscht: ICE blockt Skripte per Cloudflare →
  Weg wäre Databento (IFEU-Feed), `providers.py` hat den Slot. Vorher prüfen,
  ob EU-Gamma live überhaupt trägt (DAX-Karte 2–3 Wochen als Proxy testen).
- TradingView-Pine-Seed-Whitelisting (Repo public → `request.seed(...)`),
  dann entfällt das tägliche Copy-Paste
