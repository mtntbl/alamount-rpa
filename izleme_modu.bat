@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Alamount RPA - PCA izleme
echo input klasoru PCA icin izleniyor. Durdurmak icin Ctrl+C ...
AlamountRPA.exe pca --watch
pause
