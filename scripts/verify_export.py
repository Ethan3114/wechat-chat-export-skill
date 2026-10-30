import argparse
from html.parser import HTMLParser
import json
from pathlib import Path


class PayloadReader(HTMLParser):
    def __init__(self):
        super().__init__()
        self.inside = False
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag == 'script' and dict(attrs).get('id') == 'data':
            self.inside = True

    def handle_endtag(self, tag):
        if tag == 'script':
            self.inside = False

    def handle_data(self, text):
        if self.inside:
            self.parts.append(text)


def verify(directory):
    data = json.loads((directory / 'chat.json').read_text())
    summary, messages = data['summary'], data['messages']
    assert messages and len(messages) == summary['message_count'] == sum(summary['database_counts'].values())
    allowed = {summary['owner'], summary['contact']['username'], ''}
    assert all(item['sender_username'] in allowed for item in messages)
    identifiers = [item['server_id'] for item in messages if item['server_id']]
    assert len(identifiers) == len(set(identifiers))
    assert all(messages[index]['create_time'] <= messages[index + 1]['create_time'] for index in range(len(messages) - 1))
    assert messages[0]['time'] == summary['first_time'] and messages[-1]['time'] == summary['last_time']
    parser = PayloadReader()
    parser.feed((directory / 'chat.html').read_text())
    assert json.loads(''.join(parser.parts)) == data
    attachments = json.loads((directory / 'attachments.json').read_text())
    assert len(attachments) == summary['attachment_count']
    paths = set()
    for item in attachments:
        path = (directory / item['path']).resolve()
        assert path.is_relative_to(directory.resolve())
        assert path.is_file() and path.stat().st_size == item['size']
        paths.add(item['path'])
    for item in messages:
        assert isinstance(item['message_content'], str) and isinstance(item['display_text'], str)
        assert all(attachment['path'] in paths for attachment in item['attachments'])
    expected = '\n\n'.join(f'{item["time"]}  {item["sender"]}  {item["type_name"]}\n{item["display_text"]}' for item in messages)
    assert (directory / 'chat.txt').read_text() == expected
    print(json.dumps({'verified_messages': len(messages), 'verified_attachments': len(attachments)}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='核验会话导出文件')
    parser.add_argument('directory', type=Path)
    verify(parser.parse_args().directory)
