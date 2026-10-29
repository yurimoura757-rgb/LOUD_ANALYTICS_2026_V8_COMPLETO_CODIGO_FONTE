"""Classes dos agentes (nomes verificados na lista de agentes do VLR em 2026).
Para novos agentes ainda não cadastrados, exibe "Não classificado".
"""
ROLES = {
    'Duelista': ('Iso','Jett','Neon','Phoenix','Raze','Reyna','Waylay','Yoru'),
    'Iniciador': ('Breach','Fade','Gekko','KAY/O','Kayo','Skye','Sova','Tejo'),
    'Controlador': ('Astra','Brimstone','Clove','Harbor','Miks','Omen','Viper'),
    'Sentinela': ('Chamber','Cypher','Deadlock','Killjoy','Sage','Veto','Vyse'),
}
_BY_NAME = {a.casefold().replace('/','').replace(' ',''): role for role,names in ROLES.items() for a in names}

def role_of(agent):
    if not agent or not isinstance(agent,str):
        return 'Não classificado'
    names=[s.strip() for s in agent.split(',') if s.strip()]
    if len(names)!=1:
        return 'Não classificado'
    return _BY_NAME.get(names[0].casefold().replace('/','').replace(' ',''), 'Não classificado')
