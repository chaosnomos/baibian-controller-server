#!/bin/bash
# XControl Server macOS 打包脚本
# 需要在 macOS 系统上运行
#
# 使用方法:
#   chmod +x build_macos.sh
#   ./build_macos.sh

set -e

echo "========================================"
echo "  XControl Server macOS 打包工具"
echo "========================================"
echo ""

# 检查 Python
if ! command -v python3 &> /dev/null; then
    echo "[错误] 未检测到 Python3，请先安装 Python 3.9+"
    echo "下载地址: https://www.python.org/downloads/"
    exit 1
fi

# 安装依赖
echo "[1/4] 安装项目依赖..."
pip3 install -r requirements.txt

# 安装 PyInstaller
echo "[2/4] 安装 PyInstaller..."
pip3 install pyinstaller

# 清理旧文件
echo "[3/4] 清理旧文件..."
rm -rf build dist

# 打包
echo "[4/4] 正在打包，请稍候..."
python3 -m PyInstaller \
    --name XControl \
    --windowed \
    --onefile \
    --hidden-import pynput.mouse._darwin \
    --hidden-import pynput.keyboard._darwin \
    --hidden-import pynput._util.darwin \
    --hidden-import PIL._tkinter_finder \
    --exclude-module matplotlib \
    --exclude-module numpy \
    --exclude-module pytest \
    --exclude-module unittest \
    server.pyw

echo ""
echo "========================================"
echo "  打包成功!"
echo "========================================"
echo "生成的文件: dist/XControl.app"
echo ""

# 创建 zip 包
echo "正在创建 zip 包..."
cd dist
zip -r ../downloads/XControl_mac.zip XControl.app
cd ..

echo "zip 包已生成: downloads/XControl_mac.zip"
echo ""
echo "注意: macOS 版本需要在此 Mac 上运行此脚本生成"
