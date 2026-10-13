#!/usr/bin/env python3
"""Export public messages and tool I/O, omitting internal reasoning blocks."""
import argparse
import json
from pathlib import Path


def fenced(value):
    text = value if isinstance(value, str) else json.dumps(value, indent=2, ensure_ascii=False)
    fence = '`' * max(3, max((len(piece) for piece in text.split() if set(piece) == {'`'}), default=0)+1)
    return '\n'+fence+'text\n'+text+'\n'+fence+'\n'


def export(report_path):
    report = json.loads(report_path.read_text()); root = report_path.parent
    rows = []
    for run in report['runs']:
        log = Path(run['transcript']); out = log.parent/'readable.md'
        parts = ['# '+run['arm']+' / '+run['round'],
                 '\nRequested model: '+str(run.get('model', report.get('model'))),
                 '\nObserved usage models: '+', '.join((run.get('modelUsage') or {}).keys()),
                 '\nExperiment status: '+str(report.get('status')),
                 '\n[Raw transcript]('+str(log)+') · [Frozen workspace]('+str(log.parent/'workspace')+')',
                 '\n## Invocation prompt\n', (log.parent/'prompt.txt').read_text()]
        calls = 0
        for line in log.read_text().splitlines():
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if event.get('type') in ('assistant', 'user'):
                for block in event.get('message', {}).get('content', []) or []:
                    if not isinstance(block, dict):
                        continue
                    kind = block.get('type')
                    if kind == 'text':
                        parts += ['\n## '+event['type'].capitalize()+'\n', block.get('text', '')]
                    elif kind == 'tool_use':
                        calls += 1
                        parts += ['\n## Tool: '+block.get('name', ''), fenced(block.get('input'))]
                    elif kind == 'tool_result':
                        payload = block.get('content')
                        if isinstance(payload, list):
                            payload = [b if b.get('type') == 'text' else {'type': b.get('type'), 'note': 'Non-text payload omitted'} for b in payload]
                        parts += ['\n## Tool result'+(' (error)' if block.get('is_error') else ''), fenced(payload)]
            elif event.get('type') == 'item.completed':
                item = event.get('item', {}); kind = item.get('type')
                if kind == 'agent_message':
                    parts += ['\n## Assistant\n', item.get('text', '')]
                elif kind != 'reasoning':
                    calls += 1
                    parts += ['\n## Tool: '+kind, fenced(item)]
        out.write_text('\n'.join(parts)+'\n')
        rows.append({'arm': run['arm'], 'round': run['round'], 'path': str(out),
                     'toolCalls': calls, 'recordedToolCalls': run['toolCalls']})
    (root/'transcript-manifest.json').write_text(json.dumps(rows, indent=2)+'\n')
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('reports', type=Path, nargs='+')
    args = parser.parse_args()
    for path in args.reports:
        rows = export(path)
        print(path, len(rows), 'turns;', sum(x['toolCalls'] for x in rows), 'tool calls')


if __name__ == '__main__':
    main()
