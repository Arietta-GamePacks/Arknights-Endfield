# 资源-GRYPHLINK启动器封面与壁纸提取-交接

## 背景
需要官方 GRYPHLINK 启动器（全球版，`D:\AAAAA\global\Arknights Endfield\GRYPHLINK`，v1.6.0）
里「游戏选择」方形卡片图（各语言 Logo 版）和终末地默认壁纸，供游戏包后续 UI 使用。
已提取落盘到 `assets/launcher/endfield/`（2026-11-15，来自本机安装的官方启动器）。

## 实测结论
- **资源不在磁盘缓存，也不在 CDN 明文路径上，而是内嵌在 `Games.exe` 里**（Qt 资源系统，
  `qrc:///web/theme/...`）。`res/web/` 只有 UI 壳（JS/CSS），`AppData` 里只有 `.ico` 应用图标。
- 图片 URL 规律（从 `res/web/index.f1a2b9.js` 逆出，base=`qrc:///web`）：
  - 卡片图 `{base}/theme/{theme}/lang/{lang}/cover.webp`
  - 默认壁纸 `{base}/theme/{theme}/default_background.webp`
  - 全游戏页背景 `{base}/theme/{theme}/background.webp`
  - 渠道图标 `{base}/theme/{theme}/channel/{channel}/game_icon.png`（official/bilibili）
- 内嵌覆盖度：3 个主题（endfield/arknights/popucom）。封面语言 endfield 和 popucom 各 5 种
  （zh-cn/zh-tw/en-us/ja-jp/ko-kr），arknights 只有 en-us + zh-cn；壁纸各 2 张。
  **5 种就是全部**——游戏本体只支持这 5 种语言，启动器其余 6 种 UI 语言（fr/es/de/pt/ru）
  走英文封面回退。
- `launcher.gryphline.com/api/proxy/web/batch_proxy` 有 `get_game_image`（返回 `.cover`/`.bg`
  的 CDN URL），但匿名请求一律返回空 rsp，需要登录态 token（存在原生侧加密 `app.data` 里），
  别再白嫖这条路线。
- `AppData/Roaming/Gryphline/<安装路径哈希>/icon/*.ico` 内嵌 256px PNG 游戏图标（顺手提取）。
- 网络缓存位置：`%LOCALAPPDATA%\PlatformProcess\Cache`（QtWebEngine 块文件，只有公告页资源）；
  `%TEMP%\HgLauncher\web\Cache` 为空目录，别再翻。

## 实现行为
提取方法：解析 PE 里的内嵌资源段——文件名为 UTF-16LE 顺序存储，图片载荷为原始
WEBP/PNG。用 magic 扫描裁切（`RIFF....WEBP` 按 RIFF 头长度截断；PNG 走 chunk 到 IEND），
再按画面内容确认语言归属。

**⚠️ 语言映射纠错（2026-11-15 晚）**：下表最初有 3 张认错（繁中/英文/日文互相错位），
当时靠肉眼批量看图排错；后做「封面+卡片九宫格对照表」才发现。正确映射如下——
数据段顺序与 QRC 文件树里 ko-kr, en-us, zh-tw, ja-jp, zh-cn 的列举顺序**不一致**，
别再按顺序推，必须逐张看 Logo 文字：

| 裁切物 | 归属 | 落盘 |
| --- | --- | --- |
| webp @0xc6d398 | 封面 明日方舟：终末地（简中） | `lang/zh-cn/cover.webp` |
| webp @0xca7484 | 封面 アークナイツ エンドフィールド（日文） | `lang/ja-jp/cover.webp` |
| webp @0xce1c02 | 封面 明日方舟：終末地（繁中） | `lang/zh-tw/cover.webp` |
| webp @0xd1bc78 | 封面 ARKNIGHTS ENDFIELD（英文） | `lang/en-us/cover.webp` |
| webp @0xd55c9a | 封面 명일방주 엔드필드（韩文） | `lang/ko-kr/cover.webp` |
| webp @0xbb7274 | 默认壁纸（底部渐隐供 UI 沉底） | `default_background.webp` |
| webp @0xc01406 | 全游戏页背景（完整主视觉） | `background.webp` |
| ico 内嵌 256px | 启动器缓存的终末地应用图标 | `app_icon_256.png` |

规格：封面 474×474 WEBP（约 230KB/张），壁纸 2324×1392 WEBP（约 300-400KB/张）。
目录结构刻意镜像启动器 QRC 路径（`theme/endfield/...` 去掉前两级）。
同次提取还得到 arknights（2 封面+2 壁纸）和 popucom（5 封面+2 壁纸）的同款资源，
当时判定不需要、未落盘，需要的话按上面方法 30 秒重提。

## 验证方式
```bash
python -c "from PIL import Image; import glob; [print(f, Image.open(f).size) for f in glob.glob('assets/launcher/endfield/**/*.webp', recursive=True)]"
```
应列出 7 个 webp：5 张 474×474 + 2 张 2324×1392。抽查 `lang/zh-cn/cover.webp`
应与启动器截图一致（佩丽卡 + 简中 Logo 方卡）。

## 已知待办
- 这些资源尚未被 `game.json`/`ui/` 引用；接入 UI 时如需 PNG，用 Pillow 转一次即可。
- 若未来启动器更新主视觉（版本活动换图），重跑提取：先看 `res/web/version.json` 的
  UI 版本，再对 `Games.exe` 做 magic 裁切。
- 三个主题全部封面/壁纸如果后续要做 Arietta 多游戏包，可按本方法批量提取。
