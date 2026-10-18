@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Alamount RPA
REM Argumansiz: menu. Ornek: calistir.bat ise-giris
AlamountRPA.exe %*
if not "%~1"=="" pause
