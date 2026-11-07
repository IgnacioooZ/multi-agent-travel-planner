"""Apply the documented one-line scorer fix; never change benchmark data/rules."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lab.common import VENDOR

OLD = 'Inccorrect cost information of Inner-City Transport'
NEW = 'Incorrect cost information of Inner-City Transport'
PATCH_ID = 'transport-cost-column-typo-v1'


def apply_fix(path=None):
    path = path or VENDOR / 'chinatravel/symbol_verification/commonsense_constraint.py'
    source = path.read_bytes()
    if OLD.encode() not in source and NEW.encode() in source:
        return  # Idempotent: bootstrap may run multiple times.
    if source.count(OLD.encode()) != 1:
        raise RuntimeError('Unexpected upstream source; review scorer patch manually')
    path.write_bytes(source.replace(OLD.encode(), NEW.encode()))


if __name__ == '__main__':
    apply_fix()
    print(f'Applied scorer patch: {PATCH_ID}')
