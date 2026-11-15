# 游戏包（Game Pack）首版 + 终末地接入 - 交接

> 时间：2026-11-14
> 性质：**新功能落地，已构建通过**。目标：让非库洛游戏进 Arietta，但**仓库里不出现任何具体游戏的代码**。
> 前置阅读：《定位-插件化借鉴Collapse-交接.md》（插件化定位与三阶段路线）。本文是该路线的落地第一刀。

## 一、结论：形态从「插件」改成「游戏包」

用户要的不是代码插件，是「在 Arietta 里加一个游戏」。因此边界从**进程内程序集**换成**数据目录**：

```
<数据目录>/games/<id>/
  game.json     描述（名/图标/exe/扫盘特征/启动方式/能力）
  icon.png      图标（BitmapImage 从字节流加载，不走 ms-appx）
  provider.py   （预留）外部数据源进程，抽卡用；本轮未接
```

数据目录 = `AppConfig.LocalFolder`（开发时 `src/Arietta/`，发布版 `data/`），两者都在 `.gitignore` 内，**包永远不进仓库**。

宿主侧只加通用能力：包加载器 / 设置页 / 启动器。全部以 `GamePack` 抽象工作，grep 不到 `endfield`。

## 二、本轮落地的文件

| 文件 | 作用 |
| --- | --- |
| `src/Core/GamePack.cs` | 包模型 + `GamePack.Load()`（JSON 容错：允许注释、尾逗号；id 校验 `[a-z0-9-]`） |
| `src/Features/GamePacks/GamePackService.cs` | 扫描 `games/*/game.json`、exe 解析与持久化（`PackExePath_<id>`）、**多盘并行扫盘**（深度 ≤4，命中即取消其余） |
| `src/Features/GamePacks/DecoyParentLauncher.cs` | 父进程伪造启动（见第四节） |
| `src/Features/GamePacks/GamePackLauncher.cs` | 普通启动 / 提权自重启（`launchpack` 动词） |
| `src/Features/GamePacks/GamePackSetting.xaml(.cs)` | 设置页「游戏包」：列表、能力行、启动、选 exe、自动查找状态 |
| `src/Program.cs` | `Main` 最前面拦 `launchpack` 动词，**不进 WinRT/XAML 初始化**、不碰单实例互斥量 |
| `src/Features/Setting/SettingPage.xaml(.cs)` | 设置左栏新增「游戏包」入口（Tag=`GamePackSetting`，字形 E7B8） |
| `src/Localization/Lang.cs` / `LangZh.cs` / `LangEn.cs` | 新增 15 个键；其余 8 种语言按既有机制回落中文 |
| `tools/extract_pe_icon.py` | 纯标准库从 exe 抠最大图标转 PNG（本机 `Add-Type` 被策略封，绕开 System.Drawing） |

包本体：`src/Arietta/games/arknights-endfield/`（game.json + 256×256 icon.png）。

## 三、game.json 字段

```jsonc
{
  "id": "arknights-endfield",     // 必填，小写+连字符，决定配置键
  "name": "明日方舟：终末地",
  "vendor": "Hypergryph",
  "version": "1.0.0",             // 包自身版本，不是游戏版本
  "order": 100,                   // 切换器排序；内置库洛游戏占 0-99
  "icon": "icon.png",
  "serverCode": "CN",
  "exeNames": ["Endfield.exe"],
  "markerDirs": ["Arknights Endfield"],   // 扫盘特征目录名
  "registryKeys": [],                     // 可选的 InstallPath 来源
  "launch": {
    "exe": "Endfield.exe",               // 相对安装目录
    "args": "",
    "decoyParent": "PlatformProcess.exe", // 父进程伪造用，见下
    "requireAdmin": true
  },
  "capabilities": { "launch": true, "gacha": false, "settings": true, "update": false },
  "provider": { "command": "python", "args": ["provider.py"], "protocol": 1 }
}
```

校验失败（缺 id/name、id 非法）不会让页面崩：该行显示 `broken: <原因>`，其余包照常。

## 四、启动校验的绕过（这是本轮技术核心）

现象：直接 `Process.Start(Endfield.exe)` 起不来。两个独立门槛：

1. **清单要求管理员**：`Endfield.exe` 的 `requestedExecutionLevel=requireAdministrator`。Arietta 是 asInvoker，非提权进程 `CreateProcess` 会直接 740。
2. **父进程检查**：客户端要求直接父进程是 **鹰角签名的 `Games.exe`**。

Collapse 的 Hypergryph 插件（本地副本 `D:\Work\Github\Hi3Helper.Plugin.Hypergryph-main`）解法，我们照抄机制、不照抄代码：

- 官方目录里 `PlatformProcess.exe` 是 **asInvoker + 同证书签名**（实测两 exe 签名者指纹一致：`2B366F39…`），可以拿它当替身。
- 复制成 `parent/<宿主pid>/<guid>/Games.exe` → **以 CREATE_SUSPENDED 创建、永不恢复** → 用它作为 `PROC_THREAD_ATTRIBUTE_PARENT_PROCESS` 拉起游戏 → 游戏退出后终止替身并删目录。
- 因为游戏要提权，宿主自己也必须提权：**用 `Arietta.exe launchpack …` 自我重启一次（`Verb=runas`）**，不额外引入 helper exe。提权实例只做「造替身 → 拉起 → 等退出 → 清理」，全程无窗口。

签名校验用 `X509Certificate.CreateFromSignedFile` 比指纹（不硬编码发布者名），替身与游戏签名者不一致就拒绝启动。

## 五、已验证 / 未验证

已验证：
- 构建 0 错误（`dotnet build src/Arietta.csproj -c Release`）。
- 设置页实测渲染正常（用户截图确认）：包被读到、图标与 `id · vendor · version` 正确、能力行 `启动 · 设置` 正确。
- 两 exe 签名者一致（decoy 前提成立）。
- 包 JSON 解析正常（含注释与尾逗号）。

未验证（需要 UAC 交互，无法自动完成）：
- **点「启动」→ UAC → 游戏是否真被拉起**。
- 替身清理是否彻底（游戏退出后 `parent/<pid>/` 应消失）。
- 游戏自身是否还有第三层校验（如 `verify_files.json` 完整性）。

## 六、已知限制

- 自动查找只在页面首次加载时跑一次（进程内 `_searched` 去重），失败后只能手动选 exe。
- 扫盘深度上限 4、跳过系统目录；装在更深或改名目录里会找不到，手动选即可。
- 包已支持多服（2026-11-15）：`game.json` 的 `servers` 数组由宿主通用展开——一份 manifest 拆成多个切换器条目，共用封面 / provider / 设置页，各自独立 exe 配置键（`PackExePath_<变体id>`），再按 manifest id 合并回一张「游戏 → 服务器」卡片。`primary` 服保留原 id，旧配置键不丢；短名复用宿主码表（GL/CN/BILI），角标图由包声明。**待实测**：终末地国际服 / B服的实际安装目录特征词、exe 名与各服端点差异，目前 `markerDirs` 是保守猜测，需按客户端校正。
- `provider`（抽卡）字段已进模型但宿主侧**没有消费者**，是下一轮的活。
- 参数 `--args` 目前是整串透传，未做引号/环境变量处理。

## 七、验证方式

```bash
dotnet build src/Arietta.csproj -c Release
# 应用内：设置 → 游戏包 → 应列出「明日方舟：终末地」，状态栏短暂出现「正在查找…」，随后 exe 路径回填、启动按钮变亮
# 日志：src/Arietta/log/Arietta_<yymmdd>.log 搜 [GamePack]
```

## 八、下一步

1. 用户实测启动，确认 UAC 与替身清理。
2. `provider` 客户端（进程 + JSON 行协议）→ 抽卡记录进宿主（GachaStore / 矩阵总览 / UGF 导出）。
3. `GameBiz` 字符串化 + 能力门控 → 包游戏进游戏切换器、时长统计、抽卡页。
4. settings 表（注册表键值映射）→ 终端地的画面/音频/语言设置页，纯数据驱动。
