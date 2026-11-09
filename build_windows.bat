@echo off
REM ==========================================================================
REM  Builds the Windows installer:  dist\IEEE-Paper-Checker-Setup-<version>.exe
REM  Needs: Python 3.9+ (python.org) and Inno Setup 6 or 7 (https://jrsoftware.org/isdl.php)
REM  People who USE the installer need nothing - Python is bundled inside.
REM ==========================================================================
cd /d "%~dp0"
python -m venv .buildenv || goto :nopython
call .buildenv\Scripts\activate.bat
python -m pip install --upgrade pip >nul
pip install -r requirements.txt pyinstaller || goto :err
python installer\make_icons.py || goto :err
pyinstaller --noconfirm --clean --distpath dist --workpath build installer\ieee_checker.spec || goto :err
for /f %%v in ('python -c "import ieee_checker; print(ieee_checker.__version__)"') do set APPVER=%%v

set ISCC=
if exist "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" set ISCC="%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"
if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set ISCC="%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" set ISCC="%ProgramFiles%\Inno Setup 6\ISCC.exe"
if exist "%LOCALAPPDATA%\Programs\Inno Setup 7\ISCC.exe" set ISCC="%LOCALAPPDATA%\Programs\Inno Setup 7\ISCC.exe"
if exist "%ProgramFiles(x86)%\Inno Setup 7\ISCC.exe" set ISCC="%ProgramFiles(x86)%\Inno Setup 7\ISCC.exe"
if exist "%ProgramFiles%\Inno Setup 7\ISCC.exe" set ISCC="%ProgramFiles%\Inno Setup 7\ISCC.exe"
if not defined ISCC goto :noinno
%ISCC% /Q /DAppVersion=%APPVER% installer\windows\IEEE-Paper-Checker.iss || goto :err
echo.
echo  Installer ready:  dist\IEEE-Paper-Checker-Setup-%APPVER%.exe
echo.
if not "%CI%"=="true" pause
exit /b 0

:noinno
echo.
echo  The app was built in dist\IEEE-Paper-Checker\ but Inno Setup is not installed,
echo  so Setup.exe could not be made. Install it from https://jrsoftware.org/isdl.php
echo  and run this script again.
if not "%CI%"=="true" pause
exit /b 1
:nopython
echo Python 3.9+ is required to BUILD the installer: https://www.python.org/downloads/
if not "%CI%"=="true" pause
exit /b 1
:err
echo Build failed - see the messages above.
if not "%CI%"=="true" pause
exit /b 1
