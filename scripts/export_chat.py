import argparse
import base64
from collections import Counter
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import shutil
import xml.etree.ElementTree as ET
from zoneinfo import ZoneInfo

from sqlcipher3 import dbapi2 as sqlcipher
import zstandard


ZONE = ZoneInfo('Asia/Shanghai')
LABELS = {1: '文字', 3: '图片', 34: '语音', 42: '名片', 43: '视频', 47: '表情', 48: '位置', 49: '分享', 50: '通话', 10000: '系统消息'}
DECOMPRESSOR = zstandard.ZstdDecompressor()


def open_database(root, keys, relative):
    path = (root / relative).resolve()
    assert path.is_relative_to(root.resolve()), '数据库路径超出副本目录'
    material = keys[relative]
    raw_key = material['enc_key'] + material['salt']
    assert re.fullmatch(r'[0-9a-fA-F]{96}', raw_key), '密钥格式不符合要求'
    connection = sqlcipher.connect(str(path))
    connection.row_factory = sqlcipher.Row
    connection.execute('PRAGMA key = "x\'' + raw_key + '\'"')
    connection.execute('PRAGMA query_only=ON')
    assert [row[0] for row in connection.execute('PRAGMA integrity_check')] == ['ok'], '数据库完整性检查失败'
    return connection


def decode(value):
    if isinstance(value, bytes):
        if value.startswith(b'\x28\xb5\x2f\xfd'):
            value = DECOMPRESSOR.decompress(value)
        return value.decode('utf-8')
    return value or ''


def serializable(value):
    return {'base64': base64.b64encode(value).decode()} if isinstance(value, bytes) else value


def describe(item):
    content = item['message_content']
    kind = item['local_type'] & 0xffffffff
    item['type_name'] = LABELS.get(kind, '消息')
    item['media_hashes'] = []
    if kind == 1:
        return content
    if content.lstrip().startswith(('<?xml', '<msg', '<sysmsg', '<voip', '<location')):
        document = ET.fromstring(content.rstrip('\0'))
        fields = []
        hashes = set()
        for node in document.iter():
            for name, value in node.attrib.items():
                if 'md5' in name.lower() and re.fullmatch('[0-9a-fA-F]{32}', value):
                    hashes.add(value.lower())
            if node.tag in ('title', 'des', 'content', 'displayname', 'label', 'replacemsg') and node.text and node.text.strip():
                fields.append(node.text.strip())
        item['media_hashes'] = sorted(hashes)
        return '\n'.join(dict.fromkeys(fields)) or f'[{item["type_name"]}]'
    return content or f'[{item["type_name"]}]'


def export(args):
    assert not args.output.exists(), '输出目录已存在，请指定新的目录'
    skill = Path(__file__).resolve().parents[1]
    assert not args.output.resolve().is_relative_to(skill), '运行数据必须保存在技能仓库以外'
    keys = json.loads(args.keys.read_text())
    contacts = open_database(args.database, keys, 'contact/contact.db')
    rows = contacts.execute('SELECT username,remark,nick_name FROM contact WHERE username=? OR remark=? OR nick_name=?', (args.contact,) * 3).fetchall()
    assert len(rows) == 1, '联系人必须精确且唯一匹配'
    contact = dict(rows[0])
    contacts.close()
    target = contact['username']
    assert target != args.owner and not target.endswith('@chatroom'), '此脚本支持与其他联系人的单独会话'
    digest = hashlib.md5(target.encode()).hexdigest()
    table = 'Msg_' + digest
    records = []
    counts = {}
    for relative in sorted(keys):
        if not re.fullmatch(r'message/message_[0-9]+\.db', relative):
            continue
        connection = open_database(args.database, keys, relative)
        if connection.execute('SELECT 1 FROM sqlite_master WHERE type="table" AND name=?', (table,)).fetchone():
            senders = dict(connection.execute('SELECT rowid,user_name FROM Name2Id'))
            selected = 0
            for row in connection.execute(f'SELECT * FROM "{table}" ORDER BY sort_seq,local_id'):
                time = datetime.fromtimestamp(row['create_time'], ZONE).isoformat()
                date = time[:10]
                if (args.start and date < args.start) or (args.end and date > args.end):
                    continue
                item = {name: serializable(row[name]) for name in row.keys()}
                item['message_content'] = decode(row['message_content'])
                item['source'] = decode(row['source'])
                sender = senders.get(row['real_sender_id'], '')
                assert sender in (args.owner, target, ''), '发现会话以外的发送者'
                item.update(sender_username=sender, sender='我' if sender == args.owner else '对方' if sender == target else '系统', time=time, database=relative)
                item['display_text'] = describe(item)
                item['attachments'] = []
                records.append(item)
                selected += 1
            counts[relative] = selected
        connection.close()
    assert records, '指定范围没有消息'
    records.sort(key=lambda item: (item['create_time'], item['sort_seq'], item['server_id'], item['database'], item['local_id']))
    identifiers = [item['server_id'] for item in records if item['server_id']]
    assert len(identifiers) == len(set(identifiers)), '发现重复消息标识，需要检查数据库范围'
    args.output.mkdir(parents=True, mode=0o700)
    attachments = []
    hashes = {value for item in records for value in item['media_hashes']}
    hash_paths = {}
    attachment_root = args.account / 'msg/attach' / digest if args.account else None
    if attachment_root and attachment_root.is_dir():
        for source in sorted(attachment_root.rglob('*')):
            if not source.is_file():
                continue
            assert source.resolve().is_relative_to(attachment_root.resolve()), '附件链接超出会话目录'
            matched = set(re.findall(r'[0-9a-fA-F]{32}', source.name)) & hashes
            if not matched and (args.start or args.end):
                continue
            relative = Path('attachments/local') / source.relative_to(attachment_root)
            destination = args.output / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, destination)
            entry = {'path': relative.as_posix(), 'size': destination.stat().st_size, 'status': '原始文件，编码与加密状态待检查'}
            attachments.append(entry)
            for value in matched:
                hash_paths.setdefault(value, []).append(entry)
    for item in records:
        item['attachments'] = [entry for value in item['media_hashes'] for entry in hash_paths.get(value, [])]
    selected_ids = set(identifiers)
    voices = {}
    if 'message/media_0.db' in keys:
        connection = open_database(args.database, keys, 'message/media_0.db')
        voice_id = connection.execute('SELECT rowid FROM Name2Id WHERE user_name=?', (target,)).fetchone()
        if voice_id:
            for row in connection.execute('SELECT svr_id,voice_data FROM VoiceInfo WHERE chat_name_id=?', (voice_id[0],)):
                if row['svr_id'] in selected_ids and row['voice_data']:
                    assert row['svr_id'] not in voices, '存在重复语音标识'
                    relative = Path('attachments/voice') / f'{row["svr_id"]}.silk'
                    destination = args.output / relative
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    destination.write_bytes(row['voice_data'])
                    entry = {'path': relative.as_posix(), 'size': destination.stat().st_size, 'status': 'SILK 原始编码'}
                    attachments.append(entry)
                    voices[row['svr_id']] = entry
        connection.close()
    for item in records:
        if item['server_id'] in voices:
            item['attachments'].append(voices[item['server_id']])
    summary = {'contact': contact, 'owner': args.owner, 'message_count': len(records), 'database_counts': counts, 'first_time': records[0]['time'], 'last_time': records[-1]['time'], 'types': dict(Counter(str(item['local_type']) for item in records)), 'attachment_count': len(attachments), 'voice_count': len(voices), 'attachment_note': '本地原始附件；DAT 图片尚未解密，SILK 语音尚未转换。只包含已确认关联且本机存在的文件。'}
    data = {'summary': summary, 'messages': records}
    (args.output / 'chat.json').write_text(json.dumps(data, ensure_ascii=False, indent=2))
    (args.output / 'chat.txt').write_text('\n\n'.join(f'{item["time"]}  {item["sender"]}  {item["type_name"]}\n{item["display_text"]}' for item in records))
    (args.output / 'attachments.json').write_text(json.dumps(attachments, ensure_ascii=False, indent=2))
    payload = json.dumps(data, ensure_ascii=False).replace('<', '\\u003c')
    (args.output / 'chat.html').write_text((skill / 'assets/chat.html').read_text().replace('CHAT_DATA_PLACEHOLDER', payload))
    print(json.dumps({'messages': len(records), 'attachments': len(attachments), 'voices': len(voices)}, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser(description='导出指定微信单独会话')
    parser.add_argument('--database', required=True, type=Path)
    parser.add_argument('--keys', required=True, type=Path)
    parser.add_argument('--contact', required=True)
    parser.add_argument('--owner', required=True)
    parser.add_argument('--account', type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--start', type=lambda value: datetime.strptime(value, '%Y-%m-%d').date().isoformat())
    parser.add_argument('--end', type=lambda value: datetime.strptime(value, '%Y-%m-%d').date().isoformat())
    args = parser.parse_args()
    assert not (args.start and args.end and args.start > args.end), '日期范围无效'
    export(args)


if __name__ == '__main__':
    main()
