
Write-Host "🛑 KILLING ALL PYTHON PROCESSES..." -ForegroundColor Red
taskkill /F /IM python.exe /T
Start-Sleep -Seconds 2

Write-Host "🧹 CLEARING LOGS..." -ForegroundColor Yellow
Clear-Content -Path "c:\Projects\Trading\Trading-fin\bot.log" -ErrorAction SilentlyContinue

Write-Host "🚀 STARTING SERVER..." -ForegroundColor Green
$env:PYTHONPATH = "c:\Projects\Trading\Trading-fin"
$env:PYTHONIOENCODING = "utf-8"
Start-Process -FilePath "python" -ArgumentList "web_ui/server.py" -WorkingDirectory "c:\Projects\Trading\Trading-fin" -RedirectStandardOutput "c:\Projects\Trading\Trading-fin\bot.log" -RedirectStandardError "c:\Projects\Trading\Trading-fin\bot.err" -NoNewWindow
Write-Host "✅ Server launched. Monitoring logs..."
Start-Sleep -Seconds 5
Get-Content -Path "c:\Projects\Trading\Trading-fin\bot.log" -Wait -Tail 20
