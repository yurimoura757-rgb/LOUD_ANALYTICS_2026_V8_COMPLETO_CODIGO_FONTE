"""Configuração central — nenhuma estatística é fornecida artificialmente."""
from pathlib import Path
import sys

# No .exe do PyInstaller, __file__ pode apontar para a pasta _internal.
# Dados editáveis devem ficar ao lado do executável para não se perderem.
ROOT = (Path(sys.executable).resolve().parent
        if getattr(sys, "frozen", False) else Path(__file__).resolve().parent)
DB_PATH = ROOT / 'loud_2026.sqlite3'
LOG_PATH = ROOT / 'loud_analytics.log'
TEAM_ID = 6961
YEAR = 2026
START = '2026-01-01'
END = '2026-12-31'
SOURCE = 'VLR.gg via vlrdevapi'
COLORS = {
    'bg': '#0b1110', 'panel': '#15211d', 'panel2': '#1e2c26',
    'accent': '#a6f536', 'accent_dark': '#2c713b', 'fg': '#f0f7f2',
    'muted': '#a2b4a7', 'line': '#36483c', 'red': '#fa717a', 'gold': '#ffcf70'
}
