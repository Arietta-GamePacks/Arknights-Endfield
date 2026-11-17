# Collapse 终末地插件调查与画面设置预览交接（Hi3Helper.Plugin.Hypergryph）

## 背景

用户想从 Collapse 的终末地插件（`D:\Work\Github\Hi3Helper.Plugin.Hypergryph-main`，Hypergryph/鹰角系游戏插件，含明日方舟与终末地）把能搬的功能搬进 Arietta：**公告获取、下载 CDN、游戏画面设置**。本篇记录插件源码调查结论 + 实测 API + 画面设置页 HTML 预览（`preview-endfield-settings.html`，v2 起保留 Arietta 现有画面设置页风格（左侧粗设置，右侧详细设置），v4 改为注册表驱动枚举，浏览器截图比对通过；本篇与另两篇终末地文档已从 Arietta 仓库 docs/ 迁入本目录）。

## 插件结构速览

| 项目 | 内容 |
|---|---|
| Hi3Helper.Hypergryph.Core | 国服通用层：batch_proxy API、安装器/更新器/修复器、HgCrypto |
| Hi3Helper.Hypergryph.Yostar | 国际服（Yostar/Gryphline）API 客户端 |
| Hi3Helper.Plugin.Endfield | 终末地插件本体：4 个服预设 + `Settings/EndfieldDisplaySettings.cs`（画面设置） |
| Hi3Helper.Plugin.Arknights | 明日方舟插件（本篇不涉及） |

服预设常量（batch_proxy 全靠这组）：

| 服 | API 根 | appcode | launcher_appcode | channel/sub_channel | seq |
|---|---|---|---|---|---|
| 国服官服 | `launcher.hypergryph.com/api/proxy` | `6LL0KJuqHBVz33WK` | `abYeZZ16BPluCFyT` | 1/1 | 5 |
| B 服 | 同上 | `6LL0KJuqHBVz33WK` | `abYeZZ16BPluCFyT` | 2/2 | 5 |
| 国际服 | `launcher.gryphline.com/api/proxy` | `YDUTE5gscDZ229CW` | `TiaytKBUIEdoEwRT` | 6/6 | 3 |
| Play 商店 | 同国际服 | `YDUTE5gscDZ229CW` | 同 appcode | 6/802 | 3 |

web 变体（公告等）= 根 + `/web/batch_proxy`。画面设置插件只对国服官服（`EndfieldCn`）开放（`Read()` 里 profile 判断）。

## 公告获取（实测通过，2026-11-14）

一次 POST 拿全部：`POST https://launcher.hypergryph.com/api/proxy/web/batch_proxy`

```json
{"seq":"5","proxy_reqs":[
  {"kind":"get_banner","get_banner_req":{…common}},
  {"kind":"get_announcement","get_announcement_req":{…common}},
  {"kind":"get_sidebar","get_sidebar_req":{…common}}   // 社媒入口，可选
]}
// common = {"appcode":"6LL0KJuqHBVz33WK","language":"zh-cn","channel":"1","sub_channel":"1","platform":"Windows","source":"launcher"}
```

- `get_banner_rsp.banners[]`：`url`（图片，`hg-utils-public.hycdn.cn`）+ `md5` + `jump_url` → 轮播图
- `get_announcement_rsp.tabs[]`：`tabName`（公告/资讯/活动，按名分类）+ `announcements[]{content, jump_url, start_ts(毫秒字符串)}` → 公告列表
- `get_sidebar_rsp.sidebars[]`：`media` + `pic.url`（悬浮二维码）+ `jump_url` → 侧栏社媒按钮
- 另有 `get_main_bg_image`（`url` + `video_url`，启动器动态背景）插件未用但接口存在——**2026-11-15 已真打实测**（web 端点，请求体必须带 `platform:"Windows"` + `source:"launcher"`，否则只回 `{"kind":"get_main_bg_image"}` 空壳；详见「游戏包-官方动态背景接入-交接.md」）

## 下载 CDN（实测通过，2026-11-14）

`POST https://launcher.hypergryph.com/api/proxy/batch_proxy`（非 web）：

```json
{"seq":"5","proxy_reqs":[{"kind":"get_latest_game","get_latest_game_req":{
  "appcode":"6LL0KJuqHBVz33WK","launcher_appcode":"abYeZZ16BPluCFyT",
  "channel":"1","sub_channel":"1","version":"<本地版本，未装传空>"}}]}
```

实测返回：`version:"1.6.4"`，`pkg.packs[]` 为 1 GiB 分包 zip.001…，CDN `https://beyond.hycdn.cn/6LL0KJuqHBVz33WK/1.6/update/1/1/Windows/1.6.4_zalKK5GCVQUtfKG1/packs/…zip.NNN?auth_key=<签名>`，每包带 `md5` + `package_size`（字符串字节数）。

- **本地版本**：读游戏目录 `config.ini`（安装判定 = `Endfield.exe` + `config.ini` 都存在）；安装目录名惯例 `Arknights Endfield Game`
- **增量更新**：`patch`（`url`/`md5`/`v2_patch_info_url`+`v2_patch_info_md5`/`cd_key`/`patches[]`）——v2 清单是逐文件 diff（`base_file`/`patch` 节点），`request_full_package=true` 可强制要全量
- **预下载**：`pre_patch`（结构同 patch，含 `version`），无则为空
- 手动校验 = 强制全量请求后逐文件 MD5 对照（HgGameRepairer，走 v2 清单）

## 画面设置（键名全表，注册表 `HKCU\Software\Hypergryph\Endfield`）

Unity 标准哈希键名，除音量外全部 **REG_DWORD**：

| 用途 | 键名 | 取值 |
|---|---|---|
| 宽度 | `Screenmanager Resolution Width_h182942802` | DWORD |
| 高度 | `Screenmanager Resolution Height_h2627697771` | DWORD |
| 原生分辨率 | `Screenmanager Resolution Use Native_h1405027254` | 0/1 |
| 窗口模式 | `Screenmanager Fullscreen mode_h3630240806` | 0=独占全屏 1=无边框全屏 3=窗口 |
| 画质预设 | `video_quality_main_h2648490162` | 1=极高 2=高 3=中 4=低 5=极低 |
| 帧率上限 | `video_frame_rate_8_h697513772` | 1000=120FPS 2000=60FPS 3000=30FPS |
| 自定义画质 | `video_custom_quality_h2367254986` | 0/1；改画质细项→自动 1，改画质预设→自动 0 |
| 各向异性采样 | `video_quality_anisoLevel_1_h3121203451` | 1000/2000/3000/4000（1×/2×/4×/8×） |
| 画质提升 | `video_quality_upscaler_2_h1962157691` | 1000=DLSS 2000=TAAU 3000=AMD FSR 3 |
| FSR 模式 | `video_quality_fsr3_mode_1_h3089342015` | 1000超高性能 2000高性能 3000平衡 4000高质量 5000原生AA |
| DLSS 模式 | `video_quality_dlss_mode_1_h833809667` | 同上 5 档，5000=DLAA |
| 锐化程度 | `video_quality_sharpness_1_h923865732` | 0–1000，UI 显示 0–1 步进 0.1 |
| 帧生成 | `video_quality_framegen_1_h428217478` | 1000=关闭 2000=DLSS 3000=FSR 3 |
| DLSS 帧生成 | `video_quality_dlssg_mode_1_h1229296740` | 1000自动 2000=2× 3000=3× 4000=4× |
| Reflex | `video_quality_reflex_1_h358679639` | 1000关 2000开 3000开+增强 |
| 总音量 | `audio_global_h50590663` | **8 字节 double 0–1**（REG_BINARY 语义，UI 显示 0–10） |
| 语音音量 | `audio_voice_h1583466330` | 同上 |
| 音乐音量 | `audio_music_h1556961229` | 同上 |
| 音效音量 | `audio_sfx_h3763990721` | 同上 |
| 输出模式 | `audio_suite_mode_h170452302` | 1耳机 2电视 3家庭影院 4桌面音响 |
| 后台静音 | `audio_suspend_unfocused_h977418127` | 0/1 |
| 控制器喇叭 | `audio_controller_h1787073584` | 0/1 |
| 文字语言 | `language_text_change_h1448997164` | 0简中 4繁中 8德 12英 16西 20法 24印尼 28意 32日 36韩 40葡(巴) 44俄 48泰 52越 |
| 语音语言 | `language_audio_h2756590110` | 1中文 2英文 3日文 4韩文 |
| 阴影 | `video_quality_shadowmap_1_h128234669` | 1000高 2000中 3000低 4000极低 |
| 纹理 | `video_texture_quality_1_h3061223496` | 2000中 3000低 |
| 体积雾 | `video_quality_volumetricfog_1_h4151020765` | 1000极高 2000中 5000关 |
| 体积云 | `video_quality_volumetriccloud_1_h4135137794` | 1000极高 3000中 5000极低 |
| 环境光遮蔽 | `video_quality_ao_1_h2648627865` | 1000高 3000低 4000极低 |
| 场景细节 | `video_quality_scene_detail_1_h1593605959` | 1000极高 2000高 4000低 |
| 环境细节 | `video_quality_environment_renderfeature_1_h2552402819` | 1000高 3000低 |
| 植被密度 | `video_quality_grass_sparsity_1_h587916507` | 1000高 2000低 |
| 色差 | `video_quality_chromatic_aberration_1_h1000454999` | 0/1000 |
| 屏幕空间反射 | `video_quality_screenspacereflection_1_h1017734168` | 1000极高 4000低 5000关 |
| 接触阴影 | `video_quality_contactshadow_1_h2952688721` | 0/1000 |

插件行为约定（照搬即可）：

1. **只列出已确认项**：注册表里不存在或取值不合法的键不显示（截图里音效音量/输出模式没出现就是这个原因）
2. **写前校验**：逐一核对原值未被游戏改过（变了则中止），且 `Endfield.exe` 在跑就拒绝写
3. **音量特殊**：存 double 而非 DWORD（插件用 `RegSetValueEx` 直接写 8 字节），读的时候要求 `REG_QWORD` 类似长度——Arietta 实现时按 8 字节 binary 读写
4. UI 显示口径：音量 ×10（0–10），锐化 ÷1000（0–1）

## 本机注册表实测（2026-11-14，游戏 1.6.4，共 271 个值）

设置类键（过滤噪音后 48 个）中与画面相关的实测值：

| 键（略去哈希后缀） | 实测值 | 含义 |
|---|---|---|
| Screenmanager Resolution Width / Height | 3840 / 2160 | 分辨率 |
| Screenmanager Resolution Use Native | 1 | 用原生分辨率 |
| Screenmanager Fullscreen mode | 1 | 无边框全屏（0=独占 3=窗口） |
| Screenmanager Resolution Window Width / Height | 3840 / 2160 | 窗口模式下的窗口尺寸 |
| UnitySelectMonitor | 0 | 显示器选择 |
| video_full_screen | 1 | 全屏开关（与 Screenmanager mode **并存两套，写时要同步**） |
| video_resolution_width / height | 3840 / 2160 | 第二套分辨率（同上，**要同步写**） |
| video_quality_main | 4 | 画质预设：低 |
| video_frame_rate_8 | 1000 | 120 FPS |
| video_quality_upscaler_2 | 3000 | AMD FSR 3 |
| video_quality_fsr3_mode_1 | 3000 | 平衡 |
| video_quality_framegen_1 | 1000 | 关闭 |
| video_quality_anisoLevel_1 | 3000 | 4× |
| video_quality_sharpness_1 | 1000 | 锐化 1.0 |
| video_quality_scene_detail_1 | 3000 | 场景细节——**插件目录只认 1000/2000/4000，实测存在 3000 档** |
| video_quality_effect_1 | 3000 | 特效质量——**插件未收录的新键**（枚举待游戏内确认） |
| video_quality_vsync_v2_2 | 0 | 垂直同步 v2——**插件未收录的新键** |
| video_custom_quality | 1 | 自定义画质联动位（内部，不给 UI） |
| language_text_change / language_audio | 0 / 1 | 简体中文 / 中文语音 |

关键结论：

1. **插件白名单比游戏实际更旧更窄**：本机 10 个 video_quality 键里 effect_1、vsync_v2_2 插件不认识；scene_detail 的 3000 档插件会判「非法」隐藏。白名单方案必漏——枚举注册表 + 已知目录兜底（v4 方案）才是对的。
2. **游戏没在游戏内动过的画质键不写注册表**（本机无 shadows/textures/fog/clouds/ao/reflections/contact 等），已知键缺省时显示默认值、保存时创建即可，游戏下次启动会读。
3. **audio_* 在本机是 REG_DWORD（4 字节 0x0）**，不是插件假设的 8 字节 double——按插件逻辑本机一个音量键都不会显示。落地按 DWORD 兼容 QWORD 处理。
4. **CollapseLauncher 已在本注册表写自己的键**（CollapseLauncher_PlaytimeStats / CustomArgs / LastPlayed），游戏容忍第三方写入，Arietta 写入无先例风险。
5. 噪音键过滤规则：`PLDK_*`（下载账本）、`ManualCraftCollectRewardReport_*`（打造报告）、`unity.player_*`（会话）、`hg_warmup_*`、`u8sdk_*`、`CollapseLauncher_*`、`character_gender`、`controller_*`、`teammate_skill_effect_strength`（玩法设置，非画面）。
6. v1 用户截图的值（低/120FPS/4x/FSR3/平衡/锐化1/帧生成关/3840×2160）与本机注册表逐项一致——那张截图就是本机的 Collapse 画面设置页。

## HTML 预览

`preview-endfield-settings.html`（本 GamePack 目录下）：v1 1:1 还原 Collapse 插件截图 → v2 改保留 Arietta 现有画面设置页风格（窗口 chrome + 左侧导航栏 + 底部应用栏）→ v3 删各节灰色说明、删「自定义画质」勾选（写值时自动联动，不给 UI）、行内小框、WinUI 滑条 → **v4 注册表驱动**：枚举 `HKCU\Software\Hypergryph\Endfield` 设置类键全量展示（数据 = 本机实测值），注册表未写入的已知键**半透明**显示默认值（保存时创建），插件未收录的新键（特效质量、垂直同步）直接入列。布局：左列分辨率（全屏 + 自定义分辨率 + 显示器）/画质设置/语言设置，右列画质细项 + 超分辨率与帧生成。每个控件 `title` 悬停显示键名 + 实测值。v5 交互式：下拉/勾选/滑条可操作（分辨率预设联动宽高输入框、应用按钮出模拟 toast）；**「模式」行随画质提升联动替换**（FSR 3→FSR 模式、DLSS→DLSS 模式、TAAU→隐藏该行）；**帧生成 = DLSS 时显示「DLSS 帧生成模式」行**（对应 dlssg_mode 键）；NVIDIA Reflex 为独立新增行；左右列距收紧（26px）、kv 标签定宽 96px 对齐输入框。已用浏览器逐项点击验证联动。

## 可搬结论

1. **公告**：一个 POST 全拿到（轮播 + 公告 + 社媒），无需鉴权、无混淆 token，比库洛的 information.json 还省事——直接对齐 Arietta 现有公告面板
2. **CDN/更新**：get_latest_game 拿 packs + patch + pre_patch，与 Arietta 现有「更新-krpdiff」管线同构（分包 zip + md5 + 签名 URL），增量走 v2 清单（逐文件 diff，比 krpdiff 组补丁更细）
3. **画面设置**：纯注册表读写，键名全表在本篇；照 EndfieldDisplaySettings 的校验/联动逻辑（custom 联动、防覆盖、游戏运行禁写）抄即可

## 验证方式

- 公告/CDN 端点：curl 真打通过（2026-11-14，返回 1.6.4 真实分包与 banner）
- 画面设置键名：插件源码 `Settings/EndfieldDisplaySettings.cs` + `EndfieldPreferenceCatalog.cs` 逐条摘录
- 预览：IAB 浏览器 1400×920 截图与用户参考图逐节比对

## 已知待办

- HTML 预览评审通过后才做 WinUI 落地（画面设置页 + 公告源 + 下载源）
- 国际服（Yostar API）结构与国服不同，本篇只覆盖国服口径；若 Arietta 要接国际服再调查 `Hi3Helper.Hypergryph.Yostar`
- ~~`get_sidebar` / `get_main_bg_image` 未真打~~（2026-11-15 更新：`get_main_bg_image` 已真打并接入 provider `background` 方法，双服通过；`get_sidebar` 仍未真打）
- 音量键 8 字节写法的注册表值类型（插件用 type=4 写 8 字节）落地时需真机对照游戏原生写法

---

## 实装（2026-11-15）：设置页代码化，走 provider 模型

用户红线（AGENTS.md）：宿主零游戏语义。此前把 Unity 显示复合逻辑写进 Arietta 被否，返工后：

- **宿主（通用能力，换包零改动）**：`PackSettingsPage` 重写为通用行模型渲染器——toggle/choice/number/slider、`visibleWhen`/`enabledWhen`（按暂存值评估）、行级/选项级附带写（`writes`）、暂存应用（应用前查 `pack.ExeNames` 进程，运行中拒绝写）、两列布局（`column`）。模型来源两选一：包声明 `settingsProvider` 进程（新增，优先）或静态 game.json 表（兜底，schema 新增 slider/sets/visibleIf/enabledIf/nvidiaOnly 字段；nvidiaOnly 由宿主通用 GPU 查询过滤）。
- **包（全部终末地语义）**：新增 `settings.cs`（C#，编译 `settings-provider.exe`，`build.cmd` 单文件 publish，obj 在包外 `build-out/`）。协议新增 `settings-model`：返回 store 路径 + 行模型；键名/枚举/联动（改画质细项→custom 1、改预设→custom 0）、GPU 过滤（读设备类注册表 DriverDesc，本机 AMD → 模型里根本没有 DLSS/Reflex 行）、分辨率预设清 Use Native、模式互换（visibleWhen）全部在这。
- **game.json**：删 JSON 设置表，改 `"settingsProvider": { "command": "settings-provider.exe", "protocol": 1 }`。
- 宿主构建 0 错误（中途撞脏 obj + XAML 编译器锁，按本 AGENTS 记忆 rebuild + 手动清 obj/bin 解决）；部署副本已同步 game.json + exe 并重签（valid · PaperKito）；本机冒烟 ping/settings-model 均通。

待办：UI 端到端（开发实例里点一遍）未验；provider.exe 是框架依赖（.NET 10 运行时，宿主同款要求），对外发包时再评估 self-contained。

---

## 实装 v6（2026-11-15）：WinUI 页面按 v5 预览稿还原布局

用户指出「实装跟预览不一样」：此前 WinUI 页是通用行模型渲染器逐行铺大控件，跟 `preview-endfield-settings.html` 的紧凑 kv 网格完全两回事。修法仍是红线内的通用能力：**宿主只认布局 token，包负责声明**。

- 宿主 `PackSettingsPage` 新增 `group.style`（list / flow / cards / compact）、`row.hint`（悬停键名与实测值）、`exists=false` 半透明行、分组标题 22px / 两列间距 26px。详见宿主仓库 `docs/宿主-包设置导航可见性修复-交接.md` 第三轮。
- `settings.cs` 的 5 个分组分别声明：分辨率 `flow`、画质设置 / 语言设置 `cards`、画质细项 / 超分辨率与帧生成 `compact`；`Row()` 统一生成 hint（已写入 → 键名 + 实测值；未写入 → 「注册表暂无此键：保存时创建」），对应预览的 title 与 dim 行。
- 顺手删掉 `NVIDIA Reflex` 行被 `if (nvidia)` 重复添加两次的 bug（AMD 本机看不出来，N 卡会出两行）。
- `build.cmd` 修正：SDK 10.0.401 下框架依赖单文件不支持 `EnableCompressionInSingleFile=true`（NETSDK1176），去掉该参数；同时改成纯 ASCII（cmd 用系统码页解析，中文 rem/echo 会乱码），自检非 ASCII 字节 = 0。
- 验证：`build.cmd` 重建 exe 成功；`settings-model` 返回 `ok:true`、5 组 style 正确、hint 与 dim 行齐；同步部署副本后 `GamePackSign verify = valid · PaperKito`；宿主 Release 构建 0 错误。仓库内 `signature.json` 按约定仍等 assets 收尾统一重签。
- 待用户重启宿主目验布局与联动（画质提升 → 模式行、帧生成 → DLSS 帧生成模式）。

---

## 实装 v7（2026-11-15，订正 v6）：UI 参照作废重认

**重要：本篇标题里的「画面设置预览」与 `preview-endfield-settings.html` 从此不再是 UI 参照，只保留注册表键名 / 枚举 / 本机实测数据的调研价值。** 用户两张截图确认：期望的 p1 是**宿主内置 `GameSettingPage`**（证据：p1 的说明文字「首次启动游戏前设置此值可以避免下载部分语音资源」= 宿主 `LangZh.cs:610`，控件结构逐项对应 `GameSettingPage.xaml:25-77`），不是 Collapse 插件风格页，也不是这份 HTML 稿。前三轮照 HTML 稿做，方向错了。

p1 的分辨率段特征：方形 CheckBox「全屏」/「自定义分辨率」→ 无标签 160 宽分辨率下拉 → 120 宽宽高输入框并排、中间 `×`；语言设置段：标题 + 灰色说明文字 + 无标签下拉。p2（旧实装）是 ToggleSwitch + 每行左标签 + 宽高分行，完全两套。

- 宿主通用渲染器新增 `stack` 样式、`control=check`、`row.join`、`group.description`、空 label 不渲染（详见宿主仓库 `docs/宿主-包设置导航可见性修复-交接.md` 第四轮）。
- `settings.cs`：分辨率组改 `stack`（`Check()` 两个 + 空标签下拉 + `join:"×"` 的宽高 pair），画质 / 语言改 `stack`，语言组的 description 用内置页同款文案；右列两组仍 `compact`。新增 `Check()` 行构造，`Number()` 支持 `join`。
- 验证：宿主 Release 构建 0 错误（撞 Arietta.exe 文件锁，按 AGENTS.md 授权杀实例后重建，**开发实例已关闭需重开**）；`build.cmd` 重建 exe；部署副本冒烟 `ok:true`，分组 / 行结构 / 说明文字全对；`GamePackSign verify = valid · PaperKito`。仓库 `signature.json` 仍按约定等 assets 收尾统一重签。
- ~~待办：内置页「全屏 ↔ 自定义分辨率」互斥未实现~~ → v8 已补。

---

## 实装 v8（2026-11-15）：互斥、间距、锐化滑块 Collapse 化

- 用户截图指出两个勾选框间距不对且能同时勾上。根因：第四轮只搬了内置页外观，没搬 `GameSettingPage.xaml.cs:58-114` 的互斥逻辑；`stack` 行还叠了 4px 上下内边距，间距与内置页不一致。
- 宿主新增通用 `row.exclusiveGroup`（同组 check 互斥 + 联动写对方 Off 值 + 初始双勾修正），`stack` 行 Padding 归零；详见宿主仓库 `docs/宿主-包设置导航可见性修复-交接.md` 第五轮。
- `settings.cs`：`Check()` 支持 `exclusiveGroup`，全屏 / 自定义分辨率两行都声明 `"display"`。锐化模型不变（`0–1`、步进 `0.1`、scale `1000`），与 Collapse 插件 `EndfieldPreferenceCatalog.cs:38,64` 的 `GameSettingEntry.Slider(value/1000.0,0,1,0.1)` 同口径。
- **Collapse 滑块形式**由宿主通用渲染器实现：`TickPlacement.Outside`、`TickFrequency=max(step,(max-min)/10)`、`IsThumbToolTipEnabled=false`，并在 `Loaded` 后把水平轨道改成 18px 圆角粗条（对应 Collapse `FatSliderStyle` 的观感）。Collapse 的 `FatSlider.xaml` 有 823 行且依赖其专属 `conv:DoubleRound` / `extension:UIElementExtensions`，未整份搬入。
- 验证：宿主 Release 0 错误（按 AGENTS.md 授权杀实例解文件锁，**需重开**）；`build.cmd` 重建 exe；部署副本模型冒烟 `exclusiveGroup` / `sharpness` / style 全对；`GamePackSign verify = valid · PaperKito`。仓库 `signature.json` 仍按约定等 assets 收尾统一重签。

---

## 实装 v9（2026-11-15）：预设下拉补完内置页双条件状态机

- 用户指出勾了「自定义分辨率」预设下拉仍能选。内置页 `GameSettingPage.xaml.cs:110-114` 是双条件：`IsResolutionListEnabled = !EnableFullScreen && !EnableCustomResolution`、`IsCustomResInputEnabled = EnableCustomResolution && !EnableFullScreen`。v8 只给宽高加了单条件，下拉完全没接。
- 宿主通用协议扩展：`enabledWhen` / `visibleWhen` 支持数组（多条件 AND），单对象旧写法仍兼容；静态 JSON 表路径同步兼容。详见宿主交接文档第六轮。
- `settings.cs` 新增 `Conditions(...)`；分辨率组：预设下拉 `mode==3 && native==1`，宽 / 高输入框 `native==0 && mode==3`（原为单条件 `native==0`）。互斥联动同时写两个键，条件即时刷新。
- 验证：宿主 Release 0 错误（按授权杀实例解文件锁，**需重开**）；`build.cmd` 重建；部署副本冒烟三行条件均为 2 项数组；`GamePackSign verify = valid · PaperKito`。仓库签名仍等 assets 收尾统一重签。

---

## 实装 v10（2026-11-15）：Collapse 锐化滑块原样式归位到包

- 用户截图确认 Collapse 锐化滑块形态：粗圆角轨道 + 外侧刻度 + **白色圆角 Thumb 内显示数值「1」**。代码证据：`D:\Work\Github\CollapseLauncher_Collapse\CollapseLauncher\XAMLs\Theme\Slider\FatSlider.xaml:430-450`（Thumb 模板内 `FatSliderInnerThumbValue` TextBlock 走 `DoubleRound3Converter`）、`:735-743`（`HorizontalThumb` 的 `DataContext="{TemplateBinding Value}"`）、`PluginGameSettingsPage.cs:275-290`（`FatSliderStyle` + `TickPlacement.Outside` + 十等分刻度）、`ValueConverters.cs:96`（`Math.Round(v,3)`）。
- 用户指令「先搬到包里」：Collapse 原版 `FatSlider.xaml`（823 行 / 65874 B）落到包内 `assets/FatSlider.xaml.txt`，部署副本同步同名文件并重签 `valid · PaperKito`。**扩展名必须是 `.txt`**：放 `.xaml` 会被宿主 WinUI 项目当 Page 编译（`src/Arietta/games/` 在项目内），触发 WMC0001 / WMC9999 / CS2012 连锁错误。
- 宿主侧不加载包内这份 XAML（App.xaml 已回退），而是用通用渲染器复刻同款效果：粗圆角轨道、外侧刻度、`XamlReader.Load` 换成白色数值 Thumb、`ValueChanged` 联动数值。详见宿主交接文档第七轮。
- 验证：宿主 Release 0 错误（先跑 `rebuild.bat` 清脏 obj）；部署副本签名 valid；包内样式文件存在。仓库 `signature.json` 仍按约定等 assets 收尾统一重签。
- 待用户重开目验：锐化滑块右侧白色块显示「1」、拖动数值同步；运行时模板加载失败会静默退回默认拇指。

---

## 实装 v11（2026-11-15）：滑块整份移植，包内不再承担样式渲染

- 用户反馈 v10 效果不对：Collapse 是「整条滑轨铺满、白色按钮压在上面」，我们那版白块背景不全、像镂空，刻度也不是真刻度。核对源码：Collapse 轨道 `HorizontalTrackRect` 高 14、已填充条 `HorizontalDecreaseRect` 高 20 且 `Translation="0,0,8"` 浮在上层；拇指布局仅 18×18，视觉是内部 48×32 的白块**故意溢出**；外侧刻度是 3px `TopTickBar`/`BottomTickBar`。v10 那套「默认模板 + 改高度 + XamlReader 换拇指」从结构上就不是它。
- 本轮改为**整份移植**到宿主 `src/Styles/FatSlider.xaml`（820 行）+ `src/Converters/FatSliderConverters.cs`（4 个转换器），`App.xaml` 合并该字典，`PackSettingsPage.BuildSlider` 只负责装样式与 `TickFrequency=step`。详见宿主交接文档第九轮。
- **样式为什么在宿主**：包内 XAML 无法在编译期并进应用资源树，运行时 `XamlReader` 解析 820 行 + `using:` 映射 + 大量 `ThemeResource` 风险过高。包内 `assets/FatSlider.xaml.txt` 继续作为来源参照保留，签名覆盖范围不变。
- 顺带修 compact 网格错位：滑块行独占整行（ColumnSpan），其余控件垂直居中。这是宿主通用布局能力，包侧 `settings.cs` **无需改动**，因此本轮未重建 provider、未重签部署副本。
- 待目验：锐化轨道整条铺满、白块无镂空、外侧 11 根刻度、帧生成下拉与标签同轴。
