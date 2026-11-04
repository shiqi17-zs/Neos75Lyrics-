# 构建单文件 exe（需要 Python 3.11+ 与 requirements.txt 里的依赖）
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot\src

python -m pip install --upgrade pyinstaller

python -m PyInstaller --noconfirm --onefile --noconsole `
  --name Neos75Lyrics `
  --icon ..\assets\fish.ico `
  --add-data "..\assets;assets" `
  --collect-submodules winsdk `
  --collect-all hid --collect-all pystray --collect-all pycaw --collect-all psutil `
  --hidden-import PIL --hidden-import PIL.ImageTk `
  --hidden-import usb --hidden-import libusb_package `
  --hidden-import logsetup --hidden-import monitor --hidden-import scenes `
  Neos75Lyrics.py

Write-Host "完成：src\dist\Neos75Lyrics.exe"