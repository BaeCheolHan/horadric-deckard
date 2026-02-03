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
    echo [sari] uninstalling... >&2
    if exist "%INSTALL_DIR%\bootstrap.bat" (
        call "%INSTALL_DIR%\bootstrap.bat" daemon stop >nul 2>nul
    )
    if exist "%INSTALL_DIR%" rd /s /q "%INSTALL_DIR%"
    echo [sari] done. >&2
    exit /b 0
)

:: Auto-install/Update logic
if not defined DECKARD_BOOTSTRAP_DONE (
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
                set "DECKARD_BOOTSTRAP_DONE=1"
                "%PY%" "%ROOT_DIR%\install.py" --no-interactive >&2
                if !ERRORLEVEL! neq 0 (
                    echo [sari] bootstrap: install failed. >&2
                )
            )
        )

        if exist "%INSTALL_DIR%\bootstrap.bat" (
            set "DECKARD_BOOTSTRAP_DONE=1"
            call "%INSTALL_DIR%\bootstrap.bat" %*
            exit /b !ERRORLEVEL!
        )
    )
)

:: Regular Execution
set "PYTHONPATH=%ROOT_DIR%;%PYTHONPATH%"

:: Version from Git
if exist "%ROOT_DIR%\.git" (
    for /f "tokens=*" %%v in ('git -C "%ROOT_DIR%" describe --tags --abbrev=0 2^>nul') do (
        set "V=%%v"
        set "DECKARD_VERSION=!V:v=!"
    )
)

:: Argument loop for --workspace-root
set "ARGS="
:argparse
if "%~1"=="" goto run
if "%~1"=="--workspace-root" (
    set "DECKARD_WORKSPACE_ROOT=%~2"
    shift
    shift
    goto argparse
)
set "ARGS=%ARGS% %1"
shift
goto argparse

:run
if "%ARGS%"=="" (
    "%PY%" -m sari
) else (
    "%PY%" -m sari --cmd %ARGS%
)

endlocal
