@echo off
REM ProxmoxSession Windows Installer
REM Usage:
REM   install.bat          — full install / update
REM   install.bat --check  — check current installation status without changing anything

REM -------------------------------------------------------
REM Locate Python — try PATH first, then common install dirs
REM -------------------------------------------------------
set PYTHON_EXE=
set PYTHONW_EXE=

python --version >nul 2>&1
if not errorlevel 1 (
    set PYTHON_EXE=python
    set PYTHONW_EXE=pythonw
    goto :python_found
)

for %%V in (312 311 310) do (
    if exist "%LOCALAPPDATA%\Programs\Python\Python%%V\python.exe" (
        set PYTHON_EXE=%LOCALAPPDATA%\Programs\Python\Python%%V\python.exe
        set PYTHONW_EXE=%LOCALAPPDATA%\Programs\Python\Python%%V\pythonw.exe
        goto :python_found
    )
)

for %%V in (312 311 310) do (
    if exist "%PROGRAMFILES%\Python%%V\python.exe" (
        set PYTHON_EXE=%PROGRAMFILES%\Python%%V\python.exe
        set PYTHONW_EXE=%PROGRAMFILES%\Python%%V\pythonw.exe
        goto :python_found
    )
)

echo ERROR: Python 3.10+ not found.
echo Please install from https://www.python.org/downloads/
echo Make sure to check "Add Python to PATH" during installation.
pause
exit /b 1

:python_found
REM Resolve project root to absolute path
pushd "%~dp0.."
set PROJECT_DIR=%CD%
popd

REM -------------------------------------------------------
REM --check mode: run the checker and exit
REM -------------------------------------------------------
if /i "%~1"=="--check" (
    echo.
    "%PYTHON_EXE%" "%~dp0check.py"
    set CHECK_EXIT=%ERRORLEVEL%
    echo.
    pause
    exit /b %CHECK_EXIT%
)

REM -------------------------------------------------------
REM Full install
REM -------------------------------------------------------
echo === ProxmoxSession Windows Installer ===
echo.
echo Found Python: %PYTHON_EXE%
"%PYTHON_EXE%" --version
echo.
echo Project directory: %PROJECT_DIR%
echo.

REM Step 1: Install package and dependencies
echo [1/5] Installing ProxmoxSession and dependencies...
"%PYTHON_EXE%" -m pip install -e "%PROJECT_DIR%"
if errorlevel 1 (
    echo ERROR: pip install failed. See output above.
    pause
    exit /b 1
)

REM Step 2: virt-viewer
echo.
echo [2/5] Checking virt-viewer (SPICE client)...
cmd /c "ftype VirtViewer.vvfile" >nul 2>&1
if not errorlevel 1 (
    echo virt-viewer already installed.
    goto :vv_done
)
echo virt-viewer not found. Installing via winget...
winget install --id RedHat.VirtViewer --silent --accept-package-agreements --accept-source-agreements
if errorlevel 1 (
    echo.
    echo WARNING: winget install failed.
    echo Please manually download virt-viewer from:
    echo   https://virt-manager.org/download/
    echo Then re-run this installer.
    pause
)
:vv_done

REM Step 3: Config file
echo.
echo [3/5] Creating config directory...
if not exist "%APPDATA%\VDIClient" mkdir "%APPDATA%\VDIClient"
if not exist "%APPDATA%\VDIClient\vdiclient.ini" (
    copy /Y "%PROJECT_DIR%\vdiclient.ini.example" "%APPDATA%\VDIClient\vdiclient.ini"
    echo Default config written to: %APPDATA%\VDIClient\vdiclient.ini
    echo Please edit this file with your Proxmox server details before running.
) else (
    echo Config already exists at: %APPDATA%\VDIClient\vdiclient.ini
)

REM Step 4: Start Menu shortcuts
echo.
echo [4/5] Creating Start Menu shortcuts...
set SHORTCUT_DIR=%APPDATA%\Microsoft\Windows\Start Menu\Programs

powershell -Command "$ws = New-Object -ComObject WScript.Shell; $sc = $ws.CreateShortcut([System.IO.Path]::Combine('%SHORTCUT_DIR%', 'ProxmoxSession.lnk')); $sc.TargetPath = '%PYTHONW_EXE%'; $sc.Arguments = '-m proxmox_session'; $sc.WorkingDirectory = '%PROJECT_DIR%'; $sc.Description = 'Proxmox VDI Session Client'; $sc.Save(); Write-Host 'VDI shortcut saved.'"

powershell -Command "$ws = New-Object -ComObject WScript.Shell; $sc = $ws.CreateShortcut([System.IO.Path]::Combine('%SHORTCUT_DIR%', 'ProxmoxSession Config.lnk')); $sc.TargetPath = '%PYTHONW_EXE%'; $sc.Arguments = '-m proxmox_session.config_editor'; $sc.WorkingDirectory = '%PROJECT_DIR%'; $sc.Description = 'ProxmoxSession Configuration Editor'; $sc.Save(); Write-Host 'Config editor shortcut saved.'"

if errorlevel 1 (
    echo WARNING: Could not create Start Menu shortcuts.
) else (
    echo Shortcuts created in Start Menu.
)

REM Step 5: Write install state (pyproject.toml hash + metadata)
echo.
echo [5/5] Recording install state...
"%PYTHON_EXE%" -c "import hashlib, json, os, sys; p=r'%PROJECT_DIR%\pyproject.toml'; h=hashlib.sha256(open(p,'rb').read()).hexdigest(); state={'pyproject_hash':h,'python':sys.version,'project_dir':r'%PROJECT_DIR%'}; open(r'%PROJECT_DIR%\.install_state.json','w').write(json.dumps(state,indent=2)); print('State written: hash=' + h[:12] + '...')"
if errorlevel 1 (
    echo WARNING: Could not write install state.
) else (
    echo Install state recorded.
)

echo.
echo ============================================
echo Installation complete!
echo.
echo Next steps:
echo   1. Edit your Proxmox server details:
echo      %APPDATA%\VDIClient\vdiclient.ini
echo.
echo   2. Launch the app:
echo      Start Menu ^> ProxmoxSession
echo      OR: "%PYTHONW_EXE%" -m proxmox_session
echo.
echo   3. Check installation health anytime:
echo      install.bat --check
echo ============================================
pause
