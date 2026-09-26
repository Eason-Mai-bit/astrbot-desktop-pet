# 🚢 碧蓝航线秘书舰 · 桌面宠物（企业版增强）

> 一个接入 AstrBot 的桌宠客户端 + 配套服务端插件（含 awareness 感知增强）
> 8 位舰娘轮换 · AI 对话 · 桌面感知 · TTS 语音

---

## 📦 仓库结构

```
├── client/                  # 🖥️ 桌宠客户端（自研）
│   ├── main.py              #   主程序（PyQt5）
│   ├── smart_features.py    #   日程/主动陪伴
│   ├── file_handler.py      #   文件处理
│   ├── jp_voice.py          #   日文语音映射
│   ├── remove_bg.py         #   立绘抠图工具
│   ├── requirements.txt
│   ├── enterprise_desktop_pet.spec   # PyInstaller 打包配置
│   └── build_exe.bat        # 一键打包脚本
│
├── plugin/                  # 🔌 服务端插件（基于原版增强）
│   ├── main.py
│   ├── ws_handler.py
│   ├── ws_server.py
│   ├── services/            #   感知引擎/桌面监控/主动对话/视觉分析
│   ├── metadata.yaml
│   ├── LICENSE              #   继承原版 MIT
│   └── README.md
│
└── docs/                    # 📖 文档
```

---

## ⚡ 快速开始

### 前置要求

| 依赖 | 版本 |
|:---|:---|
| Python | 3.10+ |
| AstrBot | 4.0+ |

### 1️⃣ 安装服务端插件

将 `plugin/` 目录整体复制到 AstrBot 插件目录：

```
<AstrBot>/data/plugins/astrbot_plugin_desktop_assistant/
```

重启 AstrBot，在插件管理页确认已加载。

### 2️⃣ 配置客户端

```bash
cd client
pip install -r requirements.txt
```

**准备立绘**（版权原因，需自备）：

```bash
python remove_bg.py 立绘原图.png --output skins/企业.png --model isnet-general-use
```

支持的 8 个立绘文件名：`enterprise.png`、`shoukaku.png`、`newjersey.png`、`hood.png`、`zuikaku.png`、`essex.png`、`taihou.png`、`yorktown2.png`

### 3️⃣ 启动

```bash
python main.py
```

右键菜单 → 设置 → 填入 **API Key**（在 AstrBot 面板创建，勾选 `chat` + `file` 权限）

---

## 🔗 连接模式

| 模式 | 端口 | 说明 |
|:---|:---:|:---|
| **插件模式**（主） | 6190 | 经本仓库 `plugin/` 连接（**支持工具调用 + 桌面感知**） |
| DSH 模式 | 6191 | 连接 DeepSeek Harness |
| 原生模式 | 6185 | AstrBot 原生 API（仅基础对话） |

> ⚠️ **本客户端需配合 `plugin/`（含 awareness 增强）使用**，原版插件不支持 awareness 协议

---

## 🎯 功能

| 功能 | 说明 |
|:---|:---|
| **舰娘轮换** | 按日期自动切换 8 位秘书舰立绘 + 语音 |
| **AI 对话** | 点击弹窗对话，经 AstrBot 接入 LLM |
| **桌面感知** | 🆕 主动观察屏幕，智能搭话 |
| **工具调用** | 查看/分析屏幕、系统信息、执行命令、打开文件 |
| **TTS 语音** | 支持 GPT-SoVITS 语音合成播放 |
| **番茄钟** | 内置工作/休息计时 |
| **透明显示** | 无边框、拖拽、呼吸浮动动画 |

---

## 📜 版权与致谢

### 本仓库

- **客户端**（`client/`）：自研，MIT
- **插件**（`plugin/`）：基于 [muyouzhi6/astrbot_plugin_desktop_assistant](https://github.com/muyouzhi6/astrbot_plugin_desktop_assistant)（MIT）修改增强
  - 原版版权：Copyright (c) 2024 muyouzhi6
  - 增强内容：awareness 感知协议扩展、screenshot 处理优化、逻辑健壮性改进
  - **依照 MIT 协议保留原版权声明**（见 `plugin/LICENSE`）

### 资源声明

- **舰娘立绘/语音**：版权归《碧蓝航线》原作者所有，**本仓库不附带**，请自行准备
- **抠图模型**：`isnet-general-use`（首次运行自动下载约 170MB）

---

## ⚠️ 免责声明

1. 本项目仅供学习交流，请勿用于商业用途
2. 立绘/语音资源请自行获取并遵守相关版权规定
3. **请勿在仓库中提交任何 API Key、账号密码等敏感信息**

---

## 📄 License

MIT License（详见 `LICENSE`）
