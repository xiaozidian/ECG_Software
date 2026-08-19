@echo off
setlocal
pushd "%~dp0"
set "ECG_APP_DATA_ROOT=%~dp0AppData"
set "ECG_CONFIG_PATH=%~dp0config.json"
start "" "%~dp0CardioInsightHolter.exe"
popd
endlocal
