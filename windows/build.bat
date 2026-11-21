@echo off
setlocal
title Build Vanta and Vanta Go
rem Always work in the folder this file is in (double-clicking can start somewhere else).
cd /d "%~dp0"

if not exist "slim.spec" (
  echo.
  echo  slim.spec isn't next to this file.
  echo  Extract the whole zip to a folder first ^(right-click the zip ^> Extract All^), then run build.bat from there.
  goto :fail
)

rem Find Python by running it: the "py" launcher first, then "python".
rem (Windows' "python" shortcut that only opens the Microsoft Store fails this test, which is what we want.)
set "PY="
set "PYA="
py -3 --version >nul 2>nul
if not errorlevel 1 (
  set "PY=py"
  set "PYA=-3"
)
if not defined PY (
  python --version >nul 2>nul
  if not errorlevel 1 set "PY=python"
)
if not defined PY (
  echo.
  echo  Python isn't installed ^(or isn't on PATH^).
  echo  Install Python 3.12 from https://www.python.org/downloads/ and tick "Add python.exe to PATH".
  goto :fail
)
echo Using: %PY% %PYA%
%PY% %PYA% --version
if errorlevel 1 goto :fail

echo.
echo Installing / checking build tools ^(pyinstaller, pillow, pystray, hidapi^)...
%PY% %PYA% -m pip install --disable-pip-version-check --quiet --upgrade pyinstaller pillow pystray hidapi
if errorlevel 1 (
  echo.
  echo  Couldn't install the build tools. Check your internet connection and try again.
  goto :fail
)

echo.
echo Building Vanta.exe ^(takes a minute or two^)...
set VANTA_NAME=Vanta
set VANTA_ENTRY=vanta.py
set VANTA_ADMIN=1
set VANTA_VERSION_FILE=version.txt
%PY% %PYA% -m PyInstaller --noconfirm --workpath build slim.spec
if errorlevel 1 goto :fail

echo.
echo Building VantaGo.exe ^(takes a minute or two^)...
set VANTA_NAME=VantaGo
set VANTA_ENTRY=vanta_go.py
set VANTA_ADMIN=1
set VANTA_VERSION_FILE=version-go.txt
%PY% %PYA% -m PyInstaller --noconfirm --workpath build_g slim.spec
if errorlevel 1 goto :fail

echo.
echo  Done: dist\Vanta.exe and dist\VantaGo.exe
echo  Vanta.exe is for any Windows PC, VantaGo.exe is for the Legion Go.
start "" explorer "%~dp0dist"
pause
exit /b 0

:fail
)

rem Find Python by running it: the "py" launcher first, then "python".
rem (Windows' "python" shortcut that only opens the Microsoft Store fails this test, which is what we want.)
set "PY="
set "PYA="
py -3 --version >nul 2>nul
if not errorlevel 1 (
  set "PY=py"
  set "PYA=-3"
)
if not defined PY (
  python --version >nul 2>nul
  if not errorlevel 1 set "PY=python"
)
if not defined PY (
  echo.
  echo  Python isn't installed ^(or isn't on PATH^).
  echo  Install Python 3.12 from https://www.python.org/downloads/ and tick "Add python.exe to PATH".
  goto :fail
)
echo Using: %PY% %PYA%
%PY% %PYA% --version
if errorlevel 1 goto :fail

echo.
echo Installing / checking build tools ^(pyinstaller, pillow, pystray, hidapi^)...
%PY% %PYA% -m pip install --disable-pip-version-check --quiet --upgrade pyinstaller pillow pystray hidapi
if errorlevel 1 (
  echo.
  echo  Couldn't install the build tools. Check your internet connection and try again.
  goto :fail
)

echo.
echo Building Vanta.exe ^(takes a minute or two^)...
%PY% %PYA% -m PyInstaller --noconfirm slim.spec
if errorlevel 1 goto :fail

echo.
echo  Done: dist\Vanta.exe
start "" explorer "%~dp0dist"
pause
exit /b 0

:fail
echo.
echo  The build didn't finish. Read the message above.
pause
exit /b 1
