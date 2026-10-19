# endfield-music-extractor-skill

终末地PC本地提取BGM

因为本人过于喜爱缘缘庄BGM遂做出本skill

给同样喜欢《明日方舟：终末地》游戏音乐的玩家。

可以把曲目编号、参考片段，或“在哪张地图、什么情景下响起”告诉 AI，让它从你自己的游戏安装目录中查找音乐。找到后保留原始 WEM，并导出 WAV、MP3；有参考片段时会进一步核对声音。

## 参考片段可以来自哪里

参考片段的来源包括但不限于：网络视频片段（如B站）、玩家自行录制的游戏视频或录屏片段，以及玩家自行录制或提供的音频片段。

你可以提供网络视频链接、本地视频文件或音频文件。AI 会先从片段中选取或提取目标音乐，再与本地游戏里的候选音轨做音频比对；没有曲目编号也可以使用。

短片段的长度不等于整首音乐的时长，AI 会结合声音和场景线索查找。内置链接获取脚本支持标准 B 站 BV 链接；其他网络视频由 AI 根据可用工具处理，也可直接使用你提供的本地录屏或音频文件。

## 安装到 Codex

1. 下载本仓库或解压分享包，将技能文件夹命名为 `endfield-music-extractor`，其中应直接包含 `SKILL.md`。从 GitHub 下载 ZIP 时，需要将解压后的文件夹改为这个名称。
2. 把整个文件夹放入 `~/.codex/skills/`。Windows 默认位置为 `%USERPROFILE%\.codex\skills\`；如果你配置过 `CODEX_HOME`，则放到其 `skills/` 下。
3. 确认结构是 `skills/endfield-music-extractor/SKILL.md`，不要多套一层同名文件夹。
4. 在新聊天中使用 `$endfield-music-extractor`，并告诉 AI 游戏的实际安装位置。

其他支持 `SKILL.md` 的 AI 客户端，可按该客户端的技能安装方式添加此文件夹。

## 直接这样说

> 用 $endfield-music-extractor，帮我找这两首终末地音乐。游戏安装目录是……，参考视频是……，对应第10和11个分P。请从本地提取，并核对声音。

也可以这样说：

> 用 $endfield-music-extractor，我没有曲目编号，这是我自己录制的游戏片段。请先从片段中提取目标音乐，再与本地游戏音轨比对，帮我找到对应的音乐。

> 用 $endfield-music-extractor，我想找在某张地图、某个任务阶段响起的背景音乐。请先给候选试听，不能确认的地方告诉我。

## 需要准备什么

- 安装好的游戏；参考内容来自新版时，先完成正常更新。
- Python 3.10+。依赖在 `scripts/requirements.txt`，AI 可以放在独立环境中安装。
- FFmpeg；解码 WEM 需要 vgmstream，解析播放关系需要 wwiser。内附脚本可以从官方项目下载固定版本的辅助工具。
- 一个游戏目录之外的输出文件夹。

## 包含的文件

- `SKILL.md`：给 AI 的查找与核对流程。
- `scripts/endfield_audio.py`：资源索引、事件银行定位、定向提取与转码。
- `scripts/music_catalog.py`：建立音乐清单，支持按时长筛选。
- `scripts/audio_match.py`：短参考片段获取、音频波形比对。
- `scripts/prepare_tools.py`：下载官方辅助工具。
- `references/`：命令、格式笔记、成功案例和验证范围。

这个分享包不附带游戏歌曲、参考视频音频或解码器二进制。解码器在运行时单独下载，输出文件留在各自玩家的电脑上。

已在 Windows、本地终末地1.6资源上完成实际索引、目录构建、音频提取和声音比对。具体结果见 `references/validation.md`；未来版本若更换格式，需要更新解析器。
