# 格式与故障定位

## 已实现的范围

- 当前脚本只读取音乐常用的 InitAudio / Audio / AuditAudio / HotfixAudio 块。
- BLC 版本3：没有额外标签；版本4：每个块/文件标签4字节；版本5：标签8字节。
- 外层 VFS 使用12字节文件头作为 nonce，ChaCha20 计数器从1开始；读取后必须验证末尾 CRC32。
- 一份 Persistent 块清单覆盖该块的基础清单。实际 CHK 可能仍在 StreamingAssets，因此按当前清单查文件，再跨两层找同一个 chunk ID。旧可选块中可能残留已迁到 Audio 的同名路径，跨块按资源版本去重。
- 读取原始16字节 chunk ID 后按字节顺序转十六进制文件名，不要把整个 UInt128 做小端数值打印再反转。
- PCK 可带 `:)xD` 头；解码头后解析 banks / sounds / externals。这里只支持已观察到的 little-endian 布局。
- BNK 与 WEM 使用不同 seed。只去掉 PCK 头混淆还不能得到可播放 WEM。
- Wwise 事件名是小写 FNV-1 32位；普通媒体 ID 通常来自编辑器内部标识，不能直接靠曲目名字反算。

公开格式使用的固定 VFS 密钥和音频混淆常量位于脚本中，均非玩家账号凭据。后续版本若密钥或结构变化，CRC / magic / 范围检查应阻止继续误读。

## 常见故障

| 现象 | 接下来检查 |
|---|---|
| 原文件名搜索无结果 | 视频标题是否只是标签；尝试共有事件主体、状态关系或音频匹配 |
| 视频版本比本地新 | 正常完成更新后重建索引；检查新事件是否出现 |
| CRC 错误 | 是否仍在更新、文件损坏、格式或密钥已变化；不要跳过校验 |
| 版本5索引中字符串长度失控 | 是否把64位标签按32位读取，导致后续字段错位 |
| 索引存在但 CHK 缺失 | 同时检查 Persistent / StreamingAssets；更新是否完整；是否重复使用了旧可选块中的迁移前路径 |
| PCK有条目但音频不是RIFF | WEM是否还需按媒体ID解码；seed、偏移、长度是否正确 |
| WEM可播放但不是目标 | 事件、音乐片段、媒体ID可能被混淆；重新看播放列表分支 |
| 输出长度翻倍 | vgmstream是否使用了默认循环；完整一次解码用 `-i` |
| 匹配得分偏低 | 参考是否含旁白、剪辑、变速；尝试干净片段并检查其他候选 |
| 单个WEM只有部分音乐 | 检查是否有多段编排、裁切或叠加，使用TXTP还原 |

## 实现参考

- [EIHRTeam/EndfieldStudio](https://github.com/EIHRTeam/EndfieldStudio)：VfsParser、VfsLoader、AkpkPackage 等格式实现，MIT。
- [Escartem/AnimeWwise](https://github.com/Escartem/AnimeWwise)：音频包与音频混淆算法的交叉参考；本包未附带其代码文件。
- [bnnm/wwiser](https://github.com/bnnm/wwiser)：Wwise语义解析、音乐控制树和TXTP生成。
- [vgmstream/vgmstream](https://github.com/vgmstream/vgmstream)：WEM与TXTP解码。
- [FFmpeg](https://ffmpeg.org/)：播放格式转换与参考片段处理。

辅助工具由各自官方项目单独下载；本分享包不附带它们的二进制。VFS/PCK实现参考的MIT版权声明保留于根目录LICENSE。
