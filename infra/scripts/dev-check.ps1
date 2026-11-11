<#
.SYNOPSIS
    Checks local Windows developer prerequisites for LAUT SCAN.

.DESCRIPTION
    Verifies Python (3.11+), WSL2, Docker & Docker Compose, .NET SDK (optional/legacy check),
    required local TCP ports (5432, 6379, 8080), and environment configuration files.

.PARAMETER Strict
    Exit with non-zero status if any warning (such as Docker daemon stopped or ports in use) occurs.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File infra/scripts/dev-check.ps1
#>

[CmdletBinding()]
param(
    [switch]$Strict
)

$ErrorActionPreference = "Continue"

$script:FailCount = 0
$script:WarnCount = 0

function Write-CheckResult {
    param(
        [ValidateSet("PASS", "WARN", "FAIL", "INFO")]
        [string]$Status,
        [string]$Category,
        [string]$Message
    )

    $color = switch ($Status) {
        "PASS" { "Green" }
        "WARN" { "Yellow" }
        "FAIL" { "Red" }
        "INFO" { "Cyan" }
    }

    Write-Host ("[{0,-4}] {1,-16} {2}" -f $Status, $Category, $Message) -ForegroundColor $color

    if ($Status -eq "FAIL") { $script:FailCount++ }
    if ($Status -eq "WARN") { $script:WarnCount++ }
}

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
Write-Host "LAUT SCAN Local Environment Check ($RepoRoot)" -ForegroundColor White
Write-Host ("-" * 72)

# ==============================================================================
# 1. Python 3.11+
# ==============================================================================
$pythonCmd = Get-Command python -ErrorAction SilentlyContinue
if (-not $pythonCmd) {
    $pythonCmd = Get-Command py -ErrorAction SilentlyContinue
}

if ($pythonCmd) {
    try {
        $pyOut = @(& $pythonCmd.Source --version 2>&1)
        $pyVerOutput = ($pyOut | Select-Object -First 1).ToString().Trim()
        if ($pyVerOutput -match "Python\s+(\d+)\.(\d+)\.(\d+)") {
            $major = [int]$Matches[1]
            $minor = [int]$Matches[2]
            if (($major -gt 3) -or ($major -eq 3 -and $minor -ge 11)) {
                Write-CheckResult -Status "PASS" -Category "Python" -Message "$pyVerOutput ($($pythonCmd.Source))"
            } else {
                Write-CheckResult -Status "FAIL" -Category "Python" -Message "Found $pyVerOutput, but Python >= 3.11 is required."
            }
        } else {
            Write-CheckResult -Status "WARN" -Category "Python" -Message "Could not parse Python version: $pyVerOutput"
        }
    } catch {
        Write-CheckResult -Status "FAIL" -Category "Python" -Message "Failed to invoke Python: $_"
    }
} else {
    Write-CheckResult -Status "FAIL" -Category "Python" -Message "Python 3.11+ not found in PATH."
}

# ==============================================================================
# 2. WSL2
# ==============================================================================
$wslCmd = Get-Command wsl.exe -ErrorAction SilentlyContinue
if (-not $wslCmd) {
    $wslCmd = Get-Command wsl -ErrorAction SilentlyContinue
}

if ($wslCmd) {
    try {
        $distrosRaw = @(& $wslCmd.Source -l -q 2>&1)
        $wslExit = $LASTEXITCODE
        $distros = @($distrosRaw | ForEach-Object { ($_ -replace "`0", "").Trim() } | Where-Object { $_ -ne "" })
        if ($wslExit -eq 0 -and $distros.Count -gt 0) {
            Write-CheckResult -Status "PASS" -Category "WSL2" -Message ("WSL installed; distros: " + ($distros -join ", "))
        } else {
            Write-CheckResult -Status "WARN" -Category "WSL2" -Message "WSL command exists, but no Linux distributions were detected (run: wsl --install -d Ubuntu)."
        }
    } catch {
        Write-CheckResult -Status "WARN" -Category "WSL2" -Message "Unable to query WSL distributions: $_"
    }
} else {
    Write-CheckResult -Status "FAIL" -Category "WSL2" -Message "WSL not found. WSL2 + Ubuntu is required on Windows for Expo Exact."
}

# ==============================================================================
# 3. Docker & Docker Compose
# ==============================================================================
$dockerCmd = Get-Command docker -ErrorAction SilentlyContinue
if ($dockerCmd) {
    $dockerVerOut = @(& $dockerCmd.Source --version 2>&1)
    $dockerVer = ($dockerVerOut | Select-Object -First 1).ToString().Trim()
    $composeVerOut = @(& $dockerCmd.Source compose version 2>&1)
    $composeExit = $LASTEXITCODE
    $composeVer = ($composeVerOut | Select-Object -First 1).ToString().Trim()
    if ($composeExit -eq 0) {
        Write-CheckResult -Status "PASS" -Category "Docker CLI" -Message "$dockerVer | $composeVer"
    } else {
        Write-CheckResult -Status "WARN" -Category "Docker CLI" -Message "$dockerVer (Docker Compose v2 plugin check returned exit $composeExit)"
    }

    $null = @(& $dockerCmd.Source info 2>&1)
    if ($LASTEXITCODE -eq 0) {
        Write-CheckResult -Status "PASS" -Category "Docker Daemon" -Message "Docker Engine is running."
    } else {
        Write-CheckResult -Status "WARN" -Category "Docker Daemon" -Message "Docker CLI installed, but Docker Desktop/Engine daemon is not running."
    }
} else {
    Write-CheckResult -Status "FAIL" -Category "Docker" -Message "Docker not found in PATH. Install Docker Desktop (with WSL2 backend)."
}

# ==============================================================================
# 4. .NET SDK (optional / toolchain check)
# ==============================================================================
$dotnetCmd = Get-Command dotnet -ErrorAction SilentlyContinue
if ($dotnetCmd) {
    $dotnetOut = @(& $dotnetCmd.Source --version 2>&1)
    $dotnetExit = $LASTEXITCODE
    $dotnetVer = ($dotnetOut | Select-Object -First 1).ToString().Trim()
    if ($dotnetExit -eq 0 -and $dotnetVer) {
        Write-CheckResult -Status "PASS" -Category "dotnet" -Message ".NET SDK $dotnetVer ($($dotnetCmd.Source))"
    } else {
        Write-CheckResult -Status "INFO" -Category "dotnet" -Message "dotnet found, version check returned exit $dotnetExit (optional in PRD v1.2)."
    }
} else {
    Write-CheckResult -Status "INFO" -Category "dotnet" -Message "Not installed (optional in PRD v1.2; backend uses Python 3.11+ FastAPI)."
}

# ==============================================================================
# 5. Local TCP Port Availability (5432, 6379, 8080)
# ==============================================================================
$expectedPorts = @(
    @{ Port = 5432; Service = "PostgreSQL/PostGIS" },
    @{ Port = 6379; Service = "Redis" },
    @{ Port = 8080; Service = "FastAPI Backend API" }
)

try {
    $ipProps = [System.Net.NetworkInformation.IPGlobalProperties]::GetIPGlobalProperties()
    $activeListeners = $ipProps.GetActiveTcpListeners() | ForEach-Object { $_.Port } | Sort-Object -Unique

    foreach ($entry in $expectedPorts) {
        $port = $entry.Port
        $svc = $entry.Service
        if ($activeListeners -contains $port) {
            Write-CheckResult -Status "WARN" -Category "Port $port" -Message "Port $port ($svc) is currently IN USE (check if existing service or container is bound)."
        } else {
            Write-CheckResult -Status "PASS" -Category "Port $port" -Message "Port $port ($svc) is free."
        }
    }
} catch {
    Write-CheckResult -Status "WARN" -Category "Ports" -Message "Could not inspect TCP listeners: $_"
}

# ==============================================================================
# 6. Environment & Compose Files Check
# ==============================================================================
$envExample = Join-Path $RepoRoot "infra\.env.example"
$envLocal = Join-Path $RepoRoot "infra\.env"
$composeFile = Join-Path $RepoRoot "infra\docker-compose.yml"

if (Test-Path $composeFile) {
    Write-CheckResult -Status "PASS" -Category "Compose" -Message "Found infra/docker-compose.yml"
} else {
    Write-CheckResult -Status "FAIL" -Category "Compose" -Message "Missing infra/docker-compose.yml"
}

if (Test-Path $envLocal) {
    Write-CheckResult -Status "PASS" -Category "Env File" -Message "Found infra/.env"
} elseif (Test-Path $envExample) {
    Write-CheckResult -Status "INFO" -Category "Env File" -Message "infra/.env not created yet (copy infra/.env.example -> infra/.env before customizing)."
} else {
    Write-CheckResult -Status "WARN" -Category "Env File" -Message "Missing infra/.env.example"
}

# ==============================================================================
# Summary
# ==============================================================================
Write-Host ("-" * 72)
Write-Host ("Summary: {0} failure(s), {1} warning(s)" -f $script:FailCount, $script:WarnCount) -ForegroundColor White

if ($script:FailCount -gt 0) {
    exit 1
}
if ($Strict -and $script:WarnCount -gt 0) {
    exit 1
}
exit 0
