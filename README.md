# 百变控制器服务端（Baibian Controller Server）

手机变电脑遥控器的服务端程序。配合微信小程序 / HarmonyOS 应用「百变控制器」使用，让你的手机通过 WiFi 或蓝牙控制电脑的鼠标、键盘、触控板、游戏手柄等。

## 安全说明

> 我们理解用户对陌生 exe 的顾虑，因此将全部源码公开，你可以自行审查或编译。

- 本程序仅调用 **Windows API**（`SendInput` / `mouse_event` / `keybd_event`）模拟鼠标键盘输入
- **不收集任何用户数据**，不上传任何信息到任何服务器
- **仅局域网通信**（WebSocket + 蓝牙 BLE），不联网
- 全部源码公开，可自行编译
- 配对时使用 4 位随机连接码，防止未授权设备连接

## 功能特性

| 功能 | 说明 |
|------|------|
| 🖱️ 鼠标控制 | 移动、点击、滚轮、双鼠标（宝剑光标）模式 |
| 📱 触控板 | 单指滑动、双指滚动、左右键 |
| ⌨️ 键盘输入 | 全键盘按键、组合键 |
| 🎮 游戏手柄 | 摇杆、按键映射 |
| 🪄 变身棒 | 上传变身图片，远程显示特效 |
| 🔴 远程关机 | 一键关机 / 重启 |
| 📶 WiFi 连接 | 同一局域网下通过 WebSocket 连接 |
| 📡 蓝牙连接 | 通过 BLE GATT 服务连接 |

## 技术原理

| 功能 | 实现方式 |
|------|---------|
| 鼠标移动 | Windows API: `SetCursorPos` / `pynput` |
| 鼠标点击 | Windows API: `SendInput` / `mouse_event` |
| 键盘输入 | Windows API: `SendInput` / `keybd_event` |
| WiFi 通信 | WebSocket（`websockets` 库） |
| 蓝牙通信 | Windows BLE GATT（`winrt` / `bleak`） |
| 图形界面 | `tkinter` |
| 图片处理 | `Pillow` |

## 环境要求

- **操作系统**：Windows 10/11（主要支持）、Linux、macOS
- **Python**：3.8 或更高版本
- **pip**：最新版

## 自行编译

### 方式一：Windows 一键打包（推荐）

1. 克隆仓库
   ```bash
   git clone https://github.com/chaosnomos/baibian-controller-server.git
   cd baibian-controller-server
   ```

2. 双击运行 `build.bat`，脚本会自动完成：
   - 安装项目依赖
   - 安装 PyInstaller
   - 打包为单个 exe 文件
   - （可选）生成 Inno Setup 安装包

3. 编译完成后，exe 文件位于 `dist/` 目录下：
   ```
   dist/
   └── TPadServer.exe
   ```

### 方式二：手动编译（Windows）

```bash
# 1. 安装依赖
pip install -r requirements.txt
pip install pyinstaller

# 2. 打包
pyinstaller TPadServer.spec --noconfirm
```

生成的 exe 在 `dist/TPadServer.exe`。

### 方式三：Linux

```bash
# 1. 安装系统依赖（Ubuntu/Debian）
sudo apt install python3 python3-pip python3-tk

# 2. 编译
chmod +x build_linux.sh
./build_linux.sh
```

生成的文件在 `dist/XControl`。

### 方式四：macOS

```bash
# 1. 编译
chmod +x build_macos.sh
./build_macos.sh
```

生成的文件在 `dist/XControl.app`。

## 运行

编译完成后，双击 `dist/TPadServer.exe` 即可运行。

程序启动后会显示：
- **IP 地址**：电脑在局域网中的 IP
- **端口**：默认 8765
- **连接码**：4 位随机数字，用于小程序配对

## 预编译版本下载

不想自己编译的用户，可以直接下载预编译版本：

- [V1.3.1 下载](https://github.com/chaosnomos/baibian-controller-server/releases/tag/v1.3.1)

下载后可用以下命令验证文件完整性（防篡改）：
```powershell
Get-FileHash .\TPadServer.exe -Algorithm SHA256
```

**SHA256（V1.3.1）：**
```
B67F64D86011982506682A84CB4891FEED6CE23EF2EEEA97A96AB902E1AE5129
```

## 生成安装包（可选）

如果需要生成 Windows 安装包（带卸载程序、桌面快捷方式等）：

1. 先完成上述编译步骤，确保 `dist/TPadServer.exe` 存在
2. 安装 [Inno Setup 6](https://jrsoftware.org/isdl.php)
3. 运行：
   ```bash
   ISCC.exe installer.iss
   ```
4. 安装包生成在 `dist/TPadServer_Setup.exe`

## 目录结构

```
baibian-controller-server/
├── server.py              # 主服务端程序（WebSocket + GUI）
├── ble_client.py          # 蓝牙 BLE 外设模块
├── server.pyw             # 无 CMD 窗口启动入口
├── requirements.txt       # Python 依赖列表
├── TPadServer.spec        # PyInstaller 打包配置
├── build.bat              # Windows 一键打包脚本
├── build_linux.sh         # Linux 打包脚本
├── build_macos.sh         # macOS 打包脚本
├── installer.iss          # Inno Setup 安装包脚本
├── 宝剑1.jpg              # 双鼠标宝剑光标图片资源
├── CHANGELOG.md           # 版本更新记录
├── README.md              # 本文件
└── LICENSE                # MIT 开源协议
```

## License

MIT License — 详见 [LICENSE](LICENSE)
