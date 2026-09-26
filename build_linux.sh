#!/bin/bash
# XControl Server Linux 打包脚本
# 需要在 Linux 系统上运行
#
# 使用方法:
#   chmod +x build_linux.sh
#   ./build_linux.sh

set -e

echo "========================================"
echo "  XControl Server Linux 打包工具"
echo "========================================"
echo ""

# 检查 Python
if ! command -v python3 &> /dev/null; then
    echo "[错误] 未检测到 Python3，请先安装 Python 3.9+"
    echo "Ubuntu/Debian: sudo apt install python3 python3-pip python3-tk"
    exit 1
fi

# 检查 tkinter
python3 -c "import tkinter" 2>/dev/null || {
    echo "[错误] 未检测到 tkinter，请安装:"
    echo "Ubuntu/Debian: sudo apt install python3-tk"
    exit 1
}

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
    --onefile \
    --hidden-import pynput.mouse._xorg \
    --hidden-import pynput.keyboard._xorg \
    --hidden-import pynput._util.xorg_keysyms \
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
echo "生成的文件: dist/XControl"
echo ""

# 创建 tar.gz 包
mkdir -p downloads
echo "正在创建 tar.gz 包..."
tar -czf downloads/XControl_linux.tar.gz -C dist XControl

echo "tar.gz 包已生成: downloads/XControl_linux.tar.gz"
echo ""
echo "注意: Linux 版本需要在此 Linux 系统上运行此脚本生成"
echo "运行前需要安装: sudo apt install python3-tk"
