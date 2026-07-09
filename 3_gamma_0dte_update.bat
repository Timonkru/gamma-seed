@echo off
rem ============================================================
rem  GAMMA 0DTE-UPDATE (optional)  --  ~16:45 Berlin
rem  (nach der 1. US-Stunde). Aktualisiert NUR die gepunkteten
rem  0DTE-Walls aus dem HEUTIGEN Volumen (US-ETFs; DAX bleibt
rem  eingefroren). Struktur-Linien unangetastet = kein Repaint.
rem ============================================================
cd /d "%~dp0"
echo === Gamma 0DTE-Volumen-Update (nur gepunktete US-Linien) ===
echo.
python build_seed.py --intraday
if errorlevel 1 (
    echo.
    echo FEHLER - Ausgabe oben pruefen.
    pause
    exit /b 1
)
clip < GammaLevels_auto.pine
echo.
echo ============================================================
echo  FERTIG. Pine-Code ist in der ZWISCHENABLAGE.
echo  TradingView Pine-Editor: Strg+A, Strg+V, Save.
echo ============================================================
pause
