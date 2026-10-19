# 执行命令与定位流程

下列 `<技能目录>`、`<游戏目录>`、`<工作目录>` 都要替换为实际路径。带空格的路径始终加引号。工作目录放在游戏安装目录之外。

## 环境

使用已有 Python 环境，或在工作目录创建独立环境：

```text
python -m venv "<工作目录>/.venv"
<独立环境的python> -m pip install -r "<技能目录>/scripts/requirements.txt"
python "<技能目录>/scripts/prepare_tools.py" --out "<工作目录>/tools"
```

Windows 的独立环境 Python 通常位于 `.venv/Scripts/python.exe`，Linux 位于 `.venv/bin/python`。后续命令使用装好依赖的同一个 Python。FFmpeg 用系统现有安装或官方项目提供的构建；下载助手只处理 wwiser、vgmstream。

## 当前索引

```text
python "<技能目录>/scripts/endfield_audio.py" index --game "<游戏目录>" --out "<工作目录>/index"
```

查看 `audio_index.json` 中的版本、PCK 数量、实际 CHK 路径和媒体数。若目标来自新版本且当前没有相应事件，先核对游戏更新状态。

## 名称 → 事件 → 音乐

```text
python "<技能目录>/scripts/endfield_audio.py" bank --game "<游戏目录>" --event au_music_map02_lv010_exploring_scroll_p2 --out "<工作目录>/events"
python "<工作目录>/tools/wwiser.pyz" -d xml -dn "<工作目录>/event_dump" "<工作目录>/events/<银行ID>.bnk"
```

这是示例事件，实际任务换成用户提供的名字或共有主体。若事件银行里只有 Action / SetState，读出状态组和值，再查引用它们的音乐控制银行：

```text
python "<技能目录>/scripts/endfield_audio.py" scan-banks --game "<游戏目录>" --contains-u32 <状态组ID> --contains-u32 <状态值ID> --match-all --out "<工作目录>/related-banks"
```

对相关 BNK 运行 wwiser。需要核对的字段包括：

- `CAkEvent` 引用的 Action。
- Action 类型和实际状态组 / 状态值；不要根据十六进制里的某个整数猜字段。
- `CAkMusicSwitchCntr` 的 `Arguments` 与 `AkDecisionTree`；按状态组次序查分支，取 `audioNodeId`。
- `CAkMusicRanSeqCntr` 中 `SegmentID` / `ulChildID`。
- `CAkMusicSegment` 的子音轨。
- `CAkMusicTrack` 的 `sourceID`、裁切、播放起点、原始时长。

音乐可能是随机播放列表、多段拼接或多音轨叠加。不要把列表中第一个 WEM 无条件当整首音乐。需要还原编排时用 wwiser 生成 TXTP，再按它的播放关系解码。

## 无编号：参考与候选

参考片段来源包括但不限于网络视频片段（如B站）、玩家自行录制的游戏视频或录屏片段，以及玩家自行录制或提供的音频片段。网络参考可提供链接，本地参考可直接提供视频或音频文件。先选取或提取其中的目标音乐，再与本地候选音轨做音频比对。

标准 Bilibili BV 链接可用下面的 `reference` 命令；其他网络视频按可用工具处理。本地录屏或音频可直接用于后面的 `compare --reference`，FFmpeg 会读取其中的声音。

```text
python "<技能目录>/scripts/audio_match.py" reference --url "https://www.bilibili.com/video/BVxxxxxxxxxx/?p=10" --out "<工作目录>/references"
python "<技能目录>/scripts/music_catalog.py" --game "<游戏目录>" --out "<工作目录>/catalog" --wwiser "<工作目录>/tools/wwiser.pyz" --duration 169 --tolerance 2
```

`reference` 获取元数据和默认最长90秒的低采样率对比片段；访问失败时改用用户提供的本地参考。它的输出只用于核对，不能作为“从游戏本地提取”的交付音源。

`music_catalog.json` 包含 `segments` 和 `candidates`。检查 `source_ids`、片段时长与原始音源时长。上面的 `--duration 169` 仅适合已知整曲约169秒的参考。网络截取片段或玩家短录音的长度不能当作原曲总时长；这类情况省略 `--duration`，结合场景线索或分批声音匹配筛选。视频可能添加循环、剪掉前奏、淡出或变速；无候选时合理调整筛选方式，不能据此直接判不存在。

目录构建通过一个只含音乐元数据的临时 BNK 调用 wwiser；不会导出全量音乐。不同 Wwise 版本混在一起时会停止，需分别处理。

## 定向提取

```text
python "<技能目录>/scripts/endfield_audio.py" extract --game "<游戏目录>" --media "<媒体ID>=<文件名标签>" --out "<工作目录>/tracks" --vgmstream "<工作目录>/tools/vgmstream/vgmstream-cli.exe"
```

Linux 使用准备工具返回的可执行文件路径。多个目标重复传 `--media`；默认输出原始 WEM、WAV、320 kbps MP3。只需原始文件可用 `--formats wem`；只需 WAV 可用 `--formats wav`。`--ffmpeg` 可指定 FFmpeg 路径。

提取默认拒绝覆盖已有目标；确认是同一次任务的可替换结果时显式加 `--overwrite`。媒体 ID 若仅存在于 BNK 的内嵌 DIDX/DATA，而未出现在流式媒体索引中，此助手会明确报缺失；此时改用 wwiser / vgmstream 的 BNK 或 TXTP 读取路线，不要伪造一个流式来源。

## 声音核对

```text
python "<技能目录>/scripts/audio_match.py" compare --local "<提取的候选.wav>" --reference "<参考.wav>" --out "<工作目录>/comparison.json"
```

也可直接使用玩家自录的本地视频，例如选择录屏第10秒起的20秒进行比对：

```text
python "<技能目录>/scripts/audio_match.py" compare --local "<提取的候选.wav>" --reference "<玩家录屏.mp4>" --reference-start 10 --seconds 20 --out "<工作目录>/comparison.json"
```

可重复传 `--local` 和 `--reference` 形成比对矩阵。默认比较参考第5–65秒；不足60秒时使用剩余片段，至少需要5秒。可通过 `--reference-start` 和 `--seconds` 调整。

检查相关系数、对齐偏移和候选之间的差距。高相关支持这一段的声音匹配；没有全曲比对就不要写“全曲逐样本一致”。旁白、剪辑、变速时需要分段或人工核对，不能只看一个阈值。

交付前确认原始 WEM 已保存、解码成功、时长合理、来源清单完整，最后给玩家可直接打开的文件路径。
