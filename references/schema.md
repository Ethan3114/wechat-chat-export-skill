# 已验证的微信 4.x 数据结构

数据库结构存在版本差异。脚本遇到字段变化时直接终止，检查实际 schema 后更新支持。

- `contact/contact.db`：`contact.username` 为账号标识，`remark` 为备注，`nick_name` 为昵称。联系人名称必须精确且唯一匹配。
- `message/message_N.db`：会话表为 `Msg_` 加联系人账号 UTF-8 字节的 MD5 十六进制摘要。账号大小写必须保持原样。
- 每个消息数据库的 `Name2Id.rowid` 对应该库消息表的 `real_sender_id`。每个数据库分别建立映射。
- 消息表字段包括 `local_id`、`server_id`、`local_type`、`sort_seq`、`real_sender_id`、`create_time`、`message_content`、`source`、`packed_info_data`。`local_id` 只在各自表中唯一，不能跨库用于去重。
- `create_time` 是秒级 Unix 时间，显示时明确时区。以时间、排序序号和数据库内标识稳定排序。非零 `server_id` 出现重复时停止并检查，避免静默丢失消息。
- 正文可能是文本或 zstandard 压缩的 BLOB。压缩帧由 `zstandard` 解压，XML 由标准库 ElementTree 解析。原始内容始终保留。
- `local_type` 的低 32 位为基本消息类型，高位可能保存分享子类型。常见基本类型为 1 文字、3 图片、34 语音、43 视频、47 表情、49 分享、50 通话、10000 系统消息。
- `message/media_0.db`：`VoiceInfo.chat_name_id` 通过同库 `Name2Id` 对应联系人，`svr_id` 对应消息 `server_id`，`voice_data` 为原始编码数据。
- 本地会话附件目录为账号目录下 `msg/attach/<会话摘要>`。媒体关联取消息 XML 属性中的 MD5 摘要，保留文件原有扩展名及编码。摘要无法与文件名建立确定关系时保留未关联状态。

RMFH 的 `ChatPackage` 属于独立备份格式。此技能处理本地 WCDB 数据库，备份的 AES-GCM 密钥需要单独取得。
