@echo off
chcp 65001 >nul
title TPad Server 打包工具

echo ========================================
echo   TPad Server 打包工具
echo ========================================
echo.

REM 切换到脚本所在目录
cd /d "%~dp0"

REM 检查 Python 环境
echo [1/5] 检查 Python 环境...
python --version >nul 2>&1
if errorlevel 1 (
    echo [错误] 未检测到 Python，请先安装 Python 3.8+
    pause
    exit /b 1
)
echo.

REM 安装项目依赖
echo [2/5] 安装项目依赖...
pip install -r requirements.txt
if errorlevel 1 (
    echo [错误] 依赖安装失败
    pause
    exit /b 1
)
echo.

REM 安装 PyInstaller
echo [3/5] 安装 PyInstaller...
pip install pyinstaller
if errorlevel 1 (
    echo [错误] PyInstaller 安装失败
    pause
    exit /b 1
)
echo.

REM 清理旧文件
echo [4/5] 清理旧的打包文件...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
echo   已清理
echo.

REM 打包
echo [5/5] 正在打包，请稍候...
python -m PyInstaller TPadServer.spec --noconfirm --clean
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
if exist "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" set INNO_SETUP_PATH=C:\Program Files (x86)\Inno Setup 6\ISCC.exe
if exist "C:\Program Files\Inno Setup 6\ISCC.exe" set INNO_SETUP_PATH=C:\Program Files\Inno Setup 6\ISCC.exe

if not "%INNO_SETUP_PATH%"=="" (
    echo 检测到 Inno Setup，正在生成安装包...
    "%INNO_SETUP_PATH%" installer.iss
    if errorlevel 1 (
        echo [警告] 安装包生成失败，但 exe 已打包成功
    ) else (
        echo 安装包已生成: dist\TPadServer_Setup.exe
    )
) else (
    echo 提示: 安装 Inno Setup 6 后可自动生成安装包
    echo 下载地址: https://jrsoftware.org/isdl.php
)

echo.
pause
