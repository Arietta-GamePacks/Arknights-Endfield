# Arknights: Endfield · Arietta Game Pack

[明日方舟：终末地](https://www.endfield.hypergryph.com/) 的 [Arietta](https://github.com/PaperKito/Arietta) 游戏包：让 Arietta 直接启动终末地、拉取寻访记录、修改游戏设置、浏览社区面板。

## 安装

- Arietta 内置「浏览并下载」（尚未发布时）：设置 → 游戏包，选中后一键安装；
- 手动：把本仓库 Release 里的 `arknights-endfield-<version>.zip` 解压到 `<Arietta 数据目录>/games/arknights-endfield/`。

## 包内文件

| 文件 | 作用 |
| --- | --- |
| `game.json` | 清单：描述、启动方式、能力声明、设置表 |
| `provider.py` | 数据源进程（协议 1，仅 Python 标准库）：公告 / 寻访记录 / 抽卡统计 / 日志链接 |
| `gacha.py` | 终末地抽卡统计引擎：保底、UP / 歪、武库配额 → 通用渲染模型 |
| `ui/community.html` | 社区面板（WebView 容器由宿主提供） |
| `ui/gacha.html` | 寻访记录统计页（自带演示数据，可离线预览；宿主内走脚本桥同步） |
| `icon.png` | 游戏图标 |
| `signature.json` | 作者签名，防冒名与改包 |

## 能力

启动（含父进程校验绕过）· 寻访记录同步与统计 · 游戏设置（注册表）· 社区面板 · 公告。

## 寻访记录

在 Arietta 左侧「寻访记录」打开统计页（角色池 / 武器池、垫抽与大小保底、6★ 历史、UP / 歪、武库配额）。第一次使用二选一：

- 粘贴鹰角账号 token（浏览器登录用户中心后，从账号信息接口复制整段内容）；
- 或点「读取本地日志」：先在游戏内打开一次寻访记录页，客户端会把带短期凭证的链接写进 SDK 日志，包自动读取。

点「更新记录」拉取全量记录并缓存在宿主数据目录（不写进包目录，避免破坏签名）。统计口径见 `gacha.py` 文件头；直接双击 `ui/gacha.html` 可用内置演示数据离线预览界面。

## 验签

```bash
dotnet run --project tools/GamePackSign -- verify <包目录>
```

签名算法 ecdsa-p256-sha256，作者 `PaperKito`，publicKey（SPKI base64）：

```
MFkwEwYHKoZIzj0CAQYIKoZIzj0DAQcDQgAEusHnM9Pd0y8Vp+91s0jJjVuHVmi7zU1Ni75Lj+soul6IMJ9/1EN7ng7F1EHU4jEoWo2rxUKEnjFcRI8DbgVYcQ==
```

改动包内任何文件都会验不过；zip 以 Release 为准，hash 见 Release 说明。
