# Sobe o servidor MCP (Streamable HTTP, porta 7301 por padrao).
# Uso:  .\subir-mcp.ps1
$ErrorActionPreference = "Stop"
$raiz = Split-Path -Parent $MyInvocation.MyCommand.Path

# Carrega o .env, se existir. Linhas em branco e comentarios sao ignorados.
$env_file = Join-Path $raiz ".env"
if (Test-Path $env_file) {
    Get-Content $env_file | ForEach-Object {
        if ($_ -match '^\s*([^#=][^=]*)=(.*)$') {
            [Environment]::SetEnvironmentVariable($Matches[1].Trim(), $Matches[2].Trim())
        }
    }
}
if (-not $env:REQUEST_STATE_SECRET) {
    Write-Error "REQUEST_STATE_SECRET nao definido. Copie .env.example para .env e gere a chave com: python -c ""import secrets; print(secrets.token_hex(32))"""
}

$python = Join-Path $raiz ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) { $python = "python" }
& $python (Join-Path $raiz "servidor-mcp\servidor.py")
