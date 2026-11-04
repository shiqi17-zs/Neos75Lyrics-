# 一键发布到 GitHub
# 前置：已安装 Git（https://git-scm.com/download/win），并已登录 GitHub
#
# 用法：
#   1) 先在 GitHub 网页上建一个空仓库（不要勾选 README/.gitignore）
#   2) 在下面填上仓库地址，例如 https://github.com/你的用户名/neos75-screen-helper.git
#   3) 右键本文件 → 使用 PowerShell 运行

$Remote = "https://github.com/<你的用户名>/neos75-screen-helper.git"
$Branch = "main"

Set-Location $PSScriptRoot

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Write-Host "没有找到 git，请先安装：https://git-scm.com/download/win" -ForegroundColor Red
    exit 1
}

if (-not (Test-Path .git)) {
    git init
    git branch -M $Branch
}

git add .
git commit -m "feat: Neos75 Screen Helper 0.0.2 (lyrics / VALORANT / monitor / skins)"

git remote remove origin 2>$null
git remote add origin $Remote
git push -u origin $Branch

Write-Host ""
Write-Host "推完了。到 GitHub 仓库页 → Releases → Draft a new release，"
Write-Host "tag 填 v0.0.2，把打包好的 Neos75Lyrics.exe 作为附件传上去。"