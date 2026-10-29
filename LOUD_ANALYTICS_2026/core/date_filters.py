"""Períodos de 2026 para filtros intuitivos e sem digitação manual."""
from calendar import monthrange
from datetime import date, timedelta

YEAR = 2026
MIN_DATE = date(YEAR, 1, 1)
MAX_DATE = date(YEAR, 12, 31)
MONTHS = ('Janeiro', 'Fevereiro', 'Março', 'Abril', 'Maio', 'Junho',
          'Julho', 'Agosto', 'Setembro', 'Outubro', 'Novembro', 'Dezembro')
ALL_PERIODS = ('Toda a temporada', 'Últimos 30 dias', 'Últimos 90 dias',
               '1º semestre', '2º semestre', *MONTHS, 'Escolher datas...')
CUSTOM_PERIOD = 'Escolher datas...'


def period_range(choice, start=None, end=None, today=None):
    """Devolve datas ISO inclusivas; levanta ValueError para entrada inválida.

    Períodos móveis são relativos à data atual, respeitando o intervalo da
    temporada. Quando já passou de 2026, podem não ter resultados.
    """
    today = today or date.today()
    if choice == CUSTOM_PERIOD:
        first = _to_date(start)
        last = _to_date(end)
    elif choice == 'Toda a temporada':
        first, last = MIN_DATE, MAX_DATE
    elif choice in ('Últimos 30 dias', 'Últimos 90 dias'):
        days = 30 if '30' in choice else 90
        first, last = today - timedelta(days=days - 1), today
        first, last = max(first, MIN_DATE), min(last, MAX_DATE)
    elif choice == '1º semestre':
        first, last = date(YEAR, 1, 1), date(YEAR, 6, 30)
    elif choice == '2º semestre':
        first, last = date(YEAR, 7, 1), MAX_DATE
    elif choice in MONTHS:
        month = MONTHS.index(choice) + 1
        first, last = date(YEAR, month, 1), date(YEAR, month, monthrange(YEAR, month)[1])
    else:
        raise ValueError(f'Período desconhecido: {choice}')
    if choice == CUSTOM_PERIOD and not (MIN_DATE <= first <= last <= MAX_DATE):
        raise ValueError('Selecione um intervalo válido dentro de 2026.')
    # Intervalo móvel inteiramente fora de 2026 produz seleção vazia,
    # não dados falsos ou datas invertidas enviadas ao filtro.
    if first > last:
        return '9999-12-31', '9999-12-31'
    return first.isoformat(), last.isoformat()


def _to_date(value):
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except (ValueError, TypeError) as exc:
        raise ValueError('Escolha datas válidas no calendário.') from exc


def date_label(value):
    d = _to_date(value)
    return f'{d.day:02d}/{d.month:02d}/{d.year}'
