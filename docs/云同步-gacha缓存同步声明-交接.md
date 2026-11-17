# 云同步-gacha缓存同步声明-交接

状态：已完成（2026-11-16）；宿主侧行为详见 Arietta 仓库 `docs/游戏包-数据云同步PackData-交接.md`。

## 背景

宿主 WebDAV 云同步（`AriettaSync/Arietta.db` 加密快照 + 行级合并）此前不含游戏包数据。
本次宿主新增通用能力：包在 game.json 里声明哪些数据文件搭同步的便车（进宿主库 `PackData`
表，按 UpdateTime 新者胜，墓碑传播删除）。

## 实现行为

game.json 新增一处声明（`src/Arietta/games/arknights-endfield/game.json` 已同步并重签）：

```jsonc
"sync": ["gacha-*.json"]
```

范围决策（用户拍板）：

- **gacha-*.json**（寻访缓存，按凭证指纹一账号一文件，`provider.py cache_key`）→ 同步。
  链接过期后本地就是唯一副本，值得跨设备；按账号一文件天然按账号粒度合并。
- **community.json**（森空岛凭证）→ 由宿主拆成按账号对象自行同步（token 进同步，过期就
  过期；账号取并集），**包不用声明**。
- **wiki 图标等可再生缓存** → 不声明 = 永远只留本机（用户明确：图库类缓存不可接受上云）。

## 实测结论

- DataLayerVerify 新增 PackData 段 8/8 通过（LWW 合并 / 墓碑传播 / 账号并集 / 幂等 / 指纹）。
- 宿主 Release 构建 0 错误。

## 验证方式 / 已知待办

- 端到端双机（同一 WebDAV）拉取验证待做；provider 侧零改动（`data_dir` 参数不变，文件被
  宿主还原回来后 provider 直接读盘）。
- 包作者约定：声明只写小体积、值得跨设备的数据文件；通配只支持 `*`（平目录）。
