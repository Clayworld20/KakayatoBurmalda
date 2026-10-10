@echo off
rem ===========================================================================
rem  wireless-adb-nowifi.cmd — тонкая обёртка для Windows.
rem  Запускает wireless-adb-nowifi.sh через bash (Git Bash / WSL), если он есть,
rem  иначе печатает подсказку. Аргументы передаются как есть:
rem     wireless-adb-nowifi.cmd --strategy usb-tcpip
rem     wireless-adb-nowifi.cmd --status
rem ===========================================================================
setlocal

set "SCRIPT_DIR=%~dp0"
set "SH_SCRIPT=%SCRIPT_DIR%wireless-adb-nowifi.sh"

if not exist "%SH_SCRIPT%" (
  echo [x] Не найден %SH_SCRIPT%
  exit /b 1
)

rem 1) bash из Git Bash / MSYS2 / Cygwin
for %%P in ("%ProgramFiles%\Git\bin\bash.exe" "%ProgramFiles%\Git\usr\bin\bash.exe" "%LOCALAPPDATA%\Programs\Git\bin\bash.exe" "C:\Program Files\Git\bin\bash.exe") do (
  if exist %%~P (
    "%%~P" "%SH_SCRIPT%" %*
    exit /b %ERRORLEVEL%
  )
)

rem 2) bash в PATH
where bash >nul 2>nul
if %ERRORLEVEL%==0 (
  bash "%SH_SCRIPT%" %*
  exit /b %ERRORLEVEL%
)

rem 3) WSL
where wsl >nul 2>nul
if %ERRORLEVEL%==0 (
  wsl bash "%SH_SCRIPT%" %*
  exit /b %ERRORLEVEL%
)

echo [x] Не найден bash. Установите Git for Windows (https://git-scm.com)
echo     или запускайте скрипт из WSL. Альтернатива без bash — рецепты
echo     из docs\SNIPPETS.md (блоки A, C, D).
exit /b 1
