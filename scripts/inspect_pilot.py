"""Export readable last candidates and diagnose every case after a pilot finishes.

Candidate scoring is diagnostic only; it never overwrites accepted plan scores.
"""
import hashlib
import json
import contextlib
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lab.agent import parse_plan
from lab.common import ROOT, DATA, VENDOR, use_upstream, read_json, write_json
from lab.evaluate import evaluate_plan


def main():
    pilot = Path(sys.argv[1]).resolve()
    manifest = read_json(pilot/'manifest.json')
    generation_matches = all(hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==digest
                             for name,digest in manifest['source_sha256'].items())
    for mapping in (manifest['data_sha256'], manifest['scoring_audit']['source_sha256']):
        for name, digest in mapping.items():
            assert hashlib.sha256((ROOT/name).read_bytes()).hexdigest() == digest, name
    rows = []
    for split, ids in manifest['task_ids'].items():
        for uid in ids:
            task = pilot/split/uid
            metrics, score = read_json(task/'metrics.json'), read_json(task/'evaluation.json')
            events = [json.loads(s) for s in (task/'trace.jsonl').read_text(encoding='utf-8').splitlines()]
            responses = [e for e in events if e['event'] == 'model_response']
            assert metrics['model_calls'] == sum(e['event']=='model_request' for e in events)
            for key in ('input_tokens','output_tokens'):
                assert metrics[key] == sum(e[key] for e in responses)
            assert not score.get('evaluator_exception'), uid
            assert score['all_pass'] == (score['schema_pass'] and score['commonsense_pass'] and score['logical_pass'])
            candidates = [e for e in responses if e['agent'] in ('planner','single')
                          and e['content'] and not e['tool_calls']]
            submissions = [e for e in events if e['event']=='tool_result' and e['tool']=='finalize_plan' and 'plan' in e['result']]
            if submissions:
                candidates = [{'content':json.dumps(submissions[-1]['result']['plan'],ensure_ascii=False)}]
            candidate_score = None
            candidate_path = None
            diagnostic_plan = read_json(task/'plan.json') if (task/'plan.json').exists() else None
            if not (task/'plan.json').exists() and candidates:
                text = candidates[-1]['content']
                (task/'candidate_plan.txt').write_text(text, encoding='utf-8')
                candidate_path = str(task/'candidate_plan.txt')
                try:
                    candidate = parse_plan(text)
                except (ValueError, TypeError):
                    pass
                else:
                    write_json(task/'candidate_plan.json', candidate)
                    candidate_path = str(task/'candidate_plan.json')
                    candidate_score = evaluate_plan(split, uid, candidate)
                    diagnostic_plan = candidate
                    write_json(task/'candidate_evaluation.json', candidate_score)
            if not candidates and not (task/'plan.json').exists() and responses:
                (task/'last_agent_output.txt').write_text(responses[-1]['content'], encoding='utf-8')
            detailed_errors = {}
            if not score['all_pass'] and diagnostic_plan is not None:
                use_upstream()
                from chinatravel.symbol_verification import commonsense_constraint as checks
                query = next(q for q in read_json(DATA/'private'/f'{split}.json') if q['uid']==uid)
                with contextlib.chdir(VENDOR):
                    checks._set_tool_lang('zh')
                    for name in ('Is_activity_grounded','Is_intercity_transport_correct','Is_attractions_correct',
                                 'Is_hotels_correct','Is_restaurants_correct','Is_transport_correct','Is_time_correct','Is_space_correct'):
                        try:
                            _, errors = getattr(checks, name)(query, diagnostic_plan, verbose=False)
                            if errors:
                                detailed_errors[name] = errors
                        except Exception as exc:
                            detailed_errors[name] = {'diagnostic_error_type':type(exc).__name__}
                write_json(task/'case_diagnostics.json', detailed_errors)
            rows.append({
                'uid':uid,'split':split,'metrics':metrics,'scores':score,
                'view_plan':str(task/'plan.json') if (task/'plan.json').exists() else candidate_path,
                'candidate_scores_diagnostic_only':candidate_score,
                'commonsense_errors':detailed_errors,
                'submission_errors':[e['errors'] for e in events if e['event']=='validation_failed'],
                'failed_commonsense_checks':[key for row in score.get('commonsense_details',[])
                                             for key,value in row.items() if key!='data_id' and value],
                'failed_hard_checks':[key for row in score.get('logical_details',[])
                                      for key,value in row.items() if key!='data_id' and not value],
                'tool_errors':[{'tool':e['tool'],'arguments':e['arguments'],'result':e['result']}
                               for e in events if e['event']=='tool_result' and not e['result'].get('success')],
                'requested_output_limits':sorted(set(e['requested_max_tokens'] for e in responses)),
                'max_single_output_tokens':max((e['output_tokens'] for e in responses),default=0),
                'truncated_responses':sum(e.get('finish_reason')=='length' for e in responses),
                'last_agent':responses[-1]['agent'] if responses else None,
            })
    assert len(rows) == sum(manifest['counts'].values()) == len({r['uid'] for r in rows})
    result = {'tasks':len(rows),'accepted_plans':sum(r['metrics']['status']=='completed' for r in rows),
              'all_pass':sum(r['scores']['all_pass'] for r in rows),
              'scorer_exceptions':sum(bool(r['scores'].get('evaluator_exception')) for r in rows),
              'source_data_and_usage_verified':generation_matches,
              'generation_snapshot_matches_current':generation_matches,
              'data_scorer_and_usage_verified':True,
              'truncated_responses':sum(r['truncated_responses'] for r in rows),
              'input_tokens':sum(r['metrics']['input_tokens'] for r in rows),
              'output_tokens':sum(r['metrics']['output_tokens'] for r in rows),'cases':rows}
    write_json(pilot/'case_analysis.json',result)
    print(json.dumps({k:v for k,v in result.items() if k!='cases'},indent=2))


if __name__ == '__main__':
    main()
