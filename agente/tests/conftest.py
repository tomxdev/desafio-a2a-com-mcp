"""Poe `agente/` no sys.path: as pastas tem hifen e nao sao pacotes."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
