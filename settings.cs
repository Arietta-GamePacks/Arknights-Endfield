// 终末地 · 设置模型 provider（C#）。
// 架构红线（AGENTS.md 2026-11-15）：宿主零游戏语义——键名、枚举、联动、GPU 过滤全部在本文件。
// 协议：stdin 一行 JSON 请求 → stdout 一行 JSON 响应 → 退出（docs/游戏包-Provider协议-交接.md）。
// 编译：build.cmd（单文件 exe，框架依赖 .NET 10 运行时；键值按原类型写回，由宿主执行写入）。
//
// 键名来源：HKCU\Software\Hypergryph\Endfield 本机实测（271 个值，见
// docs/Collapse-终末地插件-调查与画面设置预览-交接.md），Unity PlayerPrefs 哈希键名。
// 枚举来源：Collapse Hypergryph 插件目录 + 本机实测校正（scene_detail=3000 档插件目录缺失）。
using System.IO;
using System.Runtime.InteropServices;
using System.Text.Json;
using Microsoft.Win32;

const string StorePath = @"HKCU\Software\Hypergryph\Endfield";
const string RegistryPath = @"Software\Hypergryph\Endfield";

// 画质细项改动会把 video_custom_quality 置 1，改画质预设置 0（游戏联动，与 Collapse 插件一致）
const string CustomKey = "video_custom_quality_h2367254986";

string? request;
try
{
    request = Console.ReadLine();
}
catch (Exception ex)
{
    Fail(ex.Message);
    return 0;
}
if (string.IsNullOrWhiteSpace(request))
{
    Fail("没有收到请求。");
    return 0;
}

string method = "";
int id = 1;
object? result = null;
bool ok = true;
string? error = null;
try
{
    using var document = JsonDocument.Parse(request);
    var root = document.RootElement;
    if (root.TryGetProperty("id", out var idElement) && idElement.ValueKind == JsonValueKind.Number)
    {
        id = idElement.GetInt32();
    }
    if (root.TryGetProperty("method", out var methodElement))
    {
        method = methodElement.GetString() ?? "";
    }
    // 宿主 RunProviderAsync 注入的界面语言 tag（GamePack.LanguageTagFor）在 params.ui_lang；
    // 未知 / 缺省回落 zh-Hans
    if (root.TryGetProperty("params", out var paramsEl)
        && paramsEl.ValueKind == JsonValueKind.Object
        && paramsEl.TryGetProperty("ui_lang", out var langElement)
        && langElement.ValueKind == JsonValueKind.String)
    {
        L10n.SetLang(langElement.GetString() ?? "");
    }

    result = method switch
    {
        "ping" => new Dictionary<string, object?>
        {
            ["pack"] = "arknights-endfield",
            ["protocol"] = 1,
            ["version"] = "1.1.0",
            ["capabilities"] = new[] { "settings" },
        },
        "settings-model" => BuildModel(),
        _ => throw new InvalidOperationException(L10n.T("s.err.unknownMethod", method)),
    };
}
catch (Exception ex)
{
    ok = false;
    error = ex.Message;
}

var response = new Dictionary<string, object?> { ["id"] = id, ["ok"] = ok };
if (ok)
{
    response["result"] = result;
}
else
{
    response["error"] = new Dictionary<string, object?> { ["message"] = error ?? L10n.T("s.err.failed") };
}
Console.WriteLine(JsonSerializer.Serialize(response));
return 0;

void Fail(string message)
{
    Console.WriteLine(JsonSerializer.Serialize(new Dictionary<string, object?>
    {
        ["id"] = 1,
        ["ok"] = false,
        ["error"] = new Dictionary<string, object?> { ["message"] = message },
    }));
}

Dictionary<string, object?> BuildModel()
{
    bool nvidia = HasNvidia();
    var customWriteOn = new Dictionary<string, long> { [CustomKey] = 1 };
    var customWriteOff = new Dictionary<string, long> { [CustomKey] = 0 };

    // ── 左列 ────────────────────────────────────────────────

    // 分辨率预设：游戏的下拉列表不是固定表，而是**本机显示器枚举出来的模式**去重后按宽降序、同宽再按高降序
    // （2026-11-16 实测：4K 屏 EnumDisplaySettings 输出的 22 档与游戏下拉逐项、逐序一致，
    //  顶部止于 3840×2160 —— 8K 档只在 8K 显示器上才出现）。所以运行期枚举，换显示器列表自动跟着变。
    // 别往这里补显示器不报的档（超采样 / 8K 私货）：宿主 GameSettingService.FilterByMonitor 的口径就是
    // 「只列显示器支持的模式，原生分辨率兜底」，设置页必须同一个口径，否则等于给用户一个选不了的档。
    // 列表里同一个宽度出现多次（1920×2 / 1600×2 / 1280×3），宿主 choice 只按 option.value 匹配行值，
    // 所以行值用「宽×10000+高」的合成槽位区分同宽档位，选中后由 option.writes 把真实宽高写回两个键。
    const string widthKey = "Screenmanager Resolution Width_h182942802";
    const string heightKey = "Screenmanager Resolution Height_h2627697771";
    // 游戏并存两套分辨率：Screenmanager 一套、video_resolution 一套，改档时要一起写（见 Collapse 调查文档）
    const string videoWidthKey = "video_resolution_width_h583690364";
    const string videoHeightKey = "video_resolution_height_h2517654917";

    var presets = DisplayModes();
    if (presets.Count == 0)
    {
        // 枚举不到（远程桌面 / 无显示设备）时退回常用档，保证下拉不是空的
        presets = new List<(long W, long H)> { (3840, 2160), (2560, 1440), (1920, 1080), (1600, 900), (1280, 720) };
    }
    var presetOptions = presets.Select(p => Opt(Slot(p.W, p.H), $"{p.W}×{p.H}", new Dictionary<string, long>
    {
        [widthKey] = p.W,
        [heightKey] = p.H,
        [videoWidthKey] = p.W,
        [videoHeightKey] = p.H,
    })).ToList();

    var currentWidth = Read(widthKey).Value;
    var currentHeight = Read(heightKey).Value;
    // 当前档位以游戏自己那套 video_resolution_* 为准：全屏时 Unity 的 Screenmanager 宽高会被游戏改成桌面分辨率
    // （本机实测：全屏渲染 2560×1440 时 Screenmanager=3840×2160，video_resolution=2560×1440）。
    var videoW = Read(videoWidthKey);
    var videoH = Read(videoHeightKey);
    if (videoW.Value > 0 && videoH.Value > 0)
    {
        currentWidth = videoW.Value;
        currentHeight = videoH.Value;
    }
    // 「自定义分辨率」是**派生状态**：游戏里没有对应的持久键（`Use Native` 是引擎的"用桌面原生分辨率"，
    // 窗口模式下必然写 0，不能当自定义标志 —— 实测窗口启动后它就是 0）。
    // 所以用 UI 态行：当前宽高不在档位表里 → 勾上；它只决定「用下拉还是手填」，不写注册表。
    const string customUiKey = "ui:custom-resolution";
    var isCustom = !presets.Any(p => p.W == currentWidth && p.H == currentHeight);
    var customRow = new Dictionary<string, object?>
    {
        ["key"] = customUiKey,
        ["label"] = L10n.T("s.row.customRes"),
        ["control"] = "check",
        ["value"] = isCustom ? 1L : 0L,
        ["exists"] = true,
        ["on"] = 1L,
        ["off"] = 0L,
        ["uiOnly"] = true,
        ["exclusiveGroup"] = "display",
        ["hint"] = L10n.T(isCustom ? "s.hint.customOut" : "s.hint.customIn", currentWidth, currentHeight),
    };
    // 状态机跟鸣潮不一样：**全屏下也能选预设分辨率**（全屏 = 无边窗口铺满屏幕，渲染分辨率另算，
    // 游戏里 2K 全屏就是这么来的）。所以只按「自定义分辨率」区分：
    // 不勾 → 预设下拉可交互（全屏=改渲染分辨率，窗口=改窗口尺寸）；勾上 → 只留宽高输入。
    // 选中档位只写宽高两套键、**不动 Use Native 也不动全屏模式**，否则选完自己就把自己锁灰 / 强切窗口。
    var presetRow = Choice(widthKey, "", presetOptions,
        enabledWhenAll: Conditions((customUiKey, 0L)));
    // 行值换成合成槽位，下拉才能高亮到「1920×1200」而不是同宽的第一档「1920×1080」
    presetRow["value"] = Slot(currentWidth, currentHeight);
    presetRow["hint"] = L10n.T("s.hint.preset", currentWidth, currentHeight,
        widthKey, heightKey, videoWidthKey, videoHeightKey);

    var display = Group(0, L10n.T("s.grp.display"), new List<object?>
    {
        // Unity FullScreenMode：0 独占 / 1 无边框 / 3 窗口；启动器只提供全屏（写 1）与窗口（写 3）
        // 结构与宿主内置 GameSettingPage 一致：两个方形勾选框 → 无标签分辨率下拉 → 宽 × 高 一行。
        // 与宿主内置 GameSettingPage 一样互斥：勾全屏清自定义，勾自定义切回窗口模式
        // 全屏开关绑游戏自己的 video_full_screen：Unity 的 Screenmanager Fullscreen mode 是运行时镜像，
        // 启动时由游戏按这个键回写（和分辨率那对 Screenmanager 键一样，写镜像没用）。
        // 取消全屏 = video_full_screen 0 = 窗口模式，窗口尺寸取 video_resolution_*（也就是上面选的预设）。
        Check("video_full_screen_h1998742411", L10n.T("s.row.fullscreen"), on: 1, off: 0, exclusiveGroup: "display"),
        customRow,
        presetRow,
        // 宽高输入只在「自定义分辨率」勾上时可编辑；数值镜像写到游戏自己的 video_resolution_*，
        // 否则只写 Unity 镜像键、下次启动会被游戏覆盖（宿主 mirrorTo 通用能力）
        Number(widthKey, "", 640, 7680,
            enabledWhenAll: Conditions((customUiKey, 1L)), join: "×", mirrorTo: new List<string> { videoWidthKey }),
        Number(heightKey, "", 480, 4320,
            enabledWhenAll: Conditions((customUiKey, 1L)), mirrorTo: new List<string> { videoHeightKey }),
    }, "stack");

    // 画质预设：custom_quality=1 时游戏下拉显示「自定义」，所以第一项就是它 ——
    // 选中只把标志置 1、底层档位原样保留；选具体档位才写档位并把标志清 0。
    // 档位枚举（1 极高 … 5 极低）来自 Collapse 插件目录 + 实测，本机 main=4 即「低」。
    const string qualityKey = "video_quality_main_h2648490162";
    var (qualityValue, _) = Read(qualityKey);
    var (customValue, _) = Read(CustomKey);
    var qualityRow = Choice(qualityKey, L10n.T("s.row.qualityPreset"), new List<Dictionary<string, object?>>
    {
        Opt(0, L10n.T("s.opt.custom"), new Dictionary<string, long> { [qualityKey] = qualityValue, [CustomKey] = 1 }),
        Opt(1, L10n.T("s.opt.ultra"), customWriteOff), Opt(2, L10n.T("s.opt.high"), customWriteOff),
        Opt(3, L10n.T("s.opt.medium"), customWriteOff),
        Opt(4, L10n.T("s.opt.low"), customWriteOff), Opt(5, L10n.T("s.opt.ultraLow"), customWriteOff),
    });
    // 行值换成 0 才能高亮到「自定义」；否则注册表里 main=4 会显示成「低」
    qualityRow["value"] = customValue == 1 ? 0 : qualityValue;

    var quality = Group(0, L10n.T("s.grp.quality"), new List<object?>
    {
        qualityRow,
        Choice("video_frame_rate_8_h697513772", L10n.T("s.row.fpsLimit"), new List<Dictionary<string, object?>>
        {
            Opt(1000, "120 FPS"), Opt(2000, "60 FPS"), Opt(3000, "30 FPS"),
        }),
    }, "stack");

    // 游戏内语言名（简体中文/English/日本語…）是 endonym，任何界面语言下原样显示，不进翻译表
    var language = Group(0, L10n.T("s.grp.language"), new List<object?>
    {
        Choice("language_text_change_h1448997164", L10n.T("s.row.textLang"), new List<Dictionary<string, object?>>
        {
            Opt(0, "简体中文"), Opt(4, "繁體中文"), Opt(8, "Deutsch"), Opt(12, "English"),
            Opt(16, "Español"), Opt(20, "Français"), Opt(24, "Bahasa Indonesia"), Opt(28, "Italiano"),
            Opt(32, "日本語"), Opt(36, "한국어"), Opt(40, "Português (Brasil)"), Opt(44, "Русский"),
            Opt(48, "ภาษาไทย"), Opt(52, "Tiếng Việt"),
        }),
        Choice("language_audio_h2756590110", L10n.T("s.row.audioLang"), new List<Dictionary<string, object?>>
        {
            Opt(1, "中文"), Opt(2, "English"), Opt(3, "日本語"), Opt(4, "한국어"),
        }),
    }, "stack", L10n.T("s.desc.langNote"));

    // ── 右列 ────────────────────────────────────────────────

    const string upscalerKey = "video_quality_upscaler_2_h1962157691";
    const string framegenKey = "video_quality_framegen_1_h428217478";

    var details = Group(1, L10n.T("s.grp.details"), new List<object?>
    {
        Choice("video_quality_anisoLevel_1_h3121203451", L10n.T("s.row.aniso"), new List<Dictionary<string, object?>>
        {
            Opt(1000, "1x"), Opt(2000, "2x"), Opt(3000, "4x"), Opt(4000, "8x"),
        }, writes: customWriteOn),
        Choice("video_quality_scene_detail_1_h1593605959", L10n.T("s.row.sceneDetail"), new List<Dictionary<string, object?>>
        {
            Opt(1000, L10n.T("s.opt.ultra")), Opt(2000, L10n.T("s.opt.high")),
            Opt(3000, L10n.T("s.opt.medium")), Opt(4000, L10n.T("s.opt.low")),
        }, writes: customWriteOn),
        Choice("video_quality_effect_1_h2848831456", L10n.T("s.row.effects"), new List<Dictionary<string, object?>>
        {
            Opt(1000, L10n.T("s.opt.ultra")), Opt(2000, L10n.T("s.opt.high")),
            Opt(3000, L10n.T("s.opt.medium")), Opt(4000, L10n.T("s.opt.low")),
        }, writes: customWriteOn),
        Toggle("video_quality_vsync_v2_2_h1194426206", L10n.T("s.row.vsync"), on: 1, off: 0, writes: customWriteOn),
        Choice("video_quality_shadowmap_1_h128234669", L10n.T("s.row.shadows"), new List<Dictionary<string, object?>>
        {
            Opt(1000, L10n.T("s.opt.high")), Opt(2000, L10n.T("s.opt.medium")),
            Opt(3000, L10n.T("s.opt.low")), Opt(4000, L10n.T("s.opt.ultraLow")),
        }, writes: customWriteOn),
        Choice("video_texture_quality_1_h3061223496", L10n.T("s.row.textures"), new List<Dictionary<string, object?>>
        {
            Opt(2000, L10n.T("s.opt.medium")), Opt(3000, L10n.T("s.opt.low")),
        }, writes: customWriteOn),
        Choice("video_quality_volumetricfog_1_h4151020765", L10n.T("s.row.volFog"), new List<Dictionary<string, object?>>
        {
            Opt(1000, L10n.T("s.opt.ultra")), Opt(2000, L10n.T("s.opt.medium")), Opt(5000, L10n.T("s.opt.off")),
        }, writes: customWriteOn),
        Choice("video_quality_volumetriccloud_1_h4135137794", L10n.T("s.row.volCloud"), new List<Dictionary<string, object?>>
        {
            Opt(1000, L10n.T("s.opt.ultra")), Opt(3000, L10n.T("s.opt.medium")), Opt(5000, L10n.T("s.opt.ultraLow")),
        }, writes: customWriteOn),
        Choice("video_quality_ao_1_h2648627865", L10n.T("s.row.ao"), new List<Dictionary<string, object?>>
        {
            Opt(1000, L10n.T("s.opt.high")), Opt(3000, L10n.T("s.opt.low")), Opt(4000, L10n.T("s.opt.ultraLow")),
        }, writes: customWriteOn),
        Choice("video_quality_environment_renderfeature_1_h2552402819", L10n.T("s.row.envDetail"), new List<Dictionary<string, object?>>
        {
            Opt(1000, L10n.T("s.opt.high")), Opt(3000, L10n.T("s.opt.low")),
        }, writes: customWriteOn),
        Choice("video_quality_grass_sparsity_1_h587916507", L10n.T("s.row.grass"), new List<Dictionary<string, object?>>
        {
            Opt(1000, L10n.T("s.opt.high")), Opt(2000, L10n.T("s.opt.low")),
        }, writes: customWriteOn),
        Toggle("video_quality_chromatic_aberration_1_h1000454999", L10n.T("s.row.chroma"), on: 1000, off: 0, writes: customWriteOn),
        Choice("video_quality_screenspacereflection_1_h1017734168", L10n.T("s.row.ssr"), new List<Dictionary<string, object?>>
        {
            Opt(1000, L10n.T("s.opt.ultra")), Opt(4000, L10n.T("s.opt.low")), Opt(5000, L10n.T("s.opt.off")),
        }, writes: customWriteOn),
        Toggle("video_quality_contactshadow_1_h2952688721", L10n.T("s.row.contactShadow"), on: 1000, off: 0, writes: customWriteOn),
    }, "compact");

    // 画质提升决定「模式」行：DLSS → DLSS 模式，FSR 3 → FSR 模式，TAAU → 无；
    // 帧生成 = DLSS 时出现 DLSS 帧生成模式；Reflex 整行只在 N 卡上出现。
    var upscalerOptions = new List<Dictionary<string, object?>>();
    if (nvidia)
    {
        upscalerOptions.Add(Opt(1000, "DLSS"));
    }
    upscalerOptions.Add(Opt(2000, "TAAU"));
    upscalerOptions.Add(Opt(3000, "AMD FSR 3"));

    var framegenOptions = new List<Dictionary<string, object?>> { Opt(1000, L10n.T("s.opt.off")) };
    if (nvidia)
    {
        framegenOptions.Add(Opt(2000, "DLSS"));
    }
    framegenOptions.Add(Opt(3000, "FSR 3"));

    var upscalingRows = new List<object?>
    {
        Choice(upscalerKey, L10n.T("s.row.upscaler"), upscalerOptions, writes: customWriteOn),
        Choice("video_quality_fsr3_mode_1_h3089342015", L10n.T("s.row.fsrMode"), new List<Dictionary<string, object?>>
        {
            Opt(1000, L10n.T("s.opt.ultraPerf")), Opt(2000, L10n.T("s.opt.perf")), Opt(3000, L10n.T("s.opt.balanced")),
            Opt(4000, L10n.T("s.opt.quality")), Opt(5000, L10n.T("s.opt.nativeAA")),
        }, visibleWhen: (upscalerKey, 3000), writes: customWriteOn),
        Slider("video_quality_sharpness_1_h923865732", L10n.T("s.row.sharpness"), 0, 1, 0.1, 1000, writes: customWriteOn),
        Choice(framegenKey, L10n.T("s.row.framegen"), framegenOptions, writes: customWriteOn),
    };
    if (nvidia)
    {
        upscalingRows.Add(Choice("video_quality_dlss_mode_1_h833809667", L10n.T("s.row.dlssMode"), new List<Dictionary<string, object?>>
        {
            Opt(1000, L10n.T("s.opt.ultraPerfDLSS")), Opt(2000, L10n.T("s.opt.perf")), Opt(3000, L10n.T("s.opt.balanced")),
            Opt(4000, L10n.T("s.opt.quality")), Opt(5000, "DLAA"),
        }, visibleWhen: (upscalerKey, 1000), writes: customWriteOn, defaultValue: 4000));
        upscalingRows.Add(Choice("video_quality_dlssg_mode_1_h1229296740", L10n.T("s.row.dlssFgMode"), new List<Dictionary<string, object?>>
        {
            Opt(1000, L10n.T("s.opt.auto")), Opt(2000, "2×"), Opt(3000, "3×"), Opt(4000, "4×"),
        }, visibleWhen: (framegenKey, 2000), writes: customWriteOn));
        upscalingRows.Add(Choice("video_quality_reflex_1_h358679639", "NVIDIA Reflex", new List<Dictionary<string, object?>>
        {
            Opt(1000, L10n.T("s.opt.off")), Opt(2000, L10n.T("s.opt.on")), Opt(3000, L10n.T("s.opt.onBoost")),
        }, writes: customWriteOn));
    }
    var upscaling = Group(1, L10n.T("s.grp.upscaling"), upscalingRows, "compact");

    return new Dictionary<string, object?>
    {
        ["store"] = StorePath,
        ["groups"] = new List<object?> { display, quality, language, details, upscaling },
    };
}

// ── 行构造 ──────────────────────────────────────────────────

// style 是宿主通用布局 token（list / flow / cards / compact），不含游戏语义：
// flow = 紧凑竖排、cards = 标签在上的三列、compact = 两列 kv 小控件网格。
static Dictionary<string, object?> Group(int column, string label, List<object?> rows, string style = "list",
    string description = "") => new()
{
    ["column"] = column,
    ["label"] = label,
    ["style"] = style,
    ["description"] = description,
    ["rows"] = rows,
};

static (long Value, bool Found) Read(string key)
{
    try
    {
        using var root = Registry.CurrentUser.OpenSubKey(RegistryPath);
        var raw = root?.GetValue(key);
        return raw switch
        {
            int i => (i, true),
            long l => (l, true),
            string s when long.TryParse(s, out var parsed) => (parsed, true),
            _ => (0, false),
        };
    }
    catch
    {
        return (0, false);
    }
}

static Dictionary<string, object?> Row(string key, string label, string control, bool found, long value) => new()
{
    ["key"] = key,
    ["label"] = label,
    ["control"] = control,
    ["value"] = value,
    ["exists"] = found,
    // 预览稿里每个控件悬停可见键名 / 实测值；宿主只把这串挂到 ToolTip 上。
    ["hint"] = found ? L10n.T("s.hint.found", key, value) : L10n.T("s.hint.missing", key),
};

// 分辨率档位槽位：宽×10000+高，只用于下拉匹配（真实写入由 option.writes 覆盖，不会落库）
static long Slot(long width, long height) => width * 10000 + height;

// 本机显示器支持的分辨率：EnumDisplaySettings 全量枚举（含每个刷新率），按 宽×高 去重，
// 排序宽降序 → 高降序，与游戏下拉完全一致。4K 屏止于 3840×2160，8K 屏顶部就是 7680×4320。
static List<(long W, long H)> DisplayModes()
{
    var seen = new HashSet<(long, long)>();
    var result = new List<(long W, long H)>();
    try
    {
        var mode = new DevMode { Size = (ushort)Marshal.SizeOf<DevMode>() };
        for (int i = 0; NativeDisplay.EnumDisplaySettings(null, i, ref mode); i++)
        {
            long w = mode.PelsWidth;
            long h = mode.PelsHeight;
            if (w < 640 || h < 400)
            {
                continue;
            }
            if (seen.Add((w, h)))
            {
                result.Add((w, h));
            }
        }
    }
    catch
    {
        // 枚举失败交由调用方回退到常用档
    }
    result.Sort((a, b) => a.W != b.W ? b.W.CompareTo(a.W) : b.H.CompareTo(a.H));
    return result;
}

static Dictionary<string, object?> Opt(long value, string label, Dictionary<string, long>? writes = null)
{
    var option = new Dictionary<string, object?> { ["value"] = value, ["label"] = label };
    if (writes is not null)
    {
        option["writes"] = writes;
    }
    return option;
}

// 多个条件同时成立（AND）才启用 / 显示；宿主通用协议里 enabledWhen 可以是数组
static List<Dictionary<string, object?>> Conditions(params (string key, long value)[] items)
    => items.Select(i => new Dictionary<string, object?> { ["key"] = i.key, ["value"] = i.value }).ToList();

static Dictionary<string, object?> Toggle(string key, string label, long on, long off,
    Dictionary<string, long>? writes = null, (string key, long value)? enabledWhen = null)
{
    var (value, found) = Read(key);
    if (!found)
    {
        value = off;
    }
    var row = Row(key, label, "toggle", found, value);
    row["on"] = on;
    row["off"] = off;
    if (writes is not null)
    {
        row["writes"] = writes;
    }
    if (enabledWhen is not null)
    {
        row["enabledWhen"] = new Dictionary<string, object?> { ["key"] = enabledWhen.Value.key, ["value"] = enabledWhen.Value.value };
    }
    return row;
}

// 方形勾选框（宿主内置游戏设置页同款），文字挂在控件自身
static Dictionary<string, object?> Check(string key, string label, long on, long off,
    Dictionary<string, long>? writes = null, string exclusiveGroup = "")
{
    var (value, found) = Read(key);
    if (!found)
    {
        value = off;
    }
    var row = Row(key, label, "check", found, value);
    row["on"] = on;
    row["off"] = off;
    if (writes is not null)
    {
        row["writes"] = writes;
    }
    if (!string.IsNullOrEmpty(exclusiveGroup))
    {
        row["exclusiveGroup"] = exclusiveGroup;
    }
    return row;
}

static Dictionary<string, object?> Choice(string key, string label, List<Dictionary<string, object?>> options,
    (string key, long value)? visibleWhen = null, (string key, long value)? enabledWhen = null,
    Dictionary<string, long>? writes = null, long? defaultValue = null,
    List<Dictionary<string, object?>>? enabledWhenAll = null)
{
    var (value, found) = Read(key);
    if (!found)
    {
        value = defaultValue ?? (options.Count > 0 ? (long)options[0]["value"]! : 0);
    }
    var row = Row(key, label, "choice", found, value);
    row["options"] = options;
    if (visibleWhen is not null)
    {
        row["visibleWhen"] = new Dictionary<string, object?> { ["key"] = visibleWhen.Value.key, ["value"] = visibleWhen.Value.value };
    }
    if (enabledWhen is not null)
    {
        row["enabledWhen"] = new Dictionary<string, object?> { ["key"] = enabledWhen.Value.key, ["value"] = enabledWhen.Value.value };
    }
    if (writes is not null)
    {
        row["writes"] = writes;
    }
    if (enabledWhenAll is not null)
    {
        row["enabledWhen"] = enabledWhenAll;
    }
    return row;
}

static Dictionary<string, object?> Number(string key, string label, long min, long max,
    (string key, long value)? enabledWhen = null, string? join = null,
    List<Dictionary<string, object?>>? enabledWhenAll = null, List<string>? mirrorTo = null)
{
    var (value, found) = Read(key);
    if (!found)
    {
        value = 0;
    }
    var row = Row(key, label, "number", found, value);
    row["min"] = min;
    row["max"] = max;
    // 同一数值额外写入的键（手填分辨率要同步游戏自己那套）
    if (mirrorTo is { Count: > 0 })
    {
        row["mirrorTo"] = mirrorTo;
    }
    if (enabledWhenAll is not null)
    {
        row["enabledWhen"] = enabledWhenAll;
    }
    if (join is not null)
    {
        row["join"] = join;
    }
    if (enabledWhen is not null)
    {
        row["enabledWhen"] = new Dictionary<string, object?> { ["key"] = enabledWhen.Value.key, ["value"] = enabledWhen.Value.value };
    }
    return row;
}

static Dictionary<string, object?> Slider(string key, string label, double min, double max, double step, double scale,
    Dictionary<string, long>? writes = null)
{
    var (value, found) = Read(key);
    if (!found)
    {
        value = (long)(min * scale);
    }
    var row = Row(key, label, "slider", found, value);
    row["min"] = min;
    row["max"] = max;
    row["step"] = step;
    row["scale"] = scale;
    if (writes is not null)
    {
        row["writes"] = writes;
    }
    return row;
}

// NVIDIA 专属行（DLSS / Reflex）靠这个判定；读不到显卡就按有处理，宁多勿缺
static bool HasNvidia()
{
    try
    {
        const string classKey = @"SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}";
        using var baseKey = Registry.LocalMachine.OpenSubKey(classKey);
        if (baseKey is null)
        {
            return true;
        }
        foreach (var sub in baseKey.GetSubKeyNames())
        {
            if (!int.TryParse(sub, out _))
            {
                continue;
            }
            using var key = baseKey.OpenSubKey(sub);
            if (key?.GetValue("DriverDesc") is string desc && desc.Contains("NVIDIA", StringComparison.OrdinalIgnoreCase))
            {
                return true;
            }
        }
        return false;
    }
    catch
    {
        return true;
    }
}

// ── Win32：显示器模式枚举 ──────────────────────────────────

// 只用到 dmSize / dmPelsWidth / dmPelsHeight，其余字段按 DEVMODEW 原样排列以保证偏移正确
// （类型声明必须写在顶级语句之后，CS8803）
[StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
struct DevMode
{
    [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 32)] public string DeviceName;
    public ushort SpecVersion, DriverVersion, Size, DriverExtra;
    public uint Fields;
    public int PositionX, PositionY;
    public uint DisplayOrientation, DisplayFixedOutput;
    public short Color, Duplex, YResolution, TTOption, Collate;
    [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 32)] public string FormName;
    public ushort LogPixels;
    public uint BitsPerPel, PelsWidth, PelsHeight, DisplayFlags, DisplayFrequency;
    public uint IcmMethod, IcmIntent, MediaType, DitherType, Reserved1, Reserved2, PanningWidth, PanningHeight;
}

static class NativeDisplay
{
    [DllImport("user32.dll", CharSet = CharSet.Unicode, EntryPoint = "EnumDisplaySettingsW")]
    internal static extern bool EnumDisplaySettings(string? deviceName, int modeNum, ref DevMode devMode);
}

// ── 用户可见文案翻译表 ──────────────────────────────────────
// 数据在 assets/l10n.json（与 l10n.py / gacha.py 共用同一份，键与占位符 {0}{1}… 同构）。
// 语言来自宿主 RunProviderAsync 注入的 params.ui_lang（GamePack.LanguageTagFor 的 tag）；
// 查表：当前语言 → zh-Hans（兜底）→ id 本身（表损坏时界面上直接暴露 id 定位）。
static class L10n
{
    static readonly Dictionary<string, Dictionary<string, string>>? Table;
    static string Lang = "zh-Hans";

    static L10n()
    {
        try
        {
            string path = Path.Combine(AppContext.BaseDirectory, "assets", "l10n.json");
            using var doc = JsonDocument.Parse(File.ReadAllText(path));
            if (doc.RootElement.TryGetProperty("strings", out var strings)
                && strings.ValueKind == JsonValueKind.Object)
            {
                var map = new Dictionary<string, Dictionary<string, string>>(StringComparer.Ordinal);
                foreach (var entry in strings.EnumerateObject())
                {
                    if (entry.Value.ValueKind != JsonValueKind.Object)
                    {
                        continue;
                    }
                    var langs = new Dictionary<string, string>(StringComparer.Ordinal);
                    foreach (var kv in entry.Value.EnumerateObject())
                    {
                        if (kv.Value.ValueKind == JsonValueKind.String)
                        {
                            langs[kv.Name] = kv.Value.GetString() ?? "";
                        }
                    }
                    map[entry.Name] = langs;
                }
                Table = map;
            }
        }
        catch
        {
            // 表缺失 / 损坏：T() 回落 zh-Hans 之外的最后一档是 id 本身，别让设置页起不来
            Table = null;
        }
    }

    public static void SetLang(string lang)
    {
        string tag = (lang ?? "").Trim();
        Lang = tag.Length == 0 ? "zh-Hans" : tag;
    }

    public static string T(string id, params object?[] args)
    {
        string text = id;
        if (Table is not null && Table.TryGetValue(id, out var entry))
        {
            text = entry.TryGetValue(Lang, out var value) && !string.IsNullOrWhiteSpace(value) ? value
                 : entry.TryGetValue("zh-Hans", out var zh) && !string.IsNullOrWhiteSpace(zh) ? zh
                 : id;
        }
        return args.Length == 0 ? text : string.Format(text, args);
    }
}
