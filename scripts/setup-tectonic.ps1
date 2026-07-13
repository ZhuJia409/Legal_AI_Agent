param(
    [string]$Version = "0.15.0",
    [string]$DownloadUrl = "https://github.com/tectonic-typesetting/tectonic/releases/download/tectonic%400.15.0/tectonic-0.15.0-x86_64-pc-windows-msvc.zip",
    [string]$ExpectedSha256 = "1D6BB76F049C8A3774F6E9D66E4B04E1A8C3DCB37527B6B41B7E894328E7BF29"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if ($PSBoundParameters.ContainsKey("Version") -and -not $PSBoundParameters.ContainsKey("DownloadUrl")) {
    $DownloadUrl = "https://github.com/tectonic-typesetting/tectonic/releases/download/tectonic%40$Version/tectonic-$Version-x86_64-pc-windows-msvc.zip"
}
if ($Version -ne "0.15.0" -and -not $PSBoundParameters.ContainsKey("ExpectedSha256")) {
    throw "覆盖 Tectonic 版本时必须同时提供该发布包的 ExpectedSha256。"
}

$repositoryRoot = Split-Path -Parent $PSScriptRoot
$targetDirectory = Join-Path $repositoryRoot ".tools\tectonic"
$targetExecutable = Join-Path $targetDirectory "tectonic.exe"
$cacheDirectory = Join-Path $targetDirectory "cache"
$stagedExecutable = Join-Path $targetDirectory ("tectonic.exe.staged-" + [guid]::NewGuid().ToString("N"))
$backupExecutable = Join-Path $targetDirectory ("tectonic.exe.backup-" + [guid]::NewGuid().ToString("N"))
$previousCacheDirectory = [System.Environment]::GetEnvironmentVariable("TECTONIC_CACHE_DIR", "Process")
$temporaryRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("legal-ai-tectonic-" + [guid]::NewGuid().ToString("N"))
$archivePath = Join-Path $temporaryRoot "tectonic.zip"
$extractDirectory = Join-Path $temporaryRoot "extract"
$smokeDirectory = Join-Path $temporaryRoot "smoke"

try {
    New-Item -ItemType Directory -Path $targetDirectory -Force | Out-Null
    New-Item -ItemType Directory -Path $cacheDirectory -Force | Out-Null
    # 安装与运行时共用仓库级缓存，避免依赖执行服务所使用的 Windows 账号。
    $env:TECTONIC_CACHE_DIR = $cacheDirectory
    New-Item -ItemType Directory -Path $extractDirectory -Force | Out-Null
    New-Item -ItemType Directory -Path $smokeDirectory -Force | Out-Null

    Write-Host "正在下载 Tectonic $Version ..."
    Invoke-WebRequest -Uri $DownloadUrl -OutFile $archivePath -UseBasicParsing

    # 发布包必须先通过固定摘要校验，禁止把未验证的二进制写入仓库工具目录。
    $actualSha256 = (Get-FileHash -LiteralPath $archivePath -Algorithm SHA256).Hash.ToUpperInvariant()
    if ($actualSha256 -ne $ExpectedSha256.ToUpperInvariant()) {
        throw "Tectonic 发布包 SHA-256 校验失败。期望 $ExpectedSha256，实际 $actualSha256。"
    }

    Expand-Archive -LiteralPath $archivePath -DestinationPath $extractDirectory -Force
    $downloadedExecutable = Get-ChildItem -LiteralPath $extractDirectory -Filter "tectonic.exe" -File -Recurse | Select-Object -First 1
    if ($null -eq $downloadedExecutable) {
        throw "Tectonic 发布包中未找到 tectonic.exe。"
    }

    # 冒烟文档覆盖当前报告模板使用的宏包，并通过 fontset=fandol 验证 Fandol 中文字体。
    $smokeSource = @'
\documentclass[UTF8,a4paper,11pt,fontset=fandol]{ctexart}
\usepackage[a4paper,margin=2.3cm,headheight=16pt,footskip=1.2cm]{geometry}
\usepackage{array}
\usepackage{enumitem}
\usepackage{fancyhdr}
\usepackage{longtable}
\usepackage[table]{xcolor}
\usepackage{hyperref}
\definecolor{LegalGreen}{HTML}{174C3C}
\pagestyle{fancy}
\fancyhf{}
\fancyhead[L]{\color{LegalGreen}合同审查报告}
\begin{document}
\section*{Tectonic 中文冒烟测试}
Fandol 字体与合同审查报告宏包缓存预热成功。
{\Huge\bfseries 合同审查报告封面大标题}\par
{\Large 合同名称与报告状态}\par
{\small 页眉、页脚与免责声明小字号}\par
{\scriptsize $A_1 + B^2$ 数学字体与最小字号资源}\par
普通字号数学资源：$M_1 + N^2$\par
\begin{longtable}{p{3cm}p{8cm}}
状态 & 中文 PDF 可正常生成 \\
\end{longtable}
\begin{itemize}[leftmargin=1.6em]
  \item 法律专业人士复核提示
\end{itemize}
\href{https://example.com}{链接宏包测试}
\end{document}
'@
    $smokeTexPath = Join-Path $smokeDirectory "smoke.tex"
    Set-Content -LiteralPath $smokeTexPath -Value $smokeSource -Encoding utf8

    & $downloadedExecutable.FullName --keep-logs --outdir $smokeDirectory $smokeTexPath
    if ($LASTEXITCODE -ne 0) {
        throw "Tectonic 中文冒烟编译失败，退出码 $LASTEXITCODE。"
    }

    $smokePdfPath = Join-Path $smokeDirectory "smoke.pdf"
    if (-not (Test-Path -LiteralPath $smokePdfPath -PathType Leaf)) {
        throw "Tectonic 中文冒烟预热未生成 PDF。"
    }

    # 删除首次联网编译的产物，再以只读缓存模式复编译，证明运行时不需要网络补包。
    Remove-Item -LiteralPath $smokePdfPath -Force
    foreach ($auxiliaryName in @("smoke.log", "smoke.aux", "smoke.xdv")) {
        $auxiliaryPath = Join-Path $smokeDirectory $auxiliaryName
        if (Test-Path -LiteralPath $auxiliaryPath) {
            Remove-Item -LiteralPath $auxiliaryPath -Force
        }
    }

    & $downloadedExecutable.FullName --only-cached --keep-logs --outdir $smokeDirectory $smokeTexPath
    if ($LASTEXITCODE -ne 0) {
        throw "Tectonic 中文冒烟离线复编译失败，退出码 $LASTEXITCODE；请检查预热缓存是否完整。"
    }

    if (-not (Test-Path -LiteralPath $smokePdfPath -PathType Leaf)) {
        throw "Tectonic 中文冒烟离线复编译未生成 PDF。"
    }
    $smokeBytes = [System.IO.File]::ReadAllBytes($smokePdfPath)
    if ($smokeBytes.Length -lt 5 -or [System.Text.Encoding]::ASCII.GetString($smokeBytes, 0, 5) -ne "%PDF-") {
        throw "Tectonic 中文冒烟编译输出缺少有效的 %PDF- 文件头。"
    }

    # 新二进制先写入目标同目录并核验，再通过同卷原子操作切换，失败时旧版本保持不变。
    Copy-Item -LiteralPath $downloadedExecutable.FullName -Destination $stagedExecutable -Force
    $sourceSha256 = (Get-FileHash -LiteralPath $downloadedExecutable.FullName -Algorithm SHA256).Hash.ToUpperInvariant()
    $stagedSha256 = (Get-FileHash -LiteralPath $stagedExecutable -Algorithm SHA256).Hash.ToUpperInvariant()
    if ($sourceSha256 -ne $stagedSha256) {
        throw "Tectonic 暂存文件校验失败，拒绝替换现有编译器。"
    }

    if (Test-Path -LiteralPath $targetExecutable -PathType Leaf) {
        [System.IO.File]::Replace($stagedExecutable, $targetExecutable, $backupExecutable, $true)
        Remove-Item -LiteralPath $backupExecutable -Force -ErrorAction SilentlyContinue
    }
    else {
        [System.IO.File]::Move($stagedExecutable, $targetExecutable)
    }
    Write-Host "Tectonic 已安装到 $targetExecutable，并完成中文模板缓存预热。"
}
finally {
    # 无论成功失败都恢复调用方环境，并删除暂存二进制与下载、编译临时文件。
    if ($null -eq $previousCacheDirectory) {
        Remove-Item Env:TECTONIC_CACHE_DIR -ErrorAction SilentlyContinue
    }
    else {
        $env:TECTONIC_CACHE_DIR = $previousCacheDirectory
    }
    if (Test-Path -LiteralPath $stagedExecutable) {
        Remove-Item -LiteralPath $stagedExecutable -Force
    }
    if (Test-Path -LiteralPath $backupExecutable) {
        Remove-Item -LiteralPath $backupExecutable -Force
    }
    if (Test-Path -LiteralPath $temporaryRoot) {
        Remove-Item -LiteralPath $temporaryRoot -Recurse -Force
    }
}
