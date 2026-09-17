@echo off
setlocal
set "SPECTRUM_DATA_DIR=%~dp0demo-data"
start "" /D "%~dp0" "%~dp0GeoSpectrum.exe"
endlocal
