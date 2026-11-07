"""Public output contract checks; no private tasks, hidden rules or scorer imports."""
import json
import math

from jsonschema import Draft7Validator
from lab.benchmark import output_schema


class InvalidPlan(ValueError):
    pass


def plan_errors(text, context=None, evidence=()):
    """Return actionable errors without modifying the model's answer."""
    try:
        plan = json.loads(text)
    except (ValueError, TypeError) as exc:
        return [f"JSON must be complete and parseable: {exc}"]
    errors = [f"{list(e.absolute_path)}: {e.message}"
              for e in Draft7Validator(output_schema()).iter_errors(plan)]
    if errors:
        return errors[:20]
    if not plan['itinerary']:
        return ['itinerary must contain at least one day with activities']

    def money(item, count_key, where):
        count = item.get(count_key)
        if not isinstance(count, int) or isinstance(count, bool) or count < 1:
            errors.append(f'{where}: require positive integer {count_key}')
            return
        price, cost = item['price'], item['cost']
        if not all(math.isfinite(v) and v >= 0 for v in (price, cost)):
            errors.append(f'{where}: price and cost must be finite and nonnegative')
        elif abs(price * count - cost) > 0.1:
            errors.append(f'{where}: cost must equal price * {count_key}; exclude incoming transport cost')

    def minutes(value, where):
        hour, minute = map(int, value.split(':'))
        if hour > 24 or minute > 59 or (hour == 24 and minute != 0):
            errors.append(f'{where}: invalid clock time {value}')
        return hour * 60 + minute

    visited = set()
    people = plan['people_number']
    if people < 1:
        errors.append('people_number must be positive')
    for day in plan['itinerary']:
        previous_end = None
        previous_position = None
        if not day['activities']:
            errors.append(f"day {day['day']}: activities must not be empty")
        for index, activity in enumerate(day['activities']):
            where = f"day {day['day']} activity {index}"
            kind = activity['type']
            start = minutes(activity['start_time'], where)
            end = minutes(activity['end_time'], where)
            if kind not in ('train', 'airplane') and start >= end:
                errors.append(f'{where}: activity end must be after start')
            if previous_end is not None and start < previous_end:
                errors.append(f'{where}: activity overlaps previous activity')
            # Public benchmark meal windows; no task-specific hidden constraints.
            meal_windows = {'lunch': (11 * 60, 14 * 60), 'dinner': (17 * 60, 20 * 60)}
            if kind in meal_windows:
                opens, closes = meal_windows[kind]
                if end <= opens or start >= closes:
                    errors.append(f'{where}: {kind} must overlap {opens // 60:02d}:00--{closes // 60:02d}:00; arrival alone is not a meal')
            if kind in ('train', 'airplane', 'attraction'):
                money(activity, 'tickets', where)
            elif kind == 'accommodation':
                money(activity, 'rooms', where)
                if not isinstance(activity.get('room_type'), int):
                    errors.append(f'{where}: room_type must be sandbox numbed integer')
            else:
                money({**activity, 'people': people}, 'people', where)
            if kind == 'attraction':
                position = activity['position']
                if position in visited:
                    errors.append(f'{where}: repeated attraction {position}; incoming travel is not a separate attraction')
                visited.add(position)

            destination = activity.get('start') if kind in ('train', 'airplane') else activity['position']
            segments = activity['transports']
            if segments:
                modes = [s['mode'] for s in segments]
                if modes not in (['walk'], ['taxi'], ['walk', 'metro', 'walk']):
                    errors.append(f'{where}: transports must be ONE goto route (walk/taxi or walk-metro-walk), not concatenated routes')
                if previous_position is not None and segments[0]['start'] != previous_position:
                    errors.append(f'{where}: incoming route must start at {previous_position}')
                if segments[-1]['end'] != destination:
                    errors.append(f'{where}: incoming route must end at {destination}')
                route_end = previous_end
                last_position = None
                for segment in segments:
                    ss = minutes(segment['start_time'], where)
                    se = minutes(segment['end_time'], where)
                    if se < ss or (route_end is not None and ss < route_end):
                        errors.append(f'{where}: route times overlap or run backwards')
                    if last_position is not None and segment['start'] != last_position:
                        errors.append(f'{where}: disconnected route segments')
                    if segment['mode'] == 'walk':
                        if segment['cost'] != 0 or segment['price'] != 0:
                            errors.append(f'{where}: walking price and cost must be zero')
                    else:
                        money(segment, 'cars' if segment['mode'] == 'taxi' else 'tickets', where + ' transport')
                    route_end, last_position = se, segment['end']
                if route_end > start:
                    errors.append(f'{where}: arrive before activity starts')
            elif previous_position is not None and previous_position != destination:
                errors.append(f'{where}: missing goto route from {previous_position} to {destination}')
            previous_end = end
            previous_position = activity.get('end') if kind in ('train', 'airplane') else activity['position']
    errors.extend(_known_place_errors(plan, context or {}, evidence))
    return list(dict.fromkeys(errors))[:20]


def _known_place_errors(plan, context, evidence):
    """Check the final schedule against public tool rows, not a worker's summary.

    A worker's is_open(10:00) cannot justify the planner moving the visit to 07:00.
    Only named rows with explicit city/category provenance are used here.
    """
    records = [record for handoff in context.get('handoffs', [])
               for record in handoff.get('evidence', [])] + list(evidence)
    places = {}
    for record in records:
        category = record['tool'].split('_')[0]
        if category not in ('attractions', 'restaurants'):
            continue
        result = record['result']
        data = result.get('data')
        if not result.get('success') or not isinstance(data, dict):
            continue
        city = record['arguments'].get('city')
        for row in data.get('rows', []):
            if all(key in row for key in ('name', 'opentime', 'endtime', 'price')):
                places[city, category, row['name']] = row

    def minute(value):
        hour, minute = map(int, value.split(':'))
        return hour * 60 + minute

    errors = []
    for day in plan['itinerary']:
        for activity in day['activities']:
            kind = activity['type']
            if kind not in ('attraction', 'breakfast', 'lunch', 'dinner'):
                continue
            category = 'attractions' if kind == 'attraction' else 'restaurants'
            name = activity['position']
            row = places.get((plan['target_city'], category, name))
            if row is None:
                continue  # No verified row: this partial check cannot certify the fact.
            start, end = minute(activity['start_time']), minute(activity['end_time'])
            opens, closes = minute(row['opentime']), minute(row['endtime'])
            if closes <= opens:
                closes += 24 * 60
            if not opens <= start < end <= closes:
                errors.append(f"day {day['day']} {name}: final visit must fit tool opening hours {row['opentime']}--{row['endtime']}; a previous query for another time is insufficient")
            if abs(activity['price'] - row['price']) > 0.1:
                errors.append(f"day {day['day']} {name}: price must match tool record {row['price']}")
    return errors
