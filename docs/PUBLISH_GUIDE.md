# 🚀 发布操作指引

> 发布目录：`D:\entreprise_pet_release`
> 状态：✅ 已完成脱敏 + 结构组织 + 文档编写
> 待办：替换占位符 → 推 GitHub → 发布

---

## 📋 当前完成度

| # | 项目 | 状态 |
|:---:|:---|:---:|
| 1 | 仓库结构（client/ + plugin/ + docs/） | ✅ |
| 2 | 客户端脱敏（API Key + 硬编码路径） | ✅ |
| 3 | 插件脱敏（无 <user> 残留 / 无 session） | ✅ |
| 4 | 清除 __pycache__ / .pyc | ✅ |
| 5 | 根 README.md（一站式说明） | ✅ |
| 6 | 根 LICENSE（MIT 双版权） | ✅ |
| 7 | plugin/metadata.yaml（双署名） | ✅ |
| 8 | .gitignore（隐私排除） | ✅ |
| 9 | 客户端 requirements.txt（补全） | ✅ |
| 10 | 发布指引（本文件） | ✅ |

**统计**：26 个文件，0.63 MB（不含立绘/语音）

---

## ⚠️ 发布前必做：替换占位符

**3 处占位符**需要替换成你的真实信息：

| # | 文件 | 占位符 | 替换为 |
|:---:|:---|:---|:---|
| 1 | `plugin/metadata.yaml` | `Eason-Mai-bit` / `astrbot-desktop-pet` | 你的 GitHub 用户名 / 仓库名 |
| 2 | `LICENSE` | `Eason-Mai-bit` | 你的名字/ID |
| 3 | `README.md` | （检查有无占位符） | — |

---

## 📤 发布步骤

### Step 1：本地 Git 初始化

```powershell
cd D:\entreprise_pet_release
git init
git add .
git commit -m "feat: 碧蓝航线秘书舰桌宠（客户端 + 企业版插件）v1.0"
```

> ✅ `.gitignore` 已排除：API Key、立绘、语音、打包产物、缓存

### Step 2：创建 GitHub 仓库

1. 登录 GitHub → New repository
2. 仓库名建议：`astrbot-desktop-pet-belfast`（或你喜欢的名字）
3. **不要**勾选 "Add README"（本地已有）
4. 创建后复制仓库地址

### Step 3：推送

```powershell
git remote add origin https://github.com/Eason-Mai-bit/astrbot-desktop-pet.git
git branch -M main
git push -u origin main
```

### Step 4：发布 Release（资源分发）

由于**立绘/语音不放入仓库**（版权+体积），建议：

**选项 A：用户自备**（推荐）
- README 已说明获取方式
- 用户自行跑 `remove_bg.py` 抠图

**选项 B：Release 附件**
- 把 `skins/`（46MB）打包为 zip，作为 Release 附件
- ⚠️ 注意版权（碧蓝航线立绘）

**选项 C：打包 exe**
```powershell
cd client
python -m PyInstaller --noconfirm --clean enterprise_desktop_pet.spec
# 产物：dist\enterprise_desktop_pet\enterprise_desktop_pet.exe
```
将 dist 目录打包上传到 Release

---

## 🔌 插件市场（可选）

如果要让插件**也进 AstrBot 市场**：

1. Fork `AstrBotDevs/AstrBot_Plugins_Collection`
2. 阅读其 CONTRIBUTING.md
3. 添加插件条目到 `plugin_cache_original.json`
4. 提 PR

> 📌 建议先只发客户端，插件等社区反馈后再决定

---

## ✅ 发布前自检清单

- [ ] 3 处占位符已替换
- [ ] `git status` 确认无 `pet_config.json` / `*.onnx` / `skins/` / `voices/`
- [ ] `plugin/metadata.yaml` 的 `repo` 字段已填
- [ ] README 中的版权声明完整（原版 MIT + 立绘版权免责）
- [ ] 本地测试：`python client/main.py` 能启动
- [ ] 本地测试：插件复制到 AstrBot 后能加载

---

## 📌 重要提醒

| 事项 | 说明 |
|:---|:---|
| 🔴 **切勿提交真实 API Key** | .gitignore 已防，但请再确认 |
| 🔴 **立绘版权** | 碧蓝航线素材版权归原作者，切勿声称为己有 |
| 🟠 **插件署名** | 已在 metadata + README 双重标注原版作者 |
| 🟠 **MIT 合规** | 保留原版权声明 ✅（LICENSE 已含 muyouzhi6） |

---

## 🗂️ 参考：原文件位置

| 项目 | 原路径 |
|:---|:---|
| 客户端 | `<原项目目录>\desktop_pet\` |
| 插件 | `<用户目录>\.astrbot\data\plugins\astrbot_plugin_desktop_assistant\` |
| 发布目录 | `D:\entreprise_pet_release\` |

> 💾 原文件已备份（`*_pre_release_bak_20260926_175400`）
