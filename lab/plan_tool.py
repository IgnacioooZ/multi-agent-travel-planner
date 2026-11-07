"""Compile an itinerary using public sandbox records, never hidden task labels.

The model chooses places, services, durations and travel modes. Python owns the
copied facts and arithmetic. All changes and underlying queries are returned.
"""
from copy import deepcopy
from math import ceil
import json
import re

from lab.validation import plan_errors

SPEC = {'type': 'function', 'function': {
    'name': 'finalize_plan',
    'description': '提交完整行程草案。工具按沙盒原始记录生成真实单价、人数费用和每段路线，检查衔接；成功即作为最终计划提交，无需再复制输出。失败返回具体错误、修正后草案及可行返程候选。',
    'parameters': {'type': 'object', 'properties': {'plan': {'type': 'object'}, 'request': {'type':'string','description':'原始公开用户请求，由运行时绑定，不由模型改写。'}}, 'required': ['plan'], 'additionalProperties': False},
}}


def minutes(value):
    hour, minute = map(int, value.split(':'))
    return hour * 60 + minute


def clock(value):
    return f'{value // 60:02d}:{value % 60:02d}'


class PlanCompiler:
    def __init__(self, env):
        self.env = env
        self.cache = {}

    def table(self, component, city, name):
        key = (component, city, name)
        if key not in self.cache:
            frame = getattr(self.env, component).select(city, 'name', lambda value: value == name)
            rows = frame.to_dict(orient='records')
            if len(rows) != 1:
                raise ValueError(f'{city}/{component}: expected one exact entity {name}, found {len(rows)}')
            self.cache[key] = rows[0]
        return deepcopy(self.cache[key])

    def services(self, start, end, kind):
        key = ('intercity', start, end, kind)
        if key not in self.cache:
            self.cache[key] = self.env.intercitytransport.select(start, end, kind).to_dict(orient='records')
        return self.cache[key]

    def compile(self, draft, request=''):
        plan = deepcopy(draft)
        changes, queries, errors, alternatives = [], [], [], []

        def set_field(item, key, value, path):
            if item.get(key) != value:
                changes.append({'path': path + '/' + key, 'before': item.get(key), 'after': value})
                item[key] = value

        try:
            people = plan['people_number']
            if not isinstance(people, int) or isinstance(people, bool) or people < 1:
                raise ValueError('people_number must be a positive integer')
            city = plan['start_city']
            previous_position = None
            for day in plan['itinerary']:
                previous_end = 0
                kept = []
                for index, activity in enumerate(day['activities']):
                    path = f"day {day['day']} activity {index}"
                    kind = activity['type']
                    # A next-morning departure anchor is not a second hotel stay.
                    if (kind == 'accommodation' and previous_position == activity.get('position')
                            and not kept and minutes(activity['end_time']) <= 12 * 60):
                        changes.append({'path': path, 'action': 'remove_next_morning_hotel_departure_anchor', 'before': deepcopy(activity)})
                        continue
                    if kind == 'accommodation' and any(a['type']=='accommodation' for a in kept):
                        errors.append(f'{path}: multiple hotel entries on the same day; represent the actual overnight stay once, not check-in/rest/return placeholders with zero price')
                    kept.append(activity)
                    original_start = minutes(activity['start_time'])
                    duration = minutes(activity['end_time']) - original_start
                    intercity = kind in ('train', 'airplane')
                    row = None
                    if intercity:
                        other = plan['target_city'] if city == plan['start_city'] else plan['start_city']
                        services = self.services(city, other, kind)
                        id_key = 'TrainID' if kind == 'train' else 'FlightID'
                        matches = [r for r in services if r[id_key] == activity[id_key]]
                        if len(matches) != 1:
                            raise ValueError(f'{path}: unknown or ambiguous {id_key} {activity[id_key]} in {city}->{other}')
                        row = matches[0]
                        queries.append({'tool': 'intercity_transport_select', 'arguments': {'start_city':city,'end_city':other,'intercity_type':kind}, 'selected_record':row})
                        for key, field in (('start','From'),('end','To'),('start_time','BeginTime'),('end_time','EndTime'),('price','Cost')):
                            set_field(activity, key, row[field], path)
                        count_key, count = 'tickets', people
                        destination = activity['start']
                    else:
                        component = {'attraction':'attractions','accommodation':'accommodations'}.get(kind, 'restaurants')
                        row = self.table(component, city, activity['position'])
                        queries.append({'tool':component+'_select','arguments':{'city':city,'key':'name','op':'eq','value':activity['position']},'selected_record':row})
                        set_field(activity, 'price', row['price'], path)
                        destination = activity['position']
                        if kind == 'accommodation':
                            set_field(activity, 'room_type', row['numbed'], path)
                            count_key, count = 'rooms', activity.get('rooms', ceil(people / row['numbed']))
                        elif kind == 'attraction':
                            count_key, count = 'tickets', people
                        else:
                            count_key, count = None, people
                    if not isinstance(count, int) or isinstance(count, bool) or count < 1:
                        raise ValueError(f'{path}: invalid quantity {count_key}={count}')
                    if count_key:
                        set_field(activity, count_key, count, path)
                    set_field(activity, 'cost', round(activity['price'] * count, 2), path)

                    old_route = activity.get('transports', [])
                    route = []
                    arrival = previous_end
                    if previous_position is not None and previous_position != destination:
                        mode = activity.get('transport_mode') or ('metro' if any(s.get('mode')=='metro' for s in old_route) else old_route[0]['mode'] if old_route else 'metro')
                        departure = max(previous_end, minutes(old_route[0]['start_time']) if old_route else previous_end)
                        arguments = {'city':city,'start':previous_position,'end':destination,'start_time':clock(departure),'transport_type':mode}
                        raw = self.env.transportation.goto(**arguments)
                        if not isinstance(raw, list) or not raw:
                            raise ValueError(f'{path}: goto returned no route for {arguments}')
                        queries.append({'tool':'goto','arguments':arguments,'result':deepcopy(raw)})
                        for segment in raw:
                            item = deepcopy(segment)
                            unit = item.pop('cost')
                            item['price'] = unit
                            n = 1
                            if item['mode'] == 'taxi':
                                n = ceil(people / 4)
                                item['cars'] = n
                            elif item['mode'] == 'metro':
                                n = people
                                item['tickets'] = n
                            item['cost'] = round(unit * n, 2)
                            route.append(item)
                        arrival = minutes(route[-1]['end_time'])
                    elif previous_position is None and old_route:
                        errors.append(f'{path}: no known previous POI for initial route; do not invent an origin-city pickup')
                    set_field(activity, 'transports', route, path)
                    activity.pop('transport_mode', None)
                    if intercity:
                        if arrival > minutes(activity['start_time']):
                            options = [r for r in services if r['From']==activity['start'] and minutes(r['BeginTime']) >= arrival]
                            alternatives.append({'path':path,'earliest_arrival':clock(arrival),'choices':options[:10]})
                            errors.append(f'{path}: arrive {clock(arrival)} after departure {activity["start_time"]}; choose a later service from alternatives, or reschedule earlier activities')
                        city = other
                        previous_position = activity['end']
                    else:
                        if duration <= 0:
                            raise ValueError(f'{path}: activity duration must be positive')
                        start = max(original_start, arrival)
                        if kind != 'accommodation':
                            start = max(start, minutes(row['opentime']))
                        if kind in ('lunch','dinner'):
                            start = max(start, (11 if kind=='lunch' else 17) * 60)
                        set_field(activity, 'start_time', clock(start), path)
                        set_field(activity, 'end_time', clock(start + duration), path)
                        previous_position = activity['position']
                    previous_end = minutes(activity['end_time'])
                day['activities'] = kept
            errors.extend(plan_errors(json.dumps(plan, ensure_ascii=False), evidence=[{
                'tool':q['tool'],'arguments':q['arguments'],
                'result':{'success':True,'data':{'rows':[q['selected_record']]}}
            } for q in queries if 'selected_record' in q]))
            # Only unambiguous explicit phrases; no private task labels or defaults.
            numerals = {'一':1,'二':2,'两':2,'三':3,'四':4,'五':5,'六':6,'七':7,'八':8,'九':9,'十':10}
            matches = re.findall(r'(?:玩|游玩|旅游|旅行|游览)([一二两三四五六七八九十\d]+)天', request)
            days = {int(v) if v.isdigit() else numerals[v] for v in matches if v.isdigit() or v in numerals}
            if len(days)==1 and len(plan['itinerary']) != next(iter(days)):
                errors.append(f'Public request requires {next(iter(days))} day(s); itinerary has {len(plan["itinerary"])}. Replan within the requested days.')
            budgets = re.findall(r'预算\s*(\d+(?:\.\d+)?)\s*(?:元|人民币)', request)
            if len(set(budgets))==1:
                total = sum(a['cost'] + sum(t['cost'] for t in a['transports']) for d in plan['itinerary'] for a in d['activities'])
                if total > float(budgets[0]) + .01:
                    errors.append(f'Public request budget {budgets[0]}; grounded total {total:.2f}. Select cheaper real services/places, do not change prices.')
        except (KeyError, TypeError, ValueError, AttributeError) as exc:
            errors.append(str(exc))
        return {'success':not errors,'plan':plan,'errors':list(dict.fromkeys(errors)),
                'alternatives':alternatives,'changes':changes,'queries':queries}
