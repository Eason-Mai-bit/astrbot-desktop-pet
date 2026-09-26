@echo off
setlocal
cd /d %~dp0

REM 需要装有 PyQt5 的 Python 环境（本机为 conda base：D:\software\Anaconda3-2025.12-2-Windows-x86_64）
REM 用 spec 构建（onedir 目录式）：自动收集 skins/voices 等资源，且无需运行时解压，
REM 避免本机 Defender 实时扫描卡死 onefile 大体积解压。

python -m PyInstaller --noconfirm --clean enterprise_desktop_pet.spec

echo.
echo 打包完成：dist\enterprise_desktop_pet\enterprise_desktop_pet.exe
endlocal
