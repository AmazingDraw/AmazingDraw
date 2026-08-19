import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
NATIVE = ROOT / 'card_engine_core' / 'native'
if NATIVE.is_dir():
    sys.path.insert(0, str(NATIVE))
CORE = ROOT / 'card_engine_core'
if CORE.is_dir():
    sys.path.insert(0, str(ROOT))
