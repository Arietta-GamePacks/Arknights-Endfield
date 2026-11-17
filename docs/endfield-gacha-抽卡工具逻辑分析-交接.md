# endfield-gacha · 抽卡工具逻辑分析 · 交接（2026-11-16）

用户要求分析本地参考库 `D:/Work/Github/Endfield/endfield-gacha-master`（终末地抽卡分析软件，
Nuxt3 + Vue3 + Tauri 本地存储，v0.7.2）的逻辑，重点核对与我们抽卡包的差异与保底口径。

---

## 一、三层架构

| 层 | 文件 | 干什么 |
|---|---|---|
| 取数 | `app/composables/gacha/gachaApi.ts`（590 行） | u8_token 驱动分页拉取 + 官方累计计数 |
| 计算 | `app/utils/gachaCalc.ts`（684 行） | 按池类型分派的分析函数，产出 `GachaStatistics` |
| 展示 | `app/pages/index.vue`（角色）/ `app/pages/weapon.vue`（武器） | 类型分组 + 下钻、饼图、6★ 历史 |

## 二、数据链路（与 provider.py 高度同源）

- 凭证：webview 日志 URI 解析出 `u8_token`（`parseGachaParams`），即我们已死的「日志通道」；社区登录链路它没有。
- 分页：每页 5 条、`seqId` 游标、失败重试 `MAX_PAGE_RETRY=3`、支持 `stopSeqId` 增量停。
- 角色按 `poolType`、武器按 `poolId`（重构池合并 `pool_ids` 一次拉）——与我们 `fetch_all_pools` 相同。
- 官方权威计数：`rerun-counts` 接口（角色重构 + 武器重构），字段 `totalPullCount` 按**抽数**计（注释原话「接口 totalPullCount 为抽数，本地一件=一抽」）。
- UP 名单：`/api/content`（`up6_id` / `up6_ids` / `up6_name`，特许寻访回退 `rotate_reward_item_list` 的「XX的信物」名）。
- 记录过滤：`filterStatisticalRecords` 剔除 `kind` 为 gift 的记录；免费抽（加急招募）计入总数与稀有度、**不计保底**，且官方累计计数里也不含加急十连——全部与我们一致。

## 三、计算层要点

- 按池类型分派：特许（全局小保底 80 跨池共享 + 每池 120 UP）/ 重构（80 小保底组内共享，120 UP 跨版本继承，用官方计数）/ 辉光 / 基础 / 启程 / 武器。
- 武器 `analyzeWeaponPoolData`：小保底垫抽从最新往回数付费抽遇 6★ 停；重构池 `poolVersion` 变化重置（与我们 `_pool_changed` 同款）；6★ 历史每条带「第 N 抽」。
- 大保底：`bigPityCount = 该池累计抽数 totalPulls`（按池开局计，出 UP 即归零显示「已获得当期 UP」）；重构池优先官方累计值；`resolveBigPity` 里 `gotUp6 → count=0`。

## 四、武器 UI 逻辑（weapon.vue，对我们最有参考价值）

- 左侧三个**类型组**（限定/重构/常驻，固定顺序），组内「全部卡池」聚合或单池下钻；
- **聚合视图隐藏保底**：`aggregatePools` 把 `pityCount` 置 0，模板 `v-if="!isAllSelected"`
  藏掉「当前已垫」与大保底徽标——各池独立保底无法合并展示，**与我们「合并列不显示已垫」的结论一致**；
- 聚合视图的 6★ 记录**显示所属申领名**（`isAllSelected && rec.poolName`）——与我们「不显示申领名」相反，属产品取舍；
- 6★ 行进度条：原始抽数 `pity / 40`，无十连单位；UP 橙条、歪黄条；
- 重构申领本地 < 服务器累计时显示差值警告条（90 天前的历史官方不保留）。

## 五、保底数字裁决（本次分析的核心产出）

**武器申领 = 6★ 基础 4% + 小保底 40（必得 6★，仅 25% 为 UP，40 抽后概率递增）+
大保底 80（必得当期 UP）+ 100 抽累计自选常驻 6★（奖励，非保底）。**

| 证据 | 内容 |
|---|---|
| 工具常量 | `WEAPON_SMALL_PITY_MAX=40` / `WEAPON_BIG_PITY_MAX=80`（gachaCalc.ts:24-25） |
| 工具注释 | weapon.vue:352「所有武器池均有 80 抽 UP 大保底」；gachaApi.ts:495「累计申领次数与 **8 次**大保底同源」（官方计数接口即按此口径设计） |
| README | 「重构申领的 80 抽当期 UP 大保底跨版本继承并以服务器累计为准」 |
| 公开公示 | 6★ 基础 4%（角色池 0.8%）；40 抽必出 6★（25% UP）；80 抽必得 UP；100 抽送 6★ 常驻自选；UP 后每 100 抽再得一个非 UP 6★ |

**本地真实记录实测**（3 账号 4 个武器池，`probe_real_weapon_stats.py`）：

- 武器池 60 抽出 5 个 6★（8.3%/抽），角色池 630 抽出 11 个（1.7%/抽）——都是公示基础率的
  ~2 倍（软保底抬升 + 小样本），**武器池出货率是角色池的 ~5 倍，用户「十连容易出 6★」的体感成立**；
- 4 个池最多只抽到 20 抽、全部没出过 UP，无法实测保底距离；
- 无 gift 记录（没人到累计档位），官方接口也无规则文案字段，保底数字只能靠外部口径。

**用户体感对账**：「保底时一般 4 个以上 6★」与 80 抽大保底吻合（两个 40 抽窗口各保底 1 个
+ 4% 随机 + 概率递增，期望 3~5 个）；「第十次十连保底 UP」是 100 抽累计自选奖励的误记。
2026-11-16 用户拍板按 40/80 执行，包侧常量已改回
（`SMALL_PITY_WEAPON=40` / `BIG_PITY_WEAPON=80`，见《抽卡-武器申领合并列-交接.md》）。

## 六、对我们包的启发（未实施，备查）

1. **聚合视图 + 单池下钻**：它的「类型组 → 全部/单池」两级结构比我们单列信息更全；若以后想要武器单池视角，可考虑在武器列加下钻，宿主要加通用交互（暂不做）。
2. **100 抽累计自选进度**：可在武器列加一行「累计 X/100 → 自选常驻 6★」，纯包侧可算（该池累计抽数），用户记忆中的「100」归位（暂不做）。
3. **UP 率 25%**：武器池歪是常态（75%），UP/歪判定对武器列比角色列更有价值——我们的按池 up_map 判定方向正确。

## 七、来源

- 本地仓库：`D:/Work/Github/Endfield/endfield-gacha-master`（v0.7.2）
- 公开资料（保底/概率公示）：[TapTap](https://www.taptap.cn/moment/762693394450353551)、[知乎·抽卡机制解析](https://zhuanlan.zhihu.com/p/2000314234177868791)、[17173·抽卡机制与概率说明](https://news.17173.com/z/arknights2026/content/01222026/114910311.shtml)、[draw.market·新手卡池规则](https://draw.market/zh/blog/arknights-endfield-beginner-gacha-rules-and-team-composition-guide.html)、[NGA·武器池概率讨论](https://bbs.nga.cn/read.php?tid=46133862)、[知乎·另一篇机制说明](https://zhuanlan.zhihu.com/p/1978084655514293245)、[gamekee](https://www.gamekee.com/zmd/690819.html)
- 实测数据：本地缓存 3 账号真实记录（`src/Arietta/gamepacks/arknights-endfield/gacha-*.json`），探针 `build-out/probe_real_weapon_stats.py`
