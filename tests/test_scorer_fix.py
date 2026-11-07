from scripts.apply_upstream_fixes import OLD, NEW, apply_fix
from types import SimpleNamespace

from lab.common import use_upstream


def test_patch_only_changes_typo_and_is_repeatable(tmp_path):
    path = tmp_path / 'scorer.py'
    before = f"columns = ['{OLD}']\r\nerror_column = '{NEW}'\r\n".encode()
    path.write_bytes(before)
    apply_fix(path)
    apply_fix(path)
    assert path.read_bytes() == before.replace(OLD.encode(), NEW.encode())


def test_bad_taxi_followed_by_bad_route_is_failure_not_exception(monkeypatch):
    use_upstream()
    from chinatravel.symbol_verification import commonsense_constraint as scorer
    taxi = {'start': 'A', 'end': 'B', 'mode': 'taxi', 'start_time': '09:00',
            'end_time': '09:10', 'price': 10, 'cost': 10, 'distance': 1}
    monkeypatch.setattr(scorer, 'innercity_transport', SimpleNamespace(goto=lambda **kw: [taxi]))
    # Missing cars sets the cost error; two segments then set all three errors.
    plan = {'itinerary': [{'activities': [{'transports': [taxi]}, {'transports': [taxi, taxi]}]}]}
    table, errors = scorer.Is_transport_correct({'target_city': '杭州'}, plan)
    assert table.shape == (1, 3) and table.iloc[0].sum() == 3
    assert any('cost=price*cars' in error for error in errors)
    assert any('one-stage' in error for error in errors)
