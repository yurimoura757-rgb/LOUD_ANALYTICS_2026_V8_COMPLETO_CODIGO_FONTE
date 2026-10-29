"""Extremos de idade publicados em páginas de cada edição da Liquipedia.

Idades expressas em anos completos NA DATA DE ABERTURA DO CHAMPIONS,
não na data atual. Apenas as edições efetivamente verificadas foram
incluídas; ausentes não são extrapoladas. Fonte reproduzível por URL.
"""
import pandas as pd

_VERIFIED = (
    (2021, '01/12/2021', 'Mais jovem', 'Khalil', 17,
     'https://liquipedia.net/valorant/VALORANT_Champions_Tour/2021/Champions/Player_Information'),
    (2021, '01/12/2021', 'Mais velho', 'JessieVash', 31,
     'https://liquipedia.net/valorant/VALORANT_Champions_Tour/2021/Champions/Player_Information'),
    (2022, '31/08/2022', 'Mais jovem', 'Alfajer', 17,
     'https://liquipedia.net/valorant/VCT/2022/Champions/Player_Information'),
    (2022, '31/08/2022', 'Mais velho', 'ANGE1', 32,
     'https://liquipedia.net/valorant/VCT/2022/Champions/Player_Information'),
    (2023, '06/08/2023', 'Mais jovem', 'cauanzin', 18,
     'https://liquipedia.net/valorant/VCT/2023/Champions/Player_Information'),
    (2023, '06/08/2023', 'Mais velho', 'ANGE1', 33,
     'https://liquipedia.net/valorant/VCT/2023/Champions/Player_Information'),
)


def verified_champions_ages():
    return pd.DataFrame(_VERIFIED,columns=[
        'Ano','Início do torneio','Categoria','Jogador','Idade (anos)','Fonte'])
