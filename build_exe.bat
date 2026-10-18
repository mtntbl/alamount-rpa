@echo off
REM Windows'ta Alamount RPA'yi kendiniz derlemek icin (Python 3.12 x64 kurulu olmali).
REM Tesseract icin once:  winget install UB-Mannheim.TesseractOCR
REM ARM64 Windows'ta x64 Python kurun (paket x64 emulasyonla calisir).
cd /d "%~dp0"
python -m venv .venv || goto :err
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements.txt pyinstaller || goto :err
pyinstaller --noconfirm --clean AlamountRPA.spec || goto :err
if exist paket rmdir /s /q paket
xcopy /e /i /q dist\AlamountRPA paket >nul
for %%d in (input input\ise_giris output archive error logs) do mkdir paket\%%d 2>nul
copy config.ini paket\ >nul
copy KULLANIM.md paket\ >nul
copy calistir.bat paket\ >nul
copy izleme_modu.bat paket\ >nul
copy gorev_zamanlayici_kur.bat paket\ >nul
copy gorev_zamanlayici_kaldir.bat paket\ >nul
copy merkez_kur.bat paket\ >nul
copy ajan_kur.bat paket\ >nul
copy merkez_ajan_kaldir.bat paket\ >nul
xcopy /e /i /q marka paket\marka >nul
xcopy /e /i /q gorevler paket\gorevler >nul
xcopy /e /i /q ornek_veri paket\ornek_veri >nul
set TESS=%ProgramFiles%\Tesseract-OCR
if exist "%TESS%\tesseract.exe" (
  mkdir paket\tesseract\tessdata 2>nul
  copy "%TESS%\*.exe" paket\tesseract\ >nul
  copy "%TESS%\*.dll" paket\tesseract\ >nul
  copy "%TESS%\tessdata\eng.traineddata" paket\tesseract\tessdata\ >nul
  copy "%TESS%\tessdata\osd.traineddata" paket\tesseract\tessdata\ >nul
  if exist "%TESS%\tessdata\tur.traineddata" (
    copy "%TESS%\tessdata\tur.traineddata" paket\tesseract\tessdata\ >nul
  ) else (
    powershell -NoProfile -Command "Invoke-WebRequest https://github.com/tesseract-ocr/tessdata_fast/raw/main/tur.traineddata -OutFile paket\tesseract\tessdata\tur.traineddata"
  )
) else (
  echo UYARI: Tesseract bulunamadi; pakete eklenmedi. OCR icin hedef makinede Tesseract kurun.
)
powershell -NoProfile -Command "Compress-Archive -Path paket\* -DestinationPath AlamountRPA_Windows.zip -Force"
echo.
echo Hazir: %~dp0AlamountRPA_Windows.zip
pause
exit /b 0
:err
echo Derleme basarisiz.
pause
exit /b 1
