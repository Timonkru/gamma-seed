# Gamma-Seed v2 — Tägliche Gamma-Level für TradingView (NQ / DOW / GOLD)

Berechnet täglich **Gamma-Flip, Call/Put-Walls, Strike-Regal, Expected Move** aus
echten Options-Daten (yfinance: QQQ→NQ, DIA→DOW, GLD→GOLD) und generiert den
TradingView-Indikator `GammaLevels_auto.pine` mit eingebrannten Tages-Leveln.

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
# 1) MORGENS, ~14:00 Berlin (nach OI-Update ~12:30, VOR US-Open 15:30):
python build_seed.py
#    -> rechnet ALLES neu, schreibt data/*.csv + GammaLevels_auto.pine
#    -> Datei komplett in den TradingView-Pine-Editor kopieren, Save. FERTIG.
#    Die Level sind damit fuer den Tag EINGEFROREN.

# 2) OPTIONAL NACHMITTAGS, ~16:45 Berlin (nach der 1. US-Stunde):
python build_seed.py --intraday
#    -> zieht NUR 0-1-DTE-Ketten, nimmt das HEUTIGE Volumen (nicht OI),
#       aktualisiert NUR die gepunkteten 0DTE-Walls. Struktur unangetastet.
#    -> Label zeigt "+0DTE-Vol-Update". Wieder einfuegen.

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

- `build_seed.py` — Orchestrator: Morgen-Build (`main`), Nachmittags-Update
  (`intraday_update`), Pine-Generator, Seed-CSV-Writer
- `providers.py` — Datenquellen (yfinance aktiv; Eurex/ICE/Paid als Plan)
- `gex.py` — GEX-Mathematik: BS-Gamma → Flip/Walls/Regal/Max-Pain/EM
  (identisch in der KasseRL-QC-Historie verwendet)
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

- SPY→SPX als vierter Index (eine CONFIG-Zeile)
- Beide Läufe als Windows-Aufgabe (14:00 / 16:45 werktags) automatisieren
- OPEX-Karte (nur Monats-Verfall) in der Woche vor dem 3. Freitag
- Eurex-DAX / ICE-FTSE (bezahlte OI-Files) → `providers.py`-Platzhalter
- TradingView-Pine-Seed-Whitelisting (Repo public → `request.seed(...)`),
  dann entfällt das tägliche Copy-Paste
