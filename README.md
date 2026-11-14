# Arknights: Endfield · Arietta Game Pack

[明日方舟：终末地](https://www.endfield.hypergryph.com/) 的 [Arietta](https://github.com/PaperKito/Arietta) 游戏包：让 Arietta 直接启动终末地、拉取寻访记录、修改游戏设置、浏览社区面板。

## 安装

- Arietta 内置「浏览并下载」（尚未发布时）：设置 → 游戏包，选中后一键安装；
- 手动：把本仓库 Release 里的 `arknights-endfield-<version>.zip` 解压到 `<Arietta 数据目录>/games/arknights-endfield/`。

## 包内文件

| 文件 | 作用 |
| --- | --- |
| `game.json` | 清单：描述、启动方式、能力声明、设置表 |
| `provider.py` | 寻访记录数据源进程（协议 1，仅 Python 标准库，请求鹰角官方接口） |
| `ui/community.html` | 社区面板（WebView 容器由宿主提供） |
| `icon.png` | 游戏图标 |
| `signature.json` | 作者签名，防冒名与改包 |

## 能力

启动（含父进程校验绕过）· 寻访记录 · 游戏设置（注册表）· 社区面板。

## 验签

```bash
dotnet run --project tools/GamePackSign -- verify <包目录>
```

签名算法 ecdsa-p256-sha256，作者 `PaperKito`，publicKey（SPKI base64）：

```
MFkwEwYHKoZIzj0CAQYIKoZIzj0DAQcDQgAEusHnM9Pd0y8Vp+91s0jJjVuHVmi7zU1Ni75Lj+soul6IMJ9/1EN7ng7F1EHU4jEoWo2rxUKEnjFcRI8DbgVYcQ==
```

改动包内任何文件都会验不过；zip 以 Release 为准，hash 见 Release 说明。
