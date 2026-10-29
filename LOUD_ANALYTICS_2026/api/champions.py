"""Leaderboard histórico dos Champions: VLR.gg /event/stats/{id}.

Não há endpoint de leaderboard na VLRdevAPI. Esta fonte pública é HTML;
se o formato mudar, levantamos erro explícito em vez de inventar resultados.
O ranking é um snapshot por ano + agente e só é baixado sob pedido do usuário.
"""
import re
import requests
from bs4 import BeautifulSoup

EVENTS = {2021:449,2022:1015,2023:1657,2024:2097,2025:2283,2026:2766}
COLUMNS = {'maps':'Maps','rounds':'Rnd','rating':'R','acs':'ACS','kd':'K:D',
           'kast':'KAST','hs':'HS%','adr':'ADR','kills':'K','deaths':'D','assists':'A',
           'fk':'FK','fd':'FD','clutches':'CL'}

def event_url(year, agent='Todos'):
    if year not in EVENTS:raise ValueError('Ano fora dos Champions 2021–2026')
    url=f'https://www.vlr.gg/event/stats/{EVENTS[year]}/valorant-champions-{year}'
    # Filtro de agente usado pela página do VLR.gg; "all" é o agregado.
    return url+'?agent='+('all' if agent=='Todos' else agent.casefold().replace('/',''))+'&min_rounds=0'

def number(s, percent=False):
    if s is None:return None
    s=str(s).strip().replace(',','')
    if not s or s in ('-','N/A','—','–'):return None
    if percent:s=s.replace('%','')
    try:return float(s)
    except ValueError:return None

def parse_leaderboard(html):
    soup=BeautifulSoup(html,'html.parser')
    # Só aceita tabelas com cabeçalhos concretos de jogadores/K/D/A.
    table=None; headers=[]
    for t in soup.select('table'):
        h=[c.get_text(' ',strip=True).replace(' ','') for c in t.select('thead th')]
        if 'Player' in h and 'ACS' in h and 'K' in h and 'D' in h and 'A' in h:
            table=t;headers=h;break
    if table is None:
        raise ValueError('Formato da tabela de estatísticas do VLR.gg não reconhecido.')
    found=[]
    for tr in table.select('tbody tr'):
        cells=tr.find_all('td',recursive=False)
        if len(cells)!=len(headers):continue
        text={key:cell.get_text(' ',strip=True) for key,cell in zip(headers,cells)}
        player_cell=cells[headers.index('Player')]
        # VLR geralmente separa nick/team em nós; fallback conserva o texto completo.
        n=player_cell.select_one('.text-of,.mod-player-name,.player-name')
        tm=player_cell.select_one('.stats-player-country,.stats-player-team,.mod-player-team')
        full=text['Player'].strip()
        if n:
            name=n.get_text(' ',strip=True)
        else:
            name=full.split()[0] if full else ''
        if tm:team=tm.get_text(' ',strip=True)
        else:
            tail=full[len(name):].strip() if name and full.startswith(name) else ''
            team=tail.split()[-1] if tail else ''
        if not name:continue
        row={'player':name,'team':team}
        for field,col in COLUMNS.items():
            raw=text.get(col)
            if col=='CL' and raw and '/' in raw:
                first,second=raw.split('/',1)
                row['clutches']=int(number(first)) if number(first) is not None else None
                row['clutch_attempts']=int(number(second)) if number(second) is not None else None
                continue
            val=number(raw,field in ('kast','hs'))
            row[field]= (int(val) if val is not None else None) if field in ('maps','rounds','kills','deaths','assists','fk','fd','clutches') else val
        row.setdefault('clutch_attempts',None)
        found.append(row)
    if not found:raise ValueError('Tabela VLR sem linhas de jogadores: resposta incompleta.')
    # Nome, equipe são identificadores de leaderboard. Não retornar duplicatas.
    dedup={(p['player'].casefold(),p['team'].casefold()):p for p in found}
    return list(dedup.values())

def collect_leaderboard(year,agent='Todos'):
    url=event_url(year,agent)
    response=requests.get(url,headers={'User-Agent':'Mozilla/5.0 (compatible; LoudAnalytics/1.0)'},
                          timeout=(5,14))
    response.raise_for_status()
    if 'html' not in response.headers.get('Content-Type','text/html').lower():
        raise ValueError('A fonte não retornou HTML.')
    return parse_leaderboard(response.text),url
