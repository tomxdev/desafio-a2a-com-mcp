"""Preparo dos testes do servidor MCP."""

import os
import sys
from pathlib import Path

# As pastas tem hifen e nao sao pacotes importaveis.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Importar `servidor` exige a chave do requestState. Uma chave obviamente
# falsa serve aqui: nenhum teste depende do valor dela.
os.environ.setdefault("REQUEST_STATE_SECRET", "00" * 32)
