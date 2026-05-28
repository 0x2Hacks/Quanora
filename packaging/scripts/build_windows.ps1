param(
    [switch]$SkipPortableGit,
    [switch]$SkipInstaller,
    [switch]$AllowPortableGitFallback
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$Root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$DistDir = Join-Path $Root "dist\chainpeer"
$ReleaseDir = Join-Path $Root "release"
$VendorDir = Join-Path $Root "packaging\vendor"
$BuildVenvDir = Join-Path $Root ".venv-build"
$BuildPython = Join-Path $BuildVenvDir "Scripts\python.exe"
$GitVersion = "2.45.2"
$PortableGitArchive = "PortableGit-$GitVersion-64-bit.7z.exe"
$MinGitArchive = "MinGit-$GitVersion-64-bit.zip"
$PortableGitUrl = "https://github.com/git-for-windows/git/releases/download/v$GitVersion.windows.1/$PortableGitArchive"
$MinGitUrl = "https://github.com/git-for-windows/git/releases/download/v$GitVersion.windows.1/$MinGitArchive"
$PortableGitExe = Join-Path $VendorDir $PortableGitArchive
$MinGitZip = Join-Path $VendorDir $MinGitArchive
$PortableGitExtractDir = Join-Path $VendorDir "portable-git-$GitVersion"
$MinGitExtractDir = Join-Path $VendorDir "mingit-$GitVersion"

function Write-Step($Message) {
    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Get-ChainPeerVersion() {
    Push-Location $Root
    try {
        return (python -c "from agent.version import __version__; print(__version__)").Trim()
    }
    finally {
        Pop-Location
    }
}

function Copy-PortableGit() {
    if ($SkipPortableGit) {
        Write-Host "Skipping MinGit bundle."
        return
    }

    New-Item -ItemType Directory -Force -Path $VendorDir | Out-Null

    $SourceDir = $null

    if (Test-GitBundleDir $MinGitExtractDir) {
        $SourceDir = $MinGitExtractDir
    } elseif ($AllowPortableGitFallback -and (Test-GitBundleDir $PortableGitExtractDir)) {
        $SourceDir = $PortableGitExtractDir
    }

    if (-not $SourceDir) {
        if (-not (Test-Path $MinGitZip)) {
            Write-Step "Downloading MinGit $GitVersion"
            try {
                Invoke-WebRequest -Uri $MinGitUrl -OutFile $MinGitZip
            }
            catch {
                Write-Warning "Failed to download MinGit: $($_.Exception.Message)"
            }
        }

        if ((Test-Path $MinGitZip) -and (-not (Test-Path $MinGitExtractDir))) {
            Write-Step "Extracting MinGit"
            Expand-Archive -LiteralPath $MinGitZip -DestinationPath $MinGitExtractDir -Force
        }

        if (Test-GitBundleDir $MinGitExtractDir) {
            $SourceDir = $MinGitExtractDir
        }
    }

    if (-not $SourceDir) {
        if (-not $AllowPortableGitFallback) {
            Write-Warning "No usable MinGit bundle was found. Build will continue without bundled Git Bash."
            return
        }

        if (-not (Test-Path $PortableGitExe)) {
            Write-Step "Downloading PortableGit $GitVersion"
            try {
                Invoke-WebRequest -Uri $PortableGitUrl -OutFile $PortableGitExe
            }
            catch {
                Write-Warning "Failed to download PortableGit: $($_.Exception.Message)"
            }
        }

        if ((Test-Path $PortableGitExe) -and (-not (Test-Path $PortableGitExtractDir))) {
            Write-Step "Extracting PortableGit"
            New-Item -ItemType Directory -Force -Path $PortableGitExtractDir | Out-Null
            & $PortableGitExe -y "-o$PortableGitExtractDir" | Out-Null
        }

        if (Test-GitBundleDir $PortableGitExtractDir) {
            $SourceDir = $PortableGitExtractDir
        }
    }

    if (-not $SourceDir) {
        Write-Warning "No usable MinGit/PortableGit bundle was found. Build will continue without bundled Git Bash."
        return
    }

    Write-Step "Copying MinGit bundle into dist"
    $Target = Join-Path $DistDir "portable-git"
    if (Test-Path $Target) {
        Remove-Item -LiteralPath $Target -Recurse -Force
    }
    Copy-Item -Path $SourceDir -Destination $Target -Recurse -Force
}

function Test-GitBundleDir($Directory) {
    if (-not (Test-Path $Directory)) {
        return $false
    }

    $GitCandidates = @(
        (Join-Path $Directory "cmd\git.exe"),
        (Join-Path $Directory "mingw64\bin\git.exe")
    )
    return [bool]($GitCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1)
}

function Find-Iscc() {
    $Command = Get-Command "iscc.exe" -ErrorAction SilentlyContinue
    if ($Command) {
        return $Command.Source
    }

    $Candidates = @(
        "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
        "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
        "$env:ProgramFiles\Inno Setup 6\ISCC.exe"
    )
    foreach ($Candidate in $Candidates) {
        if ($Candidate -and (Test-Path $Candidate)) {
            return $Candidate
        }
    }
    return $null
}

function Ensure-BuildVenv() {
    if (-not (Test-Path $BuildPython)) {
        Write-Step "Creating isolated build venv"
        python -m venv $BuildVenvDir
    }

    Write-Step "Installing runtime build dependencies"
    & $BuildPython -m pip install --upgrade pip
    & $BuildPython -m pip install -r (Join-Path $Root "requirements-runtime.txt") pyinstaller
}

function Copy-Templates() {
    $TemplateSource = Join-Path $Root "packaging\templates"
    if (-not (Test-Path $TemplateSource)) {
        return
    }

    Write-Step "Copying templates into dist"
    $TemplateTarget = Join-Path $DistDir "templates"
    if (Test-Path $TemplateTarget) {
        Remove-Item -LiteralPath $TemplateTarget -Recurse -Force
    }
    Copy-Item -Path $TemplateSource -Destination $TemplateTarget -Recurse -Force
}

Write-Step "Preparing build"
New-Item -ItemType Directory -Force -Path $ReleaseDir | Out-Null

$Version = Get-ChainPeerVersion
Write-Host "Version: $Version"

Ensure-BuildVenv

Write-Step "Building PyInstaller one-folder"
Push-Location $Root
try {
    & $BuildPython -m PyInstaller packaging\pyinstaller\chainpeer.spec --clean --noconfirm
}
finally {
    Pop-Location
}

if (-not (Test-Path (Join-Path $DistDir "chainpeer.exe"))) {
    throw "PyInstaller did not produce dist\chainpeer\chainpeer.exe"
}

Copy-Templates
Copy-PortableGit

Write-Step "Smoke testing executable"
& (Join-Path $DistDir "chainpeer.exe") --version
& (Join-Path $DistDir "chainpeer.exe") --help | Out-Null

if ($SkipInstaller) {
    Write-Host "Skipping installer build."
    Write-Host "One-folder output: $DistDir"
    exit 0
}

$Iscc = Find-Iscc
if (-not $Iscc) {
    Write-Warning "Inno Setup ISCC.exe was not found. Install Inno Setup 6 or rerun with -SkipInstaller."
    Write-Host "One-folder output: $DistDir"
    exit 0
}

Write-Step "Building Inno Setup installer"
$env:CHAINPEER_VERSION = $Version
Push-Location $Root
try {
    & $Iscc packaging\inno\ChainPeerSetup.iss
}
finally {
    Pop-Location
}

$Installer = Join-Path $ReleaseDir "ChainPeerSetup-$Version.exe"
if (Test-Path $Installer) {
    Write-Host ""
    Write-Host "Built installer: $Installer" -ForegroundColor Green
} else {
    throw "Installer was not produced at $Installer"
}
