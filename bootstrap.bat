@echo off
setlocal enabledelayedexpansion

:: Sari MCP Bootstrap for Windows
set "DIR=%~dp0"
set "ROOT_DIR=%DIR:~0,-1%"

:: Determine INSTALL_DIR
if defined LOCALAPPDATA (
    set "INSTALL_DIR=%LOCALAPPDATA%\sari"
) else (
    set "INSTALL_DIR=%USERPROFILE%\AppData\Local\sari"
)

:: Detect Python
where python >nul 2>nul
if %ERRORLEVEL% equ 0 (
    set "PY=python"
) else (
    where python3 >nul 2>nul
    if %ERRORLEVEL% equ 0 (
        set "PY=python3"
    ) else (
        echo [sari] ERROR: Python not found. Please install Python. >&2
        exit /b 1
    )
)

:: Simple Uninstall (if requested manually)
if "%~1"=="uninstall" (
    echo [sari] uninstalling (remove install, DB, configs, caches)... >&2
    if exist "%ROOT_DIR%\install.py" (
        "%PY%" "%ROOT_DIR%\install.py" --uninstall --no-interactive >nul 2>nul
    ) else (
        "%PY%" -m sari.main --cmd uninstall --no-interactive >nul 2>nul
    )
    echo [sari] done. >&2
    exit /b 0
)

:: Auto-install/Update logic
if not defined SARI_BOOTSTRAP_DONE (
    if /I not "%ROOT_DIR%"=="%INSTALL_DIR%" (
        set "NEED_INSTALL=0"
        if not exist "%INSTALL_DIR%\bootstrap.bat" (
            set "NEED_INSTALL=1"
        ) else (
            :: Check versions
            if exist "%ROOT_DIR%\.git" (
                for /f "tokens=*" %%v in ('git -C "%ROOT_DIR%" describe --tags --abbrev=0 2^>nul') do set "RV=%%v"
                if exist "%INSTALL_DIR%\VERSION" (
                   set /p IV=<"%INSTALL_DIR%\VERSION"
                )
                if not "!RV:v=!"=="!IV!" set "NEED_INSTALL=1"
            )
        )

        if "!NEED_INSTALL!"=="1" (
            if exist "%ROOT_DIR%\install.py" (
                echo [sari] bootstrap: installing to %INSTALL_DIR%... >&2
                set "SARI_BOOTSTRAP_DONE=1"
                "%PY%" "%ROOT_DIR%\install.py" --no-interactive >&2
                if !ERRORLEVEL! neq 0 (
                    echo [sari] bootstrap: install failed. >&2
                )
            )
        )

        if exist "%INSTALL_DIR%\bootstrap.bat" (
            set "SARI_BOOTSTRAP_DONE=1"
            call "%INSTALL_DIR%\bootstrap.bat" %*
            exit /b !ERRORLEVEL!
        )
    )
)

:: Regular Execution
set "PYTHONPATH=%ROOT_DIR%;%PYTHONPATH%"

:: Version from package metadata
for /f "tokens=*" %%v in ('%PY% -c "import importlib,sys; spec=importlib.util.find_spec(\"sari.version\"); print(__import__(\"sari.version\", fromlist=[\"__version__\"]).__version__) if spec else None" 2^>nul') do (
    set "SARI_VERSION=%%v"
)
if /I "%SARI_VERSION%"=="None" set "SARI_VERSION="

set "RUN_MOD=sari.main"

:: Argument loop for --workspace-root / --transport
set "ARGS="
set "TRANSPORT="
:argparse
if "%~1"=="" goto run
if "%~1"=="--workspace-root" (
    set "SARI_WORKSPACE_ROOT=%~2"
    shift
    shift
    goto argparse
)
if "%~1"=="--transport" (
    set "TRANSPORT=%~2"
    shift
    shift
    goto argparse
)
set "ARGS=%ARGS% %1"
shift
goto argparse

:run
if /I "%TRANSPORT%"=="http" (
    "%PY%" -m %RUN_MOD% --transport http %ARGS%
) else if "%ARGS%"=="" (
    "%PY%" -m %RUN_MOD% auto
) else (
    "%PY%" -m %RUN_MOD% %ARGS%
)

endlocal
