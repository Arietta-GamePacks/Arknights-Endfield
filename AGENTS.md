# Arknights-Endfield 游戏包 · 项目级指引

## 架构边界（用户钦定，2026-11-15）

- **Arietta 不得出现任何包（游戏）的代码**：宿主只做通用能力（GamePack 加载 / provider 协议 / 公告卡 / 设置表单），一切游戏知识（端点、appcode、键名、字段映射）只准活在包目录（game.json / provider.py / ui/）。
- **允许**修改 Arietta 使其「能接入包的公告」这类**通用能力**（如 provider.notice 消费端）；判断标准：换一个游戏包、宿主一行不用改。
- 公告参照库：`D:\Work\Github\Hi3Helper.Plugin.Hypergryph-main`（Collapse 终末地插件），已实测结论见 `docs/Collapse-终末地插件-调查与画面设置预览-交接.md`。

## 构建宿主（Arietta）

- 本仓库的任务常要构建宿主验证：`dotnet build "D:/Work/Code Project/Arietta/src/Arietta.csproj" -c Release`。
- **遇 Arietta.exe 被锁（MSB3027/MSB3021）= 开发实例开着：直接 `taskkill /f /im Arietta.exe` 再建**，无需询问（用户明确授权，2026-11-15）。
- 编译错误的判定：报错里只有 MSB3026/3027/3021 是文件锁；出现 CS/WMC 开头才是真错误。
- **报错先看落在哪个文件**：WMC9999 + 一堆基础 API（如 FrameworkElement.IsEnabled）报不存在 = 半成品状态或脏 obj，先跑 Arietta 根目录 `rebuild.bat`；若报错集中在**本会话没碰过的文件**（如 PackSettingsPage），多半是并行会话正在编辑，等它落地再验，不要去修。
- 本仓库与部署副本（`Arietta/src/Arietta/games/arknights-endfield/`）各自持有签名：改包文件后**同步到部署副本并重签部署目录**（`dotnet run --project tools/GamePackSign -- sign <包目录> .keys/endfield.key "PaperKito"`，在 Arietta 仓库下执行）；仓库签名等 assets 半成品收尾时统一重签。
- **设置页是包代码不是数据**：`settings.cs` → `build.cmd` 编译出 `settings-provider.exe`（单文件、框架依赖 .NET 10），协议方法 `settings-model` 返回通用行模型，宿主只渲染（红线见上）。改设置语义只动 settings.cs，动完重新 build + 同步 exe 到部署副本重签。中间产物在包外 `../build-out/`，别混进包目录（签名哈希包内每个文件）。
