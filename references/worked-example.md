# 成功案例：scroll_p2 的两个分P

这是2026年10月19日的一次实际定位，用来解释排查方式。具体ID属于当次资源快照，后续任务现场读取索引，不把这些数字当通用默认值。

用户线索：

- `au_music_map02_lv010_exploring_scroll_p2_02`
- `au_music_map02_lv010_exploring_scroll_p2_03`
- [视频第10分P](https://www.bilibili.com/video/BV1NvJ66gEML/?p=10)
- [视频第11分P](https://www.bilibili.com/video/BV1NvJ66gEML/?p=11)

## 关键转折

初次本地索引里没有对应lv010事件。视频标题为1.6新增BGM，说明中还写明分P名称不是文件名。玩家更新游戏后，事件主体 `au_music_map02_lv010_exploring_scroll_p2` 出现。

新的BLC代码版本是5，标签从32位变为64位。CRC可以通过，但沿旧布局读取会把文件名长度读错；调整字段宽度后，索引才正常。

## 实际播放链

```text
事件 au_music_map02_lv010_exploring_scroll_p2
  event ID 1739497170
  → Action / SetState
  → 状态组 1175361723，状态值 1635194255
  → MusicSwitch 1047861326
  → 播放列表 261747166
  → 四个音乐片段中的具体目标
```

| 视频标签 | Segment ID | Track ID | sourceID / WEM ID | 音源时长 |
|---|---:|---:|---:|---:|
| scroll_p2_02 | 331192852 | 138379752 | 791376864 | 168.965542秒 |
| scroll_p2_03 | 608316264 | 53165831 | 487534973 | 134.845375秒 |

两个WEM都来自当次 `Data/Audio/PCK/Windows/Main/default_stream_3.pck`，采样率48kHz，双声道，原始编码为Wwise Vorbis。

## 核对

以视频第5–65秒比较本地解码音频，正确配对的归一化波形相关系数分别为0.99992774、0.99879613，时间偏移均为0秒。把两首交叉错配时，系数低于0.034。

这既给出了本地来源链，也验证了两个视频标签与具体媒体的对应关系。分享技能时只附这些文字证据，不附游戏音乐、参考片段或原电脑路径。
