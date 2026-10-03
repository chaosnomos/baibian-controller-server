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
echo [1/6] 检查 Python 环境...
python --version >nul 2>&1
if errorlevel 1 (
    echo [错误] 未检测到 Python，请先安装 Python 3.8+
    echo 下载地址: https://www.python.org/downloads/
    pause
    exit /b 1
)
for /f "tokens=2" %%a in ('python --version 2^>^&1') do set PYVER=%%a
echo   Python 版本: %PYVER%
echo.

REM 安装项目依赖
echo [2/6] 安装项目依赖...
pip install -r requirements.txt
if errorlevel 1 (
    echo [错误] 依赖安装失败
    pause
    exit /b 1
)
echo.

REM 安装 PyInstaller
echo [3/6] 检查 PyInstaller...
pip show pyinstaller >nul 2>&1
if errorlevel 1 (
    echo   正在安装 PyInstaller...
    pip install pyinstaller
    if errorlevel 1 (
        echo [错误] PyInstaller 安装失败
        pause
        exit /b 1
    )
) else (
    echo   已安装 PyInstaller
)
echo.

REM 清理旧文件
echo [4/6] 清理旧的打包文件...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
if exist downloads\BaibianController-Server.exe del /q downloads\BaibianController-Server.exe
echo   已清理
echo.

REM 打包
echo [5/6] 正在打包，请稍候（首次打包可能需要 1-3 分钟）...
python -m PyInstaller TPadServer.spec --noconfirm --clean
if errorlevel 1 (
    echo [错误] 打包失败
    echo.
    echo 排查方法:
    echo   1. 确保所有依赖已安装
    echo   2. 查看 build\TPadServer\warn-TPadServer.txt
    echo   3. 尝试以管理员身份运行
    pause
    exit /b 1
)
echo.

REM 复制到 downloads 目录
echo [6/6] 复制输出文件...
if not exist downloads mkdir downloads
copy /y dist\BaibianController-Server.exe downloads\BaibianController-Server.exe >nul
if errorlevel 1 (
    echo [错误] 复制失败
    pause
    exit /b 1
)
echo   已复制到 downloads\BaibianController-Server.exe
echo.
echo ========================================
echo   打包成功!
echo ========================================
echo.
echo 输出文件: downloads\BaibianController-Server.exe
echo.
echo 使用方法:
echo   双击 BaibianController-Server.exe 启动（无 CMD 窗口）
echo.
echo 以后打包只需双击本脚本即可
echo.
pause
