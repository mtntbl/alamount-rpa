@echo off
schtasks /End /TN "AlamountRPA_Ajan" 2>nul
schtasks /Delete /F /TN "AlamountRPA_Ajan" 2>nul
schtasks /End /TN "AlamountRPA_Merkez" 2>nul
schtasks /Delete /F /TN "AlamountRPA_Merkez" 2>nul
netsh advfirewall firewall delete rule name="Alamount RPA Kontrol Merkezi" >nul 2>&1
echo Kaldirildi.
pause
