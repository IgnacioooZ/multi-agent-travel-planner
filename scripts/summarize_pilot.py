"""Reconstruct split metadata from frozen IDs and score completed pilot tasks offline."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
from collections import Counter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from lab.common import read_json, write_json


def main():
    pilot = Path(sys.argv[1]).resolve()
    manifest = read_json(pilot / 'manifest.json')
    sources = [Path(p) for p in manifest['source_run_dirs']]
    summaries = []
    for split, ids in manifest['task_ids'].items():
        target = pilot / split
        rows = []
        for uid in ids:
            matches = [p / uid for p in sources if (p / uid / 'metrics.json').exists()]
            if len(matches) != 1:
                raise RuntimeError(f'{split}/{uid}: expected one finished task, got {len(matches)}')
            shutil.copytree(matches[0], target / uid, dirs_exist_ok=True)
            metric = read_json(target / uid / 'metrics.json')
            events = [json.loads(s) for s in (target / uid / 'trace.jsonl').read_text(encoding='utf-8').splitlines()]
            responses = [e for e in events if e['event'] == 'model_response']
            tool_results = [e for e in events if e['event'] == 'tool_result']
            observed = metric['input_tokens'] + metric['output_tokens']
            rows.append({
                'uid': uid, **metric,
                'observed_token_limit_reached': manifest['settings']['max_total_tokens'] is not None and observed >= manifest['settings']['max_total_tokens'],
                'served_models': sorted({e.get('served_model','') for e in responses}),
                'handoff_agents': [e['agent'] for e in events if e['event']=='handoff'],
                'last_agent': responses[-1].get('agent') if responses else None,
                'finish_reasons': dict(Counter(e.get('finish_reason') for e in responses)),
                'tool_errors': sum(not e['result'].get('success',False) for e in tool_results),
            })
        write_json(target / 'run.json', {
            'mode': manifest['mode'], 'transport': manifest['transport'], 'split': split,
            'subset': 'dev' if split=='easy' else 'all', 'task_ids': ids,
            'settings': manifest['settings'], 'benchmark': manifest['benchmark'],
            'measured': True, 'metadata_reconstructed_from': str(pilot / 'manifest.json'),
        })
        with (pilot / f'{split}-canonical-evaluation.log').open('w',encoding='utf-8') as log:
            result = subprocess.run([sys.executable,'-m','lab.evaluate',str(target)],cwd=ROOT,stdout=log,stderr=subprocess.STDOUT)
        if result.returncode:
            raise RuntimeError(f'Offline evaluator failed for {split}; inspect log')
        for row in rows:
            score = read_json(target / row['uid'] / 'evaluation.json')
            row['scores'] = {key: score[key] for key in ('schema_pass','commonsense_pass','logical_pass','all_pass')}
        summary = {
            'split': split, 'tasks': len(rows), 'completed': sum(r['status']=='completed' for r in rows),
            **{key: sum(r['scores'][key] for r in rows) for key in ('schema_pass','commonsense_pass','logical_pass','all_pass')},
            **{key: sum(r[key] for r in rows) for key in ('model_calls','tool_calls','input_tokens','output_tokens','latency_seconds','tool_errors')},
            'token_limit_reached': sum(r['observed_token_limit_reached'] for r in rows),
            'grounding_queries': sum(r.get('grounding_queries',0) for r in rows),
            'error_types': dict(Counter(r['error_type'] for r in rows if r['error_type'])),
            'run_dir': str(target), 'runs': rows,
        }
        write_json(target / 'metrics_summary.json', summary)
        summaries.append(summary)
        print(json.dumps({k:v for k,v in summary.items() if k!='runs'},ensure_ascii=False),flush=True)
    write_json(pilot / 'canonical_results.json', {'splits': summaries,'note':'Frozen first N tasks per split (see manifest); one run; multi only; not official leaderboard results.'})


if __name__ == '__main__':
    main()
