# Copyright (C) 2026 David L F Gaden
"""Small, portable human-readable feedback history; no scripts or dependencies."""
import html
import json
from pathlib import Path
from urllib.parse import quote


def render(report, directory):
    directory = Path(directory).absolute()
    def text(value):
        if isinstance(value, float): value = format(value, '.6g')
        if isinstance(value, (dict, list)): value = json.dumps(value, sort_keys=True)
        return html.escape(str(value))
    cards = []
    for attempt in report['attempts']:
        rows = []
        for check in attempt['decision']['checks']:
            passed = check.get('passed')
            status = 'Passed' if passed is True else 'Not met' if passed is False else 'Measured'
            rows.append('<tr><th>'+text(check.get('requirement', 'Observation'))+'</th><td>'+
                        text(check.get('observed', '—'))+'</td><td>'+text(check.get('relation', ''))+' '+
                        text(check.get('requested', '—'))+'</td><td>'+text(check.get('units', ''))+
                        '</td><td class="'+('pass' if passed is True else 'fail' if passed is False else '')+'">'+status+'</td></tr>')
        links = []
        for artifact in attempt['artifacts']:
            try: relative = Path(artifact['file']).absolute().relative_to(directory).as_posix()
            except ValueError: continue
            links.append('<a href="'+html.escape(quote(relative, safe='/'))+'">'+text(Path(relative).name)+'</a>')
        selected = attempt['index'] == report['selected']
        cards.append('<section><h2>Attempt '+str(attempt['index']+1)+(' · Selected' if selected else '')+
                     '</h2><div class="scroll"><table><thead><tr><th>Requirement</th><th>Measured</th><th>Required</th><th>Units</th><th>Result</th></tr></thead><tbody>'+
                     ''.join(rows)+'</tbody></table></div><p class="files">'+ ' · '.join(links)+
                     '</p><details><summary>Inputs for this attempt</summary><pre>'+text(json.dumps(attempt['document'], indent=2, sort_keys=True))+'</pre></details></section>')
    outcome = 'Requirements met' if report['accepted'] else 'Requirements not met'
    return ('<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Study assessment</title><style>'+'''
body{font:16px/1.5 system-ui,sans-serif;margin:0;background:#f3f5f7;color:#18232d}main{max-width:1100px;margin:40px auto;padding:0 24px}h1{font-size:2rem;margin-bottom:8px}h2{font-size:1.15rem}section{background:white;border:1px solid #d4dce3;border-radius:10px;padding:20px;margin:20px 0}table{border-collapse:collapse;width:100%;text-align:left}th,td{padding:10px;border-bottom:1px solid #e0e6eb}thead{background:#f3f5f7}tbody th{font-weight:500}.pass{color:#126038}.fail{color:#9b3422}.scroll{overflow:auto}pre{white-space:pre-wrap;overflow-wrap:anywhere;font-size:13px}a{color:#155ba4}summary{cursor:pointer}.files{font-size:14px}footer{color:#465766;margin:30px 0}
'''+ '</style><main><p>Verified study history</p><h1>'+outcome+'</h1><p>'+str(len(report['attempts']))+' attempts · Stop reason: '+
        text(report['reason'].replace('_', ' '))+'</p><p>'+text(report['selection'])+'</p>'+''.join(cards)+
        '<footer>Acceptance covers the declared requirements. This report does not establish solution convergence or a global optimum.</footer></main></html>\n')
