@echo off
rem ============================================================
rem  GAMMA VOLLER LAUF  --  ~14:00 Berlin (nach US-OI-Update
rem  ~12:30, VOR US-Open 15:30). Rechnet ALLES neu:
rem  NQ / DOW / GOLD (yfinance) + DAX (Eurex-API).
rem  Danach liegt der Pine-Code in der ZWISCHENABLAGE.
rem ============================================================
cd /d "%~dp0"
echo === Gamma voller Lauf (US frisch + DAX) ===
echo.
python build_seed.py
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
echo  TradingView Pine-Editor: Strg+A, Strg+V, Save. Einfrieren.
echo  Hinweis: nach US-Feiertagen koennen yfinance-Ketten stale
echo  sein ([skip]/Flip 0) - dann spaeter erneut laufen lassen.
echo ============================================================
pause
