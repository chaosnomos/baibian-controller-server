@echo off
chcp 65001 >nul
title TPad Server 打包工具

echo ========================================
echo   TPad Server Windows 打包工具
echo ========================================
echo.

REM 检查 Python 环境
python --version >nul 2>&1
if errorlevel 1 (
    echo [错误] 未检测到 Python，请先安装 Python 3.8+
    echo 下载地址: https://www.python.org/downloads/
    pause
    exit /b 1
)

REM 安装依赖
echo [1/4] 安装项目依赖...
pip install -r requirements.txt
if errorlevel 1 (
    echo [错误] 依赖安装失败
    pause
    exit /b 1
)

REM 安装 PyInstaller
echo [2/4] 安装 PyInstaller...
pip install pyinstaller
if errorlevel 1 (
    echo [错误] PyInstaller 安装失败
    pause
    exit /b 1
)

REM 清理旧文件
echo [3/4] 清理旧文件...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist

REM 打包
echo [4/4] 正在打包，请稍候...
python -m PyInstaller TPadServer.spec --noconfirm
if errorlevel 1 (
    echo [错误] 打包失败
    pause
    exit /b 1
)

echo.
echo ========================================
echo   打包成功!
echo ========================================
echo 生成的文件: dist\BaibianController-Server.exe
echo.

REM 检查 Inno Setup 是否安装
set INNO_SETUP_PATH=
if exist "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" (
    set INNO_SETUP_PATH=C:\Program Files (x86)\Inno Setup 6\ISCC.exe
) else if exist "C:\Program Files\Inno Setup 6\ISCC.exe" (
    set INNO_SETUP_PATH=C:\Program Files\Inno Setup 6\ISCC.exe
) else if exist "C:\Program Files (x86)\Inno Setup 5\ISCC.exe" (
    set INNO_SETUP_PATH=C:\Program Files (x86)\Inno Setup 5\ISCC.exe
)

if defined INNO_SETUP_PATH (
    echo 检测到 Inno Setup，是否生成安装包？ [Y/N]
    set /p choice=
    if /i "%choice%"=="Y" (
        echo 正在生成安装包...
        "%INNO_SETUP_PATH%" installer.iss
        echo.
        echo 安装包已生成: dist\TPadServer_Setup.exe
    )
) else (
    echo [提示] 未检测到 Inno Setup，跳过安装包生成
    echo 如需生成安装包，请安装 Inno Setup 6:
    echo https://jrsoftware.org/isdl.php
)

echo.
pause
