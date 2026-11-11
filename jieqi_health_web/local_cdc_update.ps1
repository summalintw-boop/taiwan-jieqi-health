# 在臺灣的電腦上補抓疾管署開放資料，並推送到 GitHub
# GitHub 的伺服器在美國，連不到 od.cdc.gov.tw，所以疾管署資料由這台電腦每週抓一次。
# 推送後 GitHub Actions 會自動重新發布網站。
$ErrorActionPreference = 'Stop'
$git  = 'C:\Program Files\Git\cmd\git.exe'
$repo = Split-Path -Parent $PSScriptRoot
$log  = Join-Path $PSScriptRoot 'local_cdc_update.log'

function Log($m) { "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')  $m" | Tee-Object -FilePath $log -Append }

try {
    Set-Location $repo
    & $git pull --rebase --quiet
    if ($LASTEXITCODE -ne 0) { throw "git pull 失敗" }

    Set-Location (Join-Path $repo 'jieqi_health_web')
    & python -I update_data.py --only cdc
    $j = Get-Content -Raw -Encoding UTF8 'site\data.json' | ConvertFrom-Json
    if ($j.errors.Count -gt 0) { throw "疾管署資料抓取失敗：$($j.errors -join '; ')" }

    Set-Location $repo
    & $git add jieqi_health_web/site/data.json jieqi_health_web/site/index.html
    & $git diff --cached --quiet
    if ($LASTEXITCODE -eq 0) { Log '疾管署資料沒有變動，不需推送'; exit 0 }
    & $git commit -m "data(cdc): 本機補抓疾管署資料 $(Get-Date -Format 'yyyy-MM-dd HH:mm')" --quiet
    & $git push --quiet
    if ($LASTEXITCODE -ne 0) {
        & $git pull --rebase --quiet
        & $git push --quiet
        if ($LASTEXITCODE -ne 0) { throw "git push 失敗" }
    }
    Log '已推送疾管署資料'
}
catch {
    Log "錯誤：$_"
    exit 1
}
