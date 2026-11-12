@echo off
chcp 65001 >nul
cd /d "%~dp0"

where py >nul 2>nul
if errorlevel 1 goto use_python
py "%~dp0dot_usage_sync.py" --uninstall
goto result

:use_python
python "%~dp0dot_usage_sync.py" --uninstall

:result
if errorlevel 1 (
    echo.
    echo 卸载失败，请查看上面的错误信息。
) else (
    echo.
    echo 计划任务已删除。本地配置和日志仍然保留。
)
pause
