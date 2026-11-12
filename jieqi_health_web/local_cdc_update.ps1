# 在臺灣的電腦上補抓疾管署開放資料，並推送到 GitHub
# GitHub 的伺服器在美國，連不到 od.cdc.gov.tw，所以疾管署資料由這台電腦每週抓一次。
# 同時重算節令健康曆的 24 節氣歷史季節性（cdc_seasonal.py）。
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

    # 節令健康曆：重新下載多年期 CSV，重算 24 節氣歷史季節性與報告（失敗不影響上面的資料更新）
    # 注意：不要加 -I，cdc_seasonal.py 需要讀同資料夾的 term_normals.py、update_data.py
    $seasOk = $true
    try {
        & python cdc_seasonal.py --download
        if ($LASTEXITCODE -ne 0) { throw "結束代碼 $LASTEXITCODE" }
    } catch { $seasOk = $false; Log "警告：歷史季節性重算失敗，沿用上一版：$_" }
    # 健康提醒規則（HIST）是否仍與最新統計一致；不一致只記錄，不自動改規則（改規則需人工確認）
    if ($seasOk) {
        & python sync_hist_rules.py --check | Out-Null
        if ($LASTEXITCODE -ne 0) { Log '注意：健康提醒規則與最新歷史統計不一致，請執行 python sync_hist_rules.py --check 查看，確認後再執行 python sync_hist_rules.py 更新' }
    }

    Set-Location $repo
    & $git add jieqi_health_web/site/data.json jieqi_health_web/site/index.html
    if ($seasOk) { & $git add jieqi_health_web/site/cdc_seasonal.json jieqi_health_web/reports }
    & $git diff --cached --quiet
    if ($LASTEXITCODE -eq 0) { Log '疾管署資料沒有變動，不需推送'; exit 0 }
    & $git commit -m "data(cdc): 本機補抓疾管署資料 $(Get-Date -Format 'yyyy-MM-dd HH:mm')" --quiet
    # 推送；若 GitHub Actions 同時也推了 data.json（例如每天 06:10、14:10 的更新），
    # 會在 rebase 時衝突：改用 GitHub 上的 data.json，再把疾管署資料重新併進去。
    $pushed = $false
    for ($k = 1; $k -le 3 -and -not $pushed; $k++) {
        & $git push --quiet
        if ($LASTEXITCODE -eq 0) { $pushed = $true; break }
        Log "推送被拒（第 $k 次），先同步 GitHub 上的新版本"
        & $git pull --rebase --quiet
        if ($LASTEXITCODE -ne 0) {
            $conf = @(& $git diff --name-only --diff-filter=U)
            $other = @($conf | Where-Object { $_ -notin @('jieqi_health_web/site/data.json', 'jieqi_health_web/site/index.html') })
            if ($conf.Count -eq 0 -or $other.Count -gt 0) {
                & $git rebase --abort
                throw "同步時發生無法自動處理的衝突：$($conf -join ', ')"
            }
            & $git checkout --ours -- $conf
            Set-Location (Join-Path $repo 'jieqi_health_web')
            & python -I update_data.py --only cdc
            Set-Location $repo
            & $git add jieqi_health_web/site/data.json jieqi_health_web/site/index.html
            $env:GIT_EDITOR = 'true'
            & $git rebase --continue
            if ($LASTEXITCODE -ne 0) { & $git rebase --abort; throw "rebase 無法完成" }
            Log '已改用 GitHub 上的 data.json 並重新併入疾管署資料'
        }
    }
    if (-not $pushed) { throw "git push 失敗" }
    Log "已推送疾管署資料$(if ($seasOk) { '（含歷史季節性）' } else { '（歷史季節性未更新）' })"
}
catch {
    Log "錯誤：$_"
    exit 1
}
