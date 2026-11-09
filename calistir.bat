@echo off
rem 3D Urun Bulucu - cift tiklayarak calistirin.
chcp 65001 >nul
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Ilk kurulum yapiliyor, birkac dakika surebilir...
    python -m venv .venv || (echo Python bulunamadi. README'deki 1. adima bakin. & pause & exit /b 1)
    ".venv\Scripts\python.exe" -m pip install -q --upgrade pip
    ".venv\Scripts\python.exe" -m pip install -q -r requirements.txt
)

if not exist ".env" (
    copy ".env.example" ".env" >nul
    echo .env dosyasi olusturuldu. Icine THINGIVERSE_TOKEN yazip tekrar calistirin.
    notepad ".env"
    pause
    exit /b 1
)

".venv\Scripts\python.exe" -m urun_bulucu
echo.
echo Ozet dosyalari "raporlar" klasorunde.
pause
