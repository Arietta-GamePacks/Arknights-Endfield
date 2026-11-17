# 森空岛 API · 三玩法（危机合约 / 影拓丰碑 / 战争回响）图标字段定位 - 交接

> 时间：2026-11-15 下午
> 性质：**真打验证通过**（用户提供新 token，链路同 `docs/森空岛API-数据终端直连实测-交接.md`），图标 URL 全部拿到并下载目验。
> 前置：`docs/森空岛模块-游戏数据面板与H5进入实测-交接.md`（crisis / monument / echoes 三模块的模型结构）。

## 一、背景

三个玩法面板（危机合约 / 影拓丰碑 / 战争回响）目前都用通用 `"icon": "data"`。用户给新 token 要求拉取三个玩法的真实图标。**结论：图标不需要任何新端点，全部现成挂在已有响应里**，之前只是没定位。

## 二、实测结论：图标字段位置（2026-11-15 真打）

| 玩法 | 字段路径 | 形态 | 实测样例 |
|---|---|---|---|
| 危机合约 | `card/detail.crisisContract[].kvImage`（= `headerImage`，同图） | 1074×156 横幅 | 「危机合约 浸蓝测试作战」黄黑横幅 |
| 危机合约奖章 | `crisisContract[].achieve.achievementData.initIcon` / `platedIcon` | **126×126 方图** | 金色六边形奖章 |
| 影拓丰碑 | `card/detail.indieHard.indieHardGroups[].pic` | 960×1200 竖版海报 | 每系列一张，本号 8 个系列（深林呓语/幽影刻形/山中见犼/死寂争鸣/浊流具现/灼痛疤痕/无机造物/大地的弃子） |
| 战争回响 | war-echoes 独立接口 `data.warEchoes.seasons[].kvImage` / `headerImage`；`card/detail.warEchoes` 同构 | kv 1170×1170 方图、header 1074×168 横幅 | 当季「狂热赛季」红黑 UNDOMWIN 封面 |

- 全部是 `bbs.hycdn.cn` 直链，无防盗链（带/不带 Referer 均 200，上一轮已验）。
- 模块级小图标建议：危机合约 → 奖章 `initIcon`（唯一真方图）；影拓丰碑 → 最新系列 `pic`（裁剪或当海报）；战争回响 → 当期赛季 `kvImage`。
- 赛季/合约轮换后 URL 会换（按 `startTs` 夹当期即可，接法同面板「当期轮换」行），**不要把 URL 写死进包**。

## 三、token 细节（踩坑）

- 本次 token **开头带 `+`，共 25 位**：不带 `+` 的 24 位版本会被 grant 接口拒（`Field validation for 'token' failed on the 'base64' tag`）。鹰角 token 是 base64 字符集（可含 `+/`），用户给 token 时首尾字符别丢。
- token 只经 env 进程内使用；probe 的 `--save` 临时输出（含 cred/签名密钥）**已删除**，未写入任何长期文件。

## 四、产物

- `build-out/icons-endfield-2026-11-15/`（**包外**，不计签名）：14 张 PNG 已下载并验过文件头/尺寸——crisis-kv / 奖章×2 / monument×8 / echoes-狂热 kv+header。其余赛季图 URL 见上表字段，未逐一落盘。

## 五、App 区块标题图标排查（2026-11-15 下午第二轮，用户纠正需求后）

用户实际要的是**森空岛 App 个人主页各区块标题旁的黑白线条小图标**（干员/实时数据/危机合约旁那种），不是玩法横幅/海报。排查结论：

| 排查处 | 结果 |
|---|---|
| `card/detail` / war-echoes API | ❌ 区块图标字段不存在（quickaccess 只有快捷入口图标；实时数据各行 dailyMission/weeklyMission/bpSystem/credit 全是纯数值） |
| game.skland.com H5 前端 bundle（未登录可见部分，20+ chunk 全量 grep） | ❌ 无区块图标；Icon 组件是 `background-image:url(src)` 容器，src 由数据下发；区块 UI 组件在登录后才加载的 chunk 里 |
| H5 子页（crisis-contract 等）未登录态 | ❌ 只有下载引导墙 |
| www.skland.com 主站空间页 | ❌ 不存在（「该海域无法前进」） |
| 官方 wiki.skland.com 终末地「蚀刻章」分类 | ⚠️ 有「危机合约 \| 浸蓝测试作战」「影拓丰碑 \| 深林呓语」「战争回响 \| 狂热赛季」条目，但条目图是 396×396 **活动封面背景**，详情页也无奖章本体小图 |
| 社区插件源码（nonebot-plugin-skland，本地副本） | ❌ 同 zonai 接口，无图标 |

**结论：这三枚黑白 section 图标是森空岛 App 内置 UI 资源（RN 打包资源），不在任何公开 API / web 前端 / wiki 里。** 要拿只有拆森空岛 App APK 一条路。

**最接近的官方替代品**：危机合约当期奖章 `initIcon`（126×126 金色徽章，`crisisContract[].achieve.achievementData.initIcon`）——官方徽章图标，风格与 App 图标同源（蚀刻章体系）；随合约轮换而换，不写死。

产物：`build-out/icons-endfield-2026-11-15/section-*.png` 三张为 wiki 蚀刻章条目的活动封面图（396×396，非小图标，备用）。

## 五.5、APK 拆包结果（2026-11-15 傍晚，用户提供 森空岛.apk）

拆包路径 `C:\Users\PaperKite\Downloads\APK\森空岛.apk`（55MB，res 资源名混淆），提取到 `build-out/skland-apk-extract/`：

- **res/ 1008 张 png/webp**（混淆短名）+ `assets/rn/main.jsbundle`（RN-Common 基础包，业务文案/图标映射不在其中——业务模块动态下发）。
- 用「黑白+方形+多连通域」过滤（116 张）逐屏目验 + 用户截图裁剪比对（PIL 裁出真图标参照），**确认的映射**：
  - `xf.webp` = **实时数据** section 图标（柱状图+上升箭头，形态完全一致，蓝色版）
  - `hG.webp` = **狂热轮换行**图标（结晶雪花；App 截图轮换行图标同族）
  - `sO.webp` = **每周事务行**图标（盾徽）
  - `9H`（斜线爪痕）/ `Hf`（三角山）/ `Lz`（插地武器）/ `er`（法杖）/ `YX`（弩）= 同家族黑白徽章（108×109 系列），语义推断为干员职业/武器/影拓丰碑类
- **未在 base APK 中找到**：干员 section（裁剪参照=菱形小人）、危机合约 section（裁剪参照=三角框碎片）的图标本体 → 来自动态下发资源或 split APK，base 包内无。
- 全部候选图库：`skland-apk-extract/gallery-ef.html`（70-130px 徽章 252 张）/ `gallery-blocks.html`（多块几何 116 张）。
- 交付副本：`build-out/icons-endfield-2026-11-15/apk-icons/`（8 枚，中文描述命名）。

排查工具链：unzip 直拆 + PIL（灰度/饱和度/连通域过滤）+ IAB 浏览器逐屏目验 + 截图裁剪比对。模板匹配（归一化互相关/IoU）对线条图标区分度不足，最终靠人工目验。

## 五.6、✅ 最终突破：H5 chunk 里的官方图标映射表（2026-11-15 晚，已拿到原版）

**决定性发现**：`GameData-CkCjogiM.js`（终末地数据页 chunk，682KB）内含一张**区块图标映射表**，直接把 11 个区块的图标/选中态图标变量名列全了：

```js
G = {
  [W.BASE]:            {titleKey:`gamedata_home_subtitle_basic`,        icon:rn, selectedIcon:on},
  [W.OTHER_TOOLS]:     {titleKey:`gamedata_home_subtitle_other_tools`,  icon:Tn, selectedIcon:ln},
  [W.CHAR]:            {titleKey:`gamedata_home_subtitle_operator`,     icon:_n, selectedIcon:cn},  // 干员
  [W.REALTIME]:        {titleKey:`gamedata_home_subtitle_realtime`,     icon:vn, selectedIcon:un},  // 实时数据
  [W.CRISIS_CONTRACT]: {titleKey:`crisis_contract_title`,               icon:yn, selectedIcon:sn},  // 危机合约
  [W.ACHIEVE]:         {titleKey:`achieve_title`,                       icon:bn, selectedIcon:an},
  [W.DOMAIN_BUILD]:    {titleKey:`gamedata_home_subtitle_regional_dev`, icon:xn, selectedIcon:fn},
  [W.DOMAIN_EXPLORE]:  {titleKey:`gamedata_region_explore`,             icon:Sn, selectedIcon:dn},
  [W.WAR_ECHOES]:      {titleKey:`war_echoes_title`,                    icon:gn, selectedIcon:hn},  // 战争回响
  [W.INDIE_HARD]:      {titleKey:`gamedata_umbral_title`,               icon:Cn, selectedIcon:mn},  // 影拓丰碑
  [W.SPACESHIP]:       {titleKey:`gamedata_spaceship_title`,            icon:wn, selectedIcon:pn},  // 帝江号
}
```

图标有两种存在形式，都在 chunk 里：
- **内联 SVG 组件**：`var _n=(0,H.forwardRef)((e,t)=>(0,U.jsxs)('svg',{viewBox:'0 0 20 20',...}` —— 干员 `_n`、实时数据 `vn`、地区建设 `xn`。
- **内联 base64 PNG**：`yn=\`data:image/png;base64,...\`` —— 危机合约 `yn`(60×60)、影拓丰碑 `Cn`(60×60)、战争回响 `gn`(54×54)，选中态均为 96×96。

**已全部提取并逐像素验证通过**（与用户 App 截图裁切并排比对，四枚完全吻合：危机合约=三角框碎片、影拓丰碑=圆顶三角点阵、战争回响=四瓣结晶、干员=菱形小人）。

交付目录：`build-out/skland-section-icons/`（22 枚 = 11 区块 × 常态/选中态，含 `mapping.json`）。
- 目标三枚：`crisis.png` / `monument.png` / `echoes.png`（各附 `-selected.png` 白色版）
- 附赠：`char.svg`（干员）、`realtime.svg`（实时数据）等全部区块图标

注意：`-selected` 是白色版（用于深色/选中背景），在浅色底上看是空白，属正常。

提取脚本：`build-out/h5-icon-hunt/extract_all.py`（按变量名抓 base64 或 forwardRef SVG，可复用于后续版本）。

## 六、已知待办

1. **接入面板（未做，等用户发话）**：给三模块模型加图标字段。宿主已有通用 `rows[].icon` 渲染（20px），块级/卡片级大图需要另议；不写死 URL，从响应现取。
2. 仓库 `signature.json` 等 assets 收尾统一重签（既定口径）。
