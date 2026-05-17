# 启动 4 个 MCP Server
$backendDir = Join-Path $PSScriptRoot "..\backend"

Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$backendDir'; python mcp_server/mcp_market_server.py"
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$backendDir'; python mcp_server/mcp_profit_server.py"
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$backendDir'; python mcp_server/mcp_supply_risk_server.py"
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$backendDir'; python mcp_server/mcp_review_server.py"

Write-Host "MCP Server 已启动: 8101/8102/8103/8104" -ForegroundColor Green
