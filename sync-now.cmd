@echo off
chcp 65001 >nul
cd /d "%~dp0"

where py >nul 2>nul
if errorlevel 1 goto use_python
py "%~dp0dot_usage_sync.py" --sync
goto result

:use_python
python "%~dp0dot_usage_sync.py" --sync

:result
if errorlevel 1 (
    echo 同步失败，请查看 data\sync.log。
) else (
    echo 同步请求已发送。墨水屏可能需要几分钟完成刷新。
)
pause
