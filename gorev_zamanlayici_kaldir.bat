@echo off
schtasks /Delete /F /TN "AlamountRPA_IseGiris"
schtasks /Delete /F /TN "AlamountRPA_PCA"
schtasks /Delete /F /TN "PCA_RPA" 2>nul
pause
