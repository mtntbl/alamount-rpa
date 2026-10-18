@echo off
chcp 65001 >nul
REM Alamount RPA gorevlerini Windows Gorev Zamanlayici'ya ekler.
REM Kullanim: gorev_zamanlayici_kur.bat [dakika]   (varsayilan 15 dakikada bir)
cd /d "%~dp0"
set ARALIK=%1
if "%ARALIK%"=="" set ARALIK=15
schtasks /Create /F /TN "AlamountRPA_IseGiris" /SC MINUTE /MO %ARALIK% /TR "\"%~dp0AlamountRPA.exe\" --config \"%~dp0config.ini\" ise-giris"
if errorlevel 1 goto :hata
schtasks /Create /F /TN "AlamountRPA_PCA" /SC MINUTE /MO %ARALIK% /TR "\"%~dp0AlamountRPA.exe\" --config \"%~dp0config.ini\" pca --once"
if errorlevel 1 goto :hata
echo "AlamountRPA_IseGiris" ve "AlamountRPA_PCA" gorevleri %ARALIK% dakikada bir calisacak sekilde olusturuldu.
pause
exit /b 0
:hata
echo Gorev olusturulamadi. Bu dosyayi "Yonetici olarak calistir" ile deneyin.
pause
exit /b 1
