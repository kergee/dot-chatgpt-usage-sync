@echo off
chcp 65001 >nul
cd /d "%~dp0"

where py >nul 2>nul
if errorlevel 1 goto try_python
py "%~dp0dot_usage_sync.py" --install
goto result

:try_python
where python >nul 2>nul
if errorlevel 1 goto no_python
python "%~dp0dot_usage_sync.py" --install
goto result

:no_python
echo 未找到 Python。请先安装 Python 3，然后重新运行本文件。
pause
exit /b 1

:result
if errorlevel 1 (
    echo.
    echo 安装失败，请查看上面的错误信息。
) else (
    echo.
    echo 安装完成。计划任务将每 15 分钟静默同步一次。
)
pause
