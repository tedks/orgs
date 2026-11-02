#!/usr/bin/env python3
"""Regenerate retire-agent's bounded index section in an isolated worktree."""
import json
from pathlib import Path
import re
import sys


def build(root, session_id='', event_id=''):
    waiting = root / 'waiting'
    if waiting.is_symlink() or (root / 'receipts').is_symlink():
        raise ValueError('unsafe publication directory')
    waiting.mkdir(exist_ok=True)
    index = waiting / 'INDEX.md'
    if index.is_symlink() or (index.exists() and not index.is_file()):
        raise ValueError('unsafe index path')
    original = index.read_text() if index.exists() else '# Waiting and retired sessions\n'
    begin, end = '<!-- retire-agent:begin -->', '<!-- retire-agent:end -->'
    if (begin in original or end in original) and (original.count(begin) != 1 or original.count(end) != 1 or original.index(begin) >= original.index(end)):
        raise ValueError('malformed generated index section')
    entries = ['| Shard | Session | Provider | Role | State | Last verified |\n| --- | --- | --- | --- | --- | --- |\n']
    def cell(value):
        return str(value).replace('|', '/').replace('\n', ' ')
    for shard in sorted(waiting.glob('*.md')):
        if shard.name == 'INDEX.md':
            continue
        if shard.is_symlink():
            raise ValueError('unsafe shard path')
        try:
            data = json.loads(shard.read_text())
        except ValueError:
            if session_id and len(session_id) >= 8 and session_id[:8].lower() in shard.name.lower():
                raise ValueError('legacy session shard exists; reconcile deliberately')
            continue
        if (session_id and session_id != 'unknown' and isinstance(data, dict) and data.get('session_id') == session_id
                and data.get('event') != event_id):
            raise ValueError('session already has a preserved shard')
        if not isinstance(data, dict) or not isinstance(data.get('event'), str) or not re.fullmatch(r'[0-9a-f]{32}', data['event']):
            continue
        receipt = root / 'receipts' / (data['event'] + '.json')
        if not receipt.exists():
            continue
        if receipt.is_symlink():
            raise ValueError('unsafe receipt path')
        try:
            record = json.loads(receipt.read_text())
        except ValueError as error:
            raise ValueError('malformed retirement receipt') from error
        if not isinstance(record, dict) or any(not isinstance(record.get(key), str) for key in ('event', 'status')):
            raise ValueError('malformed retirement receipt')
        if any(key in record and not isinstance(record[key], str)
               for key in ('shard', 'commit', 'author', 'verified_at')):
            raise ValueError('malformed retirement receipt')
        if record['event'] != data['event']:
            raise ValueError('malformed retirement receipt event identity')
        if record.get('shard') != 'waiting/' + shard.name:
            continue
        if any(key in data and not isinstance(data[key], str) for key in ('harness', 'session_id', 'role')):
            raise ValueError('malformed index shard metadata')
        provider = {'codex': 'OpenAI', 'claude': 'Anthropic', 'agy': 'Google'}.get(data.get('harness'), 'unknown')
        values = (data.get('session_id', 'unknown'), provider, data.get('role', 'unknown'),
                  record['status'], record.get('verified_at', 'unknown'))
        entries.append(f'| [{shard.name}]({shard.name}) | ' + ' | '.join(cell(value) for value in values) + ' |\n')
    section = begin + '\n' + ''.join(entries) + end
    if begin in original:
        updated = original[:original.index(begin)] + section + original[original.index(end) + len(end):]
    else:
        updated = original + '\n\n' + section + '\n'
    index.write_text(updated)


if __name__ == '__main__':
    try:
        build(Path(sys.argv[1]), *(sys.argv[2:4]))
    except (OSError, ValueError, IndexError) as error:
        print(str(error), file=sys.stderr)
        sys.exit(2)
