import asyncio
from copy import deepcopy
import json
from types import SimpleNamespace

import pandas as pd

from lab.plan_tool import PlanCompiler
from lab.tools import connect_tools


def draft():
    return {'people_number':2,'start_city':'上海','target_city':'杭州','itinerary':[{'day':1,'activities':[
        {'type':'train','TrainID':'G1','start':'wrong','end':'wrong','start_time':'08:00','end_time':'09:00','price':0,'cost':0,'transports':[]},
        {'type':'attraction','position':'西湖','start_time':'09:30','end_time':'10:30','price':999,'cost':999,'transports':[
            {'mode':'taxi','start_time':'09:00','start':'wrong','end':'wrong','end_time':'09:01','price':1,'cost':1,'distance':1}]}]}]}


def environment():
    services=pd.DataFrame([
        {'TrainID':'G1','From':'上海站','To':'杭州站','BeginTime':'08:00','EndTime':'09:00','Cost':100},
        {'TrainID':'G2','From':'杭州站','To':'上海站','BeginTime':'10:00','EndTime':'11:00','Cost':100},
        {'TrainID':'G3','From':'杭州站','To':'上海站','BeginTime':'12:00','EndTime':'13:00','Cost':100}])
    def goto(**kw):
        hour, minute=map(int,kw['start_time'].split(':'))
        end=hour*60+minute+20
        return [{'start':kw['start'],'end':kw['end'],'mode':'taxi','start_time':kw['start_time'],
                 'end_time':f'{end//60:02d}:{end%60:02d}','cost':20,'distance':5}]
    place=pd.DataFrame([{'name':'西湖','price':10,'opentime':'10:00','endtime':'17:00'}])
    return SimpleNamespace(intercitytransport=SimpleNamespace(select=lambda *a:services),
                           attractions=SimpleNamespace(select=lambda *a:place),transportation=SimpleNamespace(goto=goto))


def test_facts_are_compiled_without_mutating_draft():
    plan=draft()
    plan['itinerary'][0]['activities'].append({'type':'train','TrainID':'G3','start_time':'12:00','end_time':'13:00','price':0,'cost':0,'transport_mode':'taxi','transports':[]})
    original=deepcopy(plan)
    result=PlanCompiler(environment()).compile(plan)
    assert result['success'] and plan==original
    train,visit,back=result['plan']['itinerary'][0]['activities']
    assert (train['price'],train['tickets'],train['cost'],train['start'])==(100,2,200,'上海站')
    assert (visit['price'],visit['tickets'],visit['cost'],visit['start_time'])==(10,2,20,'10:00')
    route=visit['transports'][0]
    assert (route['price'],route['cost'],route['distance'],route['cars'])==(20,20,5,1)
    assert (back['price'],back['tickets'],back['cost'],back['start'])==(100,2,200,'杭州站')
    assert result['changes'] and result['queries']
    assert PlanCompiler(environment()).compile(plan) == result


def test_missed_train_returns_real_later_services_not_invented_times():
    plan=draft()
    plan['itinerary'][0]['activities'].append({'type':'train','TrainID':'G2','start_time':'10:00','end_time':'11:00',
        'price':0,'cost':0,'transport_mode':'taxi','transports':[]})
    result=PlanCompiler(environment()).compile(plan)
    assert not result['success']
    assert any('after departure' in e for e in result['errors'])
    assert result['alternatives'][0]['choices'][0]['TrainID']=='G3'
    assert result['plan']['itinerary'][0]['activities'][-1]['start_time']=='10:00'


def test_public_request_days_and_budget_are_bound_to_submission():
    plan=draft()
    plan['itinerary'].append({'day':2,'activities':[]})
    result=PlanCompiler(environment()).compile(plan, '我想去杭州玩一天，预算10元。')
    assert any('requires 1 day' in e for e in result['errors'])
    assert any('grounded total' in e for e in result['errors'])


def test_morning_hotel_anchor_is_not_another_paid_stay():
    env=environment()
    hotel=pd.DataFrame([{'name':'hotel','price':329,'numbed':1}])
    env.accommodations=SimpleNamespace(select=lambda *a:hotel)
    plan=draft()
    plan['itinerary'][0]['activities'].append({'type':'accommodation','position':'hotel','start_time':'20:00',
        'end_time':'23:00','price':0,'cost':0,'rooms':2,'transports':[]})
    plan['itinerary'].append({'day':2,'activities':[
        {'type':'accommodation','position':'hotel','start_time':'08:00','end_time':'08:30','price':0,'cost':0,'transports':[]},
        {'type':'attraction','position':'西湖','start_time':'11:00','end_time':'12:00','price':0,'cost':0,'transports':[]}]})
    result=PlanCompiler(env).compile(plan)
    assert result['plan']['itinerary'][0]['activities'][-1]['price']==329
    assert result['plan']['itinerary'][0]['activities'][-1]['cost']==658
    assert len(result['plan']['itinerary'][1]['activities'])==1
    assert result['plan']['itinerary'][1]['activities'][0]['transports'][0]['start']=='hotel'


def test_finalizer_real_mcp_matches_direct():
    async def check():
        from lab.common import ROOT,read_json
        # A small real-data fixture with no dependence on an earlier paid run.
        plan={'people_number':1,'start_city':'上海','target_city':'杭州','itinerary':[{'day':1,'activities':[
            {'type':'train','TrainID':'G1321','start_time':'06:10','end_time':'06:56','transports':[]},
            {'type':'attraction','position':'灵隐寺','start_time':'09:00','end_time':'10:00','transport_mode':'taxi','transports':[]},
            {'type':'train','TrainID':'G158','start_time':'16:13','end_time':'17:12','transport_mode':'taxi','transports':[]}]}]}
        async with connect_tools('direct') as tools:
            a=await tools.call('finalize_plan',{'plan':plan})
        async with connect_tools('mcp') as tools:
            b=await tools.call('finalize_plan',{'plan':plan})
        assert a==b and a['success']
    asyncio.run(check())
