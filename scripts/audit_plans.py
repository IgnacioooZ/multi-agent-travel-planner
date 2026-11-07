"""Replay saved plans without model calls; preserve all original evaluations."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lab.common import read_json, write_json
from lab.evaluate import evaluate_plan
from lab.validation import plan_errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('pilot_dir', type=Path)
    args = parser.parse_args()
    rows = []
    for split in ('easy', 'medium', 'human'):
        for path in sorted((args.pilot_dir / split).glob('*/plan.json')):
            task = path.parent
            original = read_json(task / 'evaluation.json')
            updated = evaluate_plan(split, task.name, read_json(path))
            rows.append({
                'split': split, 'uid': task.name,
                'public_validation_errors': plan_errors(path.read_text(encoding='utf-8')),
                'original_evaluator_exception': any(
                    value for row in original['commonsense_details']
                    for key, value in row.items() if 'Evaluator Exception' in key
                ),
                'patched_evaluation': updated,
            })
    output = args.pilot_dir / 'diagnosis' / 'plan_audit.json'
    write_json(output, rows)
    print(json.dumps({
        'plans': len(rows),
        'rejected_by_public_validation': sum(bool(r['public_validation_errors']) for r in rows),
        'original_evaluator_exceptions': sum(r['original_evaluator_exception'] for r in rows),
        'patched_evaluator_exceptions': sum(r['patched_evaluation']['evaluator_exception'] for r in rows),
        'patched_all_pass': sum(r['patched_evaluation']['all_pass'] for r in rows),
        'output': str(output),
    }, indent=2))


if __name__ == '__main__':
    main()
