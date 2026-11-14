@echo off
setlocal
cd /d "%~dp0"
title LUNARA - Local SPICE Engine

where py >nul 2>nul
if errorlevel 1 (
  echo Python launcher "py" was not found. Install Python 3 from python.org and enable the Python launcher.
  pause
  exit /b 1
)

py -c "import spiceypy" >nul 2>nul
if errorlevel 1 (
  echo Installing SpiceyPy...
  py -m pip install -r requirements_spice.txt
  if errorlevel 1 (
    echo Could not install SpiceyPy. Check your Python installation and internet connection.
    pause
    exit /b 1
  )
)

py lunara_spice_server.py --kernel-dir kernels --html index.html --download-missing
pause
