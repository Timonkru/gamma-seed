@echo off
rem ============================================================
rem  GAMMA MORGENLAUF EU  --  ~08:30 Berlin, VOR DAX-Open 09:00
rem  Holt NUR DAX frisch (Eurex-EOD von gestern). US = Vortag.
rem  Danach liegt der Pine-Code in der ZWISCHENABLAGE.
rem ============================================================
cd /d "%~dp0"
echo === Gamma EU-Morgenlauf (DAX frisch, US=Vortag) ===
echo.
python build_seed.py --eu
if errorlevel 1 (
    echo.
    echo FEHLER - Ausgabe oben pruefen. Wichtig: "[eurex] ... Stand YYYYMMDD"
    echo muss den VORTAG zeigen, sonst hinkt die Eurex-Quelle.
    pause
    exit /b 1
)
clip < GammaLevels_auto.pine
echo.
echo ============================================================
echo  FERTIG. Pine-Code ist in der ZWISCHENABLAGE.
echo  TradingView Pine-Editor: Strg+A, Strg+V, Save. Einfrieren.
echo ============================================================
pause
