import asyncio
import json
from copy import deepcopy

import pytest

from lab.agent import Agent, Trace, Usage
from lab.config import Settings
from lab.validation import InvalidPlan, plan_errors


def valid_plan():
    return {"people_number": 1, "start_city": "上海", "target_city": "杭州", "itinerary": [
        {"day": 1, "activities": [
            {"type": "train", "start": "上海虹桥站", "end": "杭州东站", "TrainID": "test",
             "start_time": "08:00", "end_time": "09:00", "price": 100, "cost": 100, "tickets": 1, "transports": []},
            {"type": "attraction", "position": "西湖", "start_time": "09:30", "end_time": "11:00",
             "price": 0, "cost": 0, "tickets": 1, "transports": [
                 {"start": "杭州东站", "end": "西湖", "mode": "taxi", "cars": 1, "price": 20,
                  "cost": 20, "distance": 5, "start_time": "09:00", "end_time": "09:30"}]}]}]}


def test_public_contract_accepts_consistent_plan():
    assert plan_errors(json.dumps(valid_plan())) == []


def test_missing_stations_and_taxi_cars_are_reported():
    plan = valid_plan()
    del plan['itinerary'][0]['activities'][0]['start']
    assert any('start' in e for e in plan_errors(json.dumps(plan)))
    plan = valid_plan()
    del plan['itinerary'][0]['activities'][1]['transports'][0]['cars']
    assert any('cars' in e for e in plan_errors(json.dumps(plan)))


def test_dinner_ending_at_1700_is_not_dinner():
    plan = valid_plan()
    meal = plan['itinerary'][0]['activities'][1]
    meal.update(type='dinner', start_time='16:37', end_time='17:00')
    assert any('dinner must overlap' in e for e in plan_errors(json.dumps(plan)))
    meal.update(start_time='17:00', end_time='17:30')
    assert plan_errors(json.dumps(plan)) == []


def test_final_schedule_checked_against_handoff_and_new_tool_rows():
    plan = valid_plan()
    record = {'tool': 'attractions_select', 'arguments': {'city': '杭州'},
              'result': {'success': True, 'data': {'rows': [
                  {'name': '西湖', 'opentime': '10:00', 'endtime': '17:00', 'price': 5}]}}}
    context = {'handoffs': [{'evidence': [record]}]}
    errors = plan_errors(json.dumps(plan), context=context)
    assert any('opening hours 10:00--17:00' in e for e in errors)
    assert any('price must match' in e for e in errors)
    assert errors == plan_errors(json.dumps(plan), evidence=[record])
    activity = plan['itinerary'][0]['activities'][1]
    activity.update(start_time='10:00', price=5, cost=5)
    assert plan_errors(json.dumps(plan), context=context) == []


def test_opening_hours_does_not_mix_cities():
    record = {'tool': 'attractions_select', 'arguments': {'city': '苏州'},
              'result': {'success': True, 'data': {'rows': [
                  {'name': '西湖', 'opentime': '10:00', 'endtime': '17:00', 'price': 99}]}}}
    assert plan_errors(json.dumps(valid_plan()), evidence=[record]) == []


def test_cost_time_route_and_duplicate_errors_are_reported():
    plan = valid_plan()
    a = plan['itinerary'][0]['activities'][1]
    a['cost'] = 20
    a['start_time'] = '09:10'
    a['transports'][0]['start'] = 'wrong station'
    plan['itinerary'][0]['activities'].append(deepcopy(a))
    errors = plan_errors(json.dumps(plan))
    assert any('exclude incoming transport' in e for e in errors)
    assert any('arrive before' in e for e in errors)
    assert any('route must start' in e for e in errors)
    assert any('repeated attraction' in e for e in errors)


class Tools:
    async def list_tools(self):
        return []


class Model:
    def __init__(self, answers):
        self.answers = iter(answers)
        self.messages = []

    async def complete(self, messages, tools, max_tokens):
        self.messages.append(deepcopy(messages))
        content, reason = next(self.answers)
        return {'content': content, 'finish_reason': reason, 'tool_calls': [], 'input_tokens': 10, 'output_tokens': 5}


def test_invalid_output_is_repaired_with_shared_budget(tmp_path):
    bad = valid_plan()
    del bad['itinerary'][0]['activities'][0]['end']
    model = Model([(json.dumps(bad), 'stop'), (json.dumps(valid_plan()), 'stop')])
    usage = Usage()
    agent = Agent('planner', 'test', model, Tools(), Settings(), usage,
                  Trace(tmp_path/'trace.jsonl'), validate_output=plan_errors)
    result = asyncio.run(agent.run({}, rounds=4))
    assert plan_errors(result['content']) == [] and usage.model_calls == 2
    assert any('end' in m['content'] and '提交前检查' in m['content'] for m in model.messages[1])


def test_invalid_or_truncated_output_never_becomes_handoff(tmp_path):
    model = Model([('{', 'length')] * 7)
    trace = tmp_path/'trace.jsonl'
    usage = Usage()
    agent = Agent('planner', 'test', model, Tools(), Settings(), usage, Trace(trace), validate_output=plan_errors)
    with pytest.raises(InvalidPlan):
        asyncio.run(agent.run({}, rounds=10))
    events = [json.loads(line)['event'] for line in trace.read_text(encoding='utf-8').splitlines()]
    assert usage.model_calls == 7
    assert events.count('validation_failed') == 7 and 'handoff' not in events
