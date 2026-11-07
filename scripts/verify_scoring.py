"""Offline scorer audit: positive, targeted mutations, parity and denominator."""
import contextlib
from copy import deepcopy
import hashlib
from pathlib import Path
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lab.common import DATA, ROOT, VENDOR, read_json, write_json, use_upstream
from lab.evaluate import evaluate_plan, score_run


def main():
    output = ROOT / 'runs/scoring-audit'
    uid = 'e20241028160248698752'
    plan_path = ROOT / 'runs/20261107-172800-289156-easy-multi-4d3d22af' / uid / 'plan.json'
    plan = read_json(plan_path)
    # Check the exact pinned-source delta, not just a patch-present flag.
    relative = 'chinatravel/symbol_verification/commonsense_constraint.py'
    original = subprocess.check_output(['git', '-C', str(VENDOR), 'show', f'HEAD:{relative}'])
    normalize = lambda b: b.replace(b'\r\n', b'\n')
    assert normalize((VENDOR / relative).read_bytes()) == normalize(original.replace(
        b'Inccorrect cost information of Inner-City Transport',
        b'Incorrect cost information of Inner-City Transport'))
    alignment = {}
    for split in ('easy', 'medium', 'human'):
        public, private = read_json(DATA/'public'/f'{split}.json'), read_json(DATA/'private'/f'{split}.json')
        indexed = {r['uid']: r for r in private}
        assert len(indexed) == len(private) == len(public)
        assert len({r['uid'] for r in public}) == len(public)
        assert all(set(r) == {'uid', 'request'} and r['request'] == indexed[r['uid']]['nature_language']
                   and indexed[r['uid']]['hard_logic_py'] for r in public)
        alignment[split] = len(public)

    cases = [('positive', deepcopy(plan), None), ('invalid_schema', {}, 'schema_pass')]
    bad = deepcopy(plan)
    del bad['itinerary'][0]['activities'][0]['start']
    cases.append(('missing_station', bad, 'schema_pass'))
    bad = deepcopy(plan)
    bad['itinerary'][0]['activities'][0]['TrainID'] = 'NONEXISTENT_TRAIN'
    cases.append(('fabricated_train', bad, 'commonsense_pass'))
    bad = deepcopy(plan)
    attraction = next(a for a in bad['itinerary'][0]['activities'] if a['type'] == 'attraction')
    attraction['price'] += 100
    attraction['cost'] += 100
    cases.append(('wrong_tool_price', bad, 'commonsense_pass'))
    bad = deepcopy(plan)
    bad['people_number'] = 2
    cases.append(('wrong_people', bad, 'logical_pass'))
    bad = deepcopy(plan)
    bad['itinerary'][0]['activities'][0]['cost'] = 100000
    cases.append(('over_budget', bad, 'logical_pass'))
    bad = deepcopy(plan)
    meal = next(a for a in bad['itinerary'][0]['activities'] if a['type'] == 'dinner')
    meal.update(start_time='15:00', end_time='15:30')
    cases.append(('wrong_meal_time', bad, 'commonsense_pass'))
    results = []
    for name, candidate, must_fail in cases:
        score = evaluate_plan('easy', uid, candidate)
        assert not score['evaluator_exception'], name
        assert score['all_pass'] == (score['schema_pass'] and score['commonsense_pass'] and score['logical_pass'])
        assert score['all_pass'] if must_fail is None else not score[must_fail] and not score['all_pass'], name
        write_json(output/name/'plan.json', candidate)
        write_json(output/name/'evaluation.json', score)
        results.append({'case': name, 'expected_failure': must_fail, 'passed': True})

    # Direct upstream call must match our wrapper on all official output fields.
    use_upstream()
    from agent_env.scripts.solve_script_with_harness import evaluate_one
    query = next(q for q in read_json(DATA/'private/easy.json') if q['uid'] == uid)
    with contextlib.chdir(VENDOR):
        raw = evaluate_one('easy', uid, query, plan, 'zh')
    wrapped = evaluate_plan('easy', uid, plan)
    assert all(wrapped[k] == v for k, v in raw.items())

    # Independent arithmetic for this fixture's five hidden hard rules.
    activities = [a for day in plan['itinerary'] for a in day['activities']]
    cost = sum(a['cost'] + sum(t['cost'] for t in a['transports']) for a in activities)
    hard = [len(plan['itinerary']) == 1, plan['people_number'] == 1, cost <= 1500,
            all(a['tickets'] == 1 for a in activities if a['type'] in ('attraction','train','airplane'))
            and all(t['tickets'] == 1 for a in activities for t in a['transports'] if t['mode']=='metro'),
            all(t['cars'] == 1 for a in activities for t in a['transports'] if t['mode']=='taxi')]
    assert hard == [bool(wrapped['logical_details'][0][f'logic_py_{i}']) for i in range(5)]
    with tempfile.TemporaryDirectory() as tmp:
        directory = Path(tmp)
        write_json(directory/'run.json', {'split':'easy','mode':'multi','subset':'audit',
                                          'task_ids':[uid,'missing-output-fixture']})
        write_json(directory/uid/'plan.json', plan)
        summary = score_run(directory)
        assert summary['tasks'] == 2 and summary['all_pass_count'] == 1 and summary['complete_success_rate'] == .5
        write_json(output/'denominator_check.json', summary)
    paths = [VENDOR/relative, VENDOR/'chinatravel/evaluation/output_schema.json',
             VENDOR/'chinatravel/evaluation/commonsense_constraint.py',
             VENDOR/'chinatravel/evaluation/hard_constraint.py',
             VENDOR/'agent_env/scripts/solve_script_with_harness.py', ROOT/'lab/evaluate.py']
    report = {'passed':True, 'task_alignment':alignment,'cases':results,'wrapper_parity':True,
              'independent_hard_checks':hard,'independent_total_cost':cost,'missing_output_denominator':True,
              'scorer_patch_exact_delta':True,'positive_plan':str(plan_path),
              'source_sha256':{str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}}
    write_json(output/'report.json',report)
    print(f'AUDIT PASS: {output / "report.json"}',flush=True)


if __name__ == '__main__':
    main()
