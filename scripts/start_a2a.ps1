# 启动 4 个 A2A Agent Server
$backendDir = Join-Path $PSScriptRoot "..\backend"

Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$backendDir'; python a2a_server/market_server.py"
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$backendDir'; python a2a_server/profit_server.py"
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$backendDir'; python a2a_server/supply_risk_server.py"
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$backendDir'; python a2a_server/review_insight_server.py"

Write-Host "A2A Agent 已启动: 5101/5102/5103/5104" -ForegroundColor Green
