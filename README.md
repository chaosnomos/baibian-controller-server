# 百变控制器服务端（Baibian Controller Server）

手机变电脑遥控器的服务端程序。配合微信小程序 / HarmonyOS 应用「百变控制器」使用，让你的手机通过 WiFi 或蓝牙控制电脑的鼠标、键盘、触控板、游戏手柄等。

## 安全说明

> 我们理解用户对陌生 exe 的顾虑，因此将全部源码公开，你可以自行审查或编译。

- 本程序仅调用 **Windows API**（`SendInput` / `mouse_event` / `keybd_event`）模拟鼠标键盘输入
- **不收集任何用户数据**，不上传任何信息到任何服务器
- **仅局域网通信**（WebSocket + 蓝牙 BLE），不联网
- 全部源码公开，可自行编译
- 配对时使用 4 位随机连接码，防止未授权设备连接
- 支持绑定用户：已登记的手机使用固定连接码，无需每次输入动态码

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
| 👥 绑定用户 | 管理已绑定手机，固定连接码免重复输入 |
| 🔽 系统托盘 | 最小化到后台运行，右下角托盘图标控制 |

## 技术原理

| 功能 | 实现方式 |
|------|---------|
| 鼠标移动 | Windows API: `SetCursorPos` / `pynput` |
| 鼠标点击 | Windows API: `SendInput` / `mouse_event` |
| 键盘输入 | Windows API: `SendInput` / `keybd_event` |
| WiFi 通信 | WebSocket（`websockets` 库） |
| 蓝牙通信 | Windows BLE GATT（`winrt` / `bleak`） |
| 系统托盘 | `pystray` |
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

2. 双击运行 `打包.bat`，脚本会自动完成：
   - 安装项目依赖
   - 安装 PyInstaller
   - 打包为单个 exe 文件
   - 复制到 `downloads/` 目录

3. 编译完成后，exe 文件位于 `downloads/` 目录下：
   ```
   downloads/
   └── BaibianController-Server.exe
   ```

### 方式二：手动编译（Windows）

```bash
# 1. 安装依赖
pip install -r requirements.txt
pip install pyinstaller

# 2. 打包
python -m PyInstaller TPadServer.spec --noconfirm
```

生成的 exe 在 `dist/BaibianController-Server.exe`。

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

编译完成后，双击 `downloads/BaibianController-Server.exe` 即可运行。

程序启动后会显示：
- **IP 地址**：电脑在局域网中的 IP
- **端口**：默认 8765
- **连接码**：4 位随机数字，用于小程序配对

## 绑定用户

在「刷新连接码」旁点击「👥 管理用户」可打开绑定用户管理：
- 为常用手机分配固定 4 位连接码
- 绑定用户连接时无需输入动态连接码
- 非绑定用户连接时，可点击「💾 保存当前连接」一键登记

## 系统托盘

点击「🔽 后台运行」按钮可将窗口最小化到系统托盘：
- 右下角显示紫色「B」托盘图标
- 双击或右键「显示主窗口」恢复界面
- 右键「退出程序」完全关闭

## 预编译版本下载

不想自己编译的用户，可以直接下载预编译版本：

- [下载](https://github.com/chaosnomos/baibian-controller-server/releases)

下载后可用以下命令验证文件完整性（防篡改）：
```powershell
Get-FileHash .\BaibianController-Server.exe -Algorithm SHA256
```

**SHA256（V1.4.1）：**
```
E48327E6E34C44A9CB97E6DC9AD34AFF3C7B1DC6E7D286F7D6CD4217B26792B2
```

## 生成安装包（可选）

如果需要生成 Windows 安装包（带卸载程序、桌面快捷方式等）：

1. 先完成上述编译步骤，确保 `dist/BaibianController-Server.exe` 存在
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
├── build.bat              # Windows 打包脚本（含 Inno Setup）
├── 打包.bat               # Windows 一键打包脚本（复制到 downloads）
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
