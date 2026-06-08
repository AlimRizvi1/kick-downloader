@echo off
setlocal enabledelayedexpansion

title Kick Downloader Build System

echo ======================================================
echo        KICK DOWNLOADER BUILD SYSTEM
echo ======================================================
echo.

:: ======================================================
:: CHECK REQUIRED FILES
:: ======================================================

if not exist requirements.txt (
echo [ERROR] requirements.txt not found.
pause
exit /b 1
)

if not exist src\download.py (
echo [ERROR] src\download.py not found.
pause
exit /b 1
)

if not exist assets\icon.ico (
echo [ERROR] assets\icon.ico not found.
pause
exit /b 1
)

:: ======================================================
:: CHECK FFMPEG
:: ======================================================

if not exist ffmpeg\ffmpeg.exe (
echo.
echo [WARNING] ffmpeg.exe not found.
echo Your build will NOT be fully portable.
echo.
)

if not exist ffmpeg\ffprobe.exe (
echo.
echo [WARNING] ffprobe.exe not found.
echo Your build will NOT be fully portable.
echo.
)

:: ======================================================
:: INSTALL DEPENDENCIES
:: ======================================================

echo Installing dependencies...
pip install -r requirements.txt

if errorlevel 1 (
echo.
echo [ERROR] Failed to install dependencies.
pause
exit /b 1
)

:: ======================================================
:: CLEAN OLD BUILDS
:: ======================================================

echo.
echo Cleaning old build files...

rmdir /s /q build 2>nul
rmdir /s /q dist 2>nul

del /q *.spec 2>nul

:: ======================================================
:: BUILD APPLICATION
:: ======================================================

echo.
echo Building application...
echo.

pyinstaller ^
--noconfirm ^
--clean ^
--onedir ^
--windowed ^
--noupx ^
--name "Kick Downloader v1.0.0" ^
--icon=assets/icon.ico ^
--version-file=version_info.txt ^
--add-data "assets;assets" ^
--add-data "ffmpeg;ffmpeg" ^
--collect-all yt_dlp ^
--hidden-import=customtkinter ^
--hidden-import=requests ^
--hidden-import=PIL ^
--hidden-import=yt_dlp ^
src/download.py

if errorlevel 1 (
echo.
echo ======================================================
echo BUILD FAILED
echo ======================================================
echo.
pause
exit /b 1
)

:: ======================================================
:: VERIFY BUILD
:: ======================================================

echo.
echo Verifying build...

if exist "dist\Kick Downloader v1.0.0\Kick Downloader v1.0.0.exe" (
echo [OK] EXE created successfully.
) else (
echo [ERROR] EXE missing.
pause
exit /b 1
)

:: ======================================================
:: COMPLETE
:: ======================================================

echo.
echo ======================================================
echo BUILD SUCCESSFUL
echo ======================================================
echo.
echo Output:
echo dist\Kick Downloader v1.0.0
echo.
echo Main executable:
echo Kick Downloader v1.0.0.exe
echo.
echo Ready for Inno Setup installer build.
echo.

pause
