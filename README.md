# 微信会话导出 Skill

用于 macOS 微信本地会话导出的 Codex skill。支持指定会话、读取 WAL、解压正文、导出可搜索 HTML／文本／JSON，并保存可以确定关联的本地附件和原始语音。

将本目录复制到 Codex 的 `skills/wechat-chat-export` 目录，通过 `$wechat-chat-export` 使用。执行说明见 [SKILL.md](SKILL.md)。

技能包仅包含通用说明、脚本与模板。运行数据和密钥存放在仓库以外的用户本地目录。

数据库密钥获取依赖单独审阅和运行的 [wcdb-key-tool](https://github.com/TANGandXUE/wcdb-key-tool)。本包未包含其源码。DAT 图片解密和 SILK 音频转换需要另外处理。
