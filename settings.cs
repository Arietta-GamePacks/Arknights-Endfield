// 终末地 · 设置模型 provider（C#）。
// 架构红线（AGENTS.md 2026-11-15）：宿主零游戏语义——键名、枚举、联动、GPU 过滤全部在本文件。
// 协议：stdin 一行 JSON 请求 → stdout 一行 JSON 响应 → 退出（docs/游戏包-Provider协议-交接.md）。
// 编译：build.cmd（单文件 exe，框架依赖 .NET 10 运行时；键值按原类型写回，由宿主执行写入）。
//
// 键名来源：HKCU\Software\Hypergryph\Endfield 本机实测（271 个值，见
// docs/Collapse-终末地插件-调查与画面设置预览-交接.md），Unity PlayerPrefs 哈希键名。
// 枚举来源：Collapse Hypergryph 插件目录 + 本机实测校正（scene_detail=3000 档插件目录缺失）。
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
        _ => throw new InvalidOperationException($"未知方法：{method}"),
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
    response["error"] = new Dictionary<string, object?> { ["message"] = error ?? "provider 失败。" };
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

    // 分辨率预设：勾选自定义分辨率（Use Native=0）之外的常用档；选中即写宽/高并清原生标志
    var presets = new (long w, long h)[] { (3840, 2160), (2560, 1440), (1920, 1080), (1600, 900), (1280, 720) };
    var presetOptions = presets.Select(p => Opt(p.w, $"{p.w} × {p.h}", new Dictionary<string, long>
    {
        ["Screenmanager Resolution Height_h2627697771"] = p.h,
        ["Screenmanager Resolution Use Native_h1405027254"] = 0,
    })).ToList();

    var display = Group(0, "分辨率", new List<object?>
    {
        // Unity FullScreenMode：0 独占 / 1 无边框 / 3 窗口；启动器只提供全屏（写 1）与窗口（写 3）
        Toggle("Screenmanager Fullscreen mode_h3630240806", "全屏", on: 1, off: 3),
        Toggle("Screenmanager Resolution Use Native_h1405027254", "自定义分辨率", on: 0, off: 1),
        Choice("Screenmanager Resolution Width_h182942802", "分辨率", presetOptions),
        Number("Screenmanager Resolution Width_h182942802", "宽度", 640, 7680,
            enabledWhen: ("Screenmanager Resolution Use Native_h1405027254", 0)),
        Number("Screenmanager Resolution Height_h2627697771", "高度", 480, 4320,
            enabledWhen: ("Screenmanager Resolution Use Native_h1405027254", 0)),
    });

    var quality = Group(0, "画质设置", new List<object?>
    {
        Choice("video_quality_main_h2648490162", "画质预设", new List<Dictionary<string, object?>>
        {
            Opt(1, "极高"), Opt(2, "高"), Opt(3, "中"), Opt(4, "低"), Opt(5, "极低"),
        }, writes: customWriteOff),
        Choice("video_frame_rate_8_h697513772", "帧率上限", new List<Dictionary<string, object?>>
        {
            Opt(1000, "120 FPS"), Opt(2000, "60 FPS"), Opt(3000, "30 FPS"),
        }),
    });

    var language = Group(0, "语言设置", new List<object?>
    {
        Choice("language_text_change_h1448997164", "文字语言", new List<Dictionary<string, object?>>
        {
            Opt(0, "简体中文"), Opt(4, "繁體中文"), Opt(8, "Deutsch"), Opt(12, "English"),
            Opt(16, "Español"), Opt(20, "Français"), Opt(24, "Bahasa Indonesia"), Opt(28, "Italiano"),
            Opt(32, "日本語"), Opt(36, "한국어"), Opt(40, "Português (Brasil)"), Opt(44, "Русский"),
            Opt(48, "ภาษาไทย"), Opt(52, "Tiếng Việt"),
        }),
        Choice("language_audio_h2756590110", "语音语言", new List<Dictionary<string, object?>>
        {
            Opt(1, "中文"), Opt(2, "English"), Opt(3, "日本語"), Opt(4, "한국어"),
        }),
    });

    // ── 右列 ────────────────────────────────────────────────

    const string upscalerKey = "video_quality_upscaler_2_h1962157691";
    const string framegenKey = "video_quality_framegen_1_h428217478";

    var details = Group(1, "画质细项", new List<object?>
    {
        Choice("video_quality_anisoLevel_1_h3121203451", "各向异性采样", new List<Dictionary<string, object?>>
        {
            Opt(1000, "1x"), Opt(2000, "2x"), Opt(3000, "4x"), Opt(4000, "8x"),
        }, writes: customWriteOn),
        Choice("video_quality_scene_detail_1_h1593605959", "场景细节", new List<Dictionary<string, object?>>
        {
            Opt(1000, "极高"), Opt(2000, "高"), Opt(3000, "中"), Opt(4000, "低"),
        }, writes: customWriteOn),
        Choice("video_quality_effect_1_h2848831456", "特效质量", new List<Dictionary<string, object?>>
        {
            Opt(1000, "极高"), Opt(2000, "高"), Opt(3000, "中"), Opt(4000, "低"),
        }, writes: customWriteOn),
        Toggle("video_quality_vsync_v2_2_h1194426206", "垂直同步", on: 1, off: 0, writes: customWriteOn),
        Choice("video_quality_shadowmap_1_h128234669", "阴影", new List<Dictionary<string, object?>>
        {
            Opt(1000, "高"), Opt(2000, "中"), Opt(3000, "低"), Opt(4000, "极低"),
        }, writes: customWriteOn),
        Choice("video_texture_quality_1_h3061223496", "纹理", new List<Dictionary<string, object?>>
        {
            Opt(2000, "中"), Opt(3000, "低"),
        }, writes: customWriteOn),
        Choice("video_quality_volumetricfog_1_h4151020765", "体积雾", new List<Dictionary<string, object?>>
        {
            Opt(1000, "极高"), Opt(2000, "中"), Opt(5000, "关闭"),
        }, writes: customWriteOn),
        Choice("video_quality_volumetriccloud_1_h4135137794", "体积云", new List<Dictionary<string, object?>>
        {
            Opt(1000, "极高"), Opt(3000, "中"), Opt(5000, "极低"),
        }, writes: customWriteOn),
        Choice("video_quality_ao_1_h2648627865", "环境光遮蔽", new List<Dictionary<string, object?>>
        {
            Opt(1000, "高"), Opt(3000, "低"), Opt(4000, "极低"),
        }, writes: customWriteOn),
        Choice("video_quality_environment_renderfeature_1_h2552402819", "环境细节", new List<Dictionary<string, object?>>
        {
            Opt(1000, "高"), Opt(3000, "低"),
        }, writes: customWriteOn),
        Choice("video_quality_grass_sparsity_1_h587916507", "植被密度", new List<Dictionary<string, object?>>
        {
            Opt(1000, "高"), Opt(2000, "低"),
        }, writes: customWriteOn),
        Toggle("video_quality_chromatic_aberration_1_h1000454999", "色差", on: 1000, off: 0, writes: customWriteOn),
        Choice("video_quality_screenspacereflection_1_h1017734168", "屏幕空间反射", new List<Dictionary<string, object?>>
        {
            Opt(1000, "极高"), Opt(4000, "低"), Opt(5000, "关闭"),
        }, writes: customWriteOn),
        Toggle("video_quality_contactshadow_1_h2952688721", "接触阴影", on: 1000, off: 0, writes: customWriteOn),
    });

    // 画质提升决定「模式」行：DLSS → DLSS 模式，FSR 3 → FSR 模式，TAAU → 无；
    // 帧生成 = DLSS 时出现 DLSS 帧生成模式；Reflex 整行只在 N 卡上出现。
    var upscalerOptions = new List<Dictionary<string, object?>>();
    if (nvidia)
    {
        upscalerOptions.Add(Opt(1000, "DLSS"));
    }
    upscalerOptions.Add(Opt(2000, "TAAU"));
    upscalerOptions.Add(Opt(3000, "AMD FSR 3"));

    var framegenOptions = new List<Dictionary<string, object?>> { Opt(1000, "关闭") };
    if (nvidia)
    {
        framegenOptions.Add(Opt(2000, "DLSS"));
    }
    framegenOptions.Add(Opt(3000, "FSR 3"));

    var upscalingRows = new List<object?>
    {
        Choice(upscalerKey, "画质提升", upscalerOptions, writes: customWriteOn),
        Choice("video_quality_fsr3_mode_1_h3089342015", "FSR 模式", new List<Dictionary<string, object?>>
        {
            Opt(1000, "超高性能"), Opt(2000, "高性能"), Opt(3000, "平衡"), Opt(4000, "高质量"), Opt(5000, "原生 AA"),
        }, visibleWhen: (upscalerKey, 3000), writes: customWriteOn),
        Slider("video_quality_sharpness_1_h923865732", "锐化程度", 0, 1, 0.1, 1000, writes: customWriteOn),
        Choice(framegenKey, "帧生成", framegenOptions, writes: customWriteOn),
    };
    if (nvidia)
    {
        upscalingRows.Add(Choice("video_quality_dlss_mode_1_h833809667", "DLSS 模式", new List<Dictionary<string, object?>>
        {
            Opt(1000, "超级性能"), Opt(2000, "性能"), Opt(3000, "平衡"), Opt(4000, "质量"), Opt(5000, "DLAA"),
        }, visibleWhen: (upscalerKey, 1000), writes: customWriteOn, defaultValue: 4000));
        upscalingRows.Add(Choice("video_quality_dlssg_mode_1_h1229296740", "DLSS 帧生成模式", new List<Dictionary<string, object?>>
        {
            Opt(1000, "自动"), Opt(2000, "2×"), Opt(3000, "3×"), Opt(4000, "4×"),
        }, visibleWhen: (framegenKey, 2000), writes: customWriteOn));
        upscalingRows.Add(Choice("video_quality_reflex_1_h358679639", "NVIDIA Reflex", new List<Dictionary<string, object?>>
        {
            Opt(1000, "关闭"), Opt(2000, "开启"), Opt(3000, "开启 + 增强"),
        }, writes: customWriteOn));
    }
    if (nvidia)
    {
        upscalingRows.Add(Choice("video_quality_reflex_1_h358679639", "NVIDIA Reflex", new List<Dictionary<string, object?>>
        {
            Opt(1000, "关闭"), Opt(2000, "开启"), Opt(3000, "开启 + 增强"),
        }, writes: customWriteOn));
    }
    var upscaling = Group(1, "超分辨率与帧生成", upscalingRows);

    return new Dictionary<string, object?>
    {
        ["store"] = StorePath,
        ["groups"] = new List<object?> { display, quality, language, details, upscaling },
    };
}

// ── 行构造 ──────────────────────────────────────────────────

static Dictionary<string, object?> Group(int column, string label, List<object?> rows) => new()
{
    ["column"] = column,
    ["label"] = label,
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
};

static Dictionary<string, object?> Opt(long value, string label, Dictionary<string, long>? writes = null)
{
    var option = new Dictionary<string, object?> { ["value"] = value, ["label"] = label };
    if (writes is not null)
    {
        option["writes"] = writes;
    }
    return option;
}

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

static Dictionary<string, object?> Choice(string key, string label, List<Dictionary<string, object?>> options,
    (string key, long value)? visibleWhen = null, (string key, long value)? enabledWhen = null,
    Dictionary<string, long>? writes = null, long? defaultValue = null)
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
    return row;
}

static Dictionary<string, object?> Number(string key, string label, long min, long max,
    (string key, long value)? enabledWhen = null)
{
    var (value, found) = Read(key);
    if (!found)
    {
        value = 0;
    }
    var row = Row(key, label, "number", found, value);
    row["min"] = min;
    row["max"] = max;
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
