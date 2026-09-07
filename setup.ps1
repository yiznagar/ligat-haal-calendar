<#
  setup.ps1  (v2)  -  one-shot deploy of the Ligat ha'Al calendar to GitHub.

  Run from inside the ligat-haal-calendar folder:
      powershell -ExecutionPolicy Bypass -File .\setup.ps1
#>

# Do NOT stop on native-command stderr; we check exit codes ourselves.
$ErrorActionPreference = 'Continue'
$RepoName  = 'ligat-haal-calendar'
$Owner     = 'yiznagar'

Set-Location -Path $PSScriptRoot

function Fail($msg) { Write-Host "`nERROR: $msg" -ForegroundColor Red; exit 1 }

# --- 1. gh present? -----------------------------------------------------------
if (-not (Get-Command gh -ErrorAction SilentlyContinue)) {
    Write-Host "Installing GitHub CLI via winget..." -ForegroundColor Yellow
    winget install --id GitHub.cli -e --source winget `
        --accept-package-agreements --accept-source-agreements
    # refresh PATH for this session
    $env:Path = [Environment]::GetEnvironmentVariable('Path','Machine') + ';' +
                [Environment]::GetEnvironmentVariable('Path','User')
    if (-not (Get-Command gh -ErrorAction SilentlyContinue)) {
        $guess = "C:\Program Files\GitHub CLI"
        if (Test-Path "$guess\gh.exe") { $env:Path += ";$guess" }
    }
    if (-not (Get-Command gh -ErrorAction SilentlyContinue)) {
        Fail "gh installed but not on PATH. CLOSE this window, open a NEW terminal, and re-run .\setup.ps1"
    }
}
Write-Host ("gh: " + (gh --version | Select-Object -First 1)) -ForegroundColor Green

# --- 2. auth ---------------------------------------------------------------
gh auth status 2>&1 | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-Host "`nOpening a browser to log in to GitHub - sign in as '$Owner'." -ForegroundColor Cyan
    gh auth login --hostname github.com --git-protocol https --web
    if ($LASTEXITCODE -ne 0) { Fail "gh auth login failed / cancelled." }
}
gh auth setup-git 2>&1 | Out-Null
$login = (gh api user --jq '.login' 2>$null)
if (-not $login) { Fail "Could not read GitHub user - is the login complete?" }
$login = $login.Trim()
Write-Host "Authenticated as: $login" -ForegroundColor Green
if ($login -ne $Owner) {
    Write-Warning "Logged in as '$login', not '$Owner' - the repo will be created under '$login'."
    $Owner = $login
}
$OwnerRepo = "$Owner/$RepoName"

# --- 3. git init + commit -------------------------------------------------------
if (-not (Test-Path .git)) { git init -b main 2>&1 | Out-Null }
git add -A 2>&1 | Out-Null
git -c user.name='setup' -c user.email='setup@local' commit -m "Ligat ha'Al 2026/27 auto calendar" 2>&1 | Out-Null

# --- 4. create repo (or push to existing) ----------------------------------
gh repo view $OwnerRepo 2>&1 | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-Host "Creating public repo $OwnerRepo ..." -ForegroundColor Cyan
    gh repo create $OwnerRepo --public --source=. --remote=origin --push
    if ($LASTEXITCODE -ne 0) { Fail "gh repo create failed." }
} else {
    Write-Host "Repo $OwnerRepo exists - pushing to it." -ForegroundColor Yellow
    git remote remove origin 2>&1 | Out-Null
    git remote add origin "https://github.com/$OwnerRepo.git"
    git push -u origin main
    if ($LASTEXITCODE -ne 0) { Fail "git push failed." }
}

# --- 5. workflow write permission -----------------------------------------
Write-Host "Granting Actions workflow read/write permission..." -ForegroundColor Cyan
gh api -X PUT "repos/$OwnerRepo/actions/permissions/workflow" `
    -f default_workflow_permissions=write -F can_approve_pull_request_reviews=false 2>&1 | Out-Null

# --- 6. enable Pages (main /docs) ---------------------------------------------
Write-Host "Enabling GitHub Pages (main /docs)..." -ForegroundColor Cyan
gh api -X POST "repos/$OwnerRepo/pages" -f "source[branch]=main" -f "source[path]=/docs" 2>&1 | Out-Null
if ($LASTEXITCODE -ne 0) {
    gh api -X PUT "repos/$OwnerRepo/pages" -f "source[branch]=main" -f "source[path]=/docs" 2>&1 | Out-Null
}

# --- 7. run the workflow now ---------------------------------------------------
Write-Host "Triggering the first calendar build..." -ForegroundColor Cyan
gh workflow run "update-calendar.yml" -R $OwnerRepo 2>&1 | Out-Null
Start-Sleep -Seconds 4
gh run list -R $OwnerRepo --workflow "update-calendar.yml" --limit 2

Write-Host "`n============================================================" -ForegroundColor Green
Write-Host " DONE."
Write-Host " Repo:     https://github.com/$OwnerRepo"
Write-Host " Actions:  https://github.com/$OwnerRepo/actions"
Write-Host " Pages:    https://$Owner.github.io/$RepoName/"
Write-Host " ICS URL:  https://$Owner.github.io/$RepoName/league.ics   <-- paste into Outlook"
Write-Host "============================================================" -ForegroundColor Green
Write-Host " Outlook (web): Add calendar -> Subscribe from web -> paste the ICS URL"
Write-Host " First Pages deploy can take 1-2 minutes to go live."
