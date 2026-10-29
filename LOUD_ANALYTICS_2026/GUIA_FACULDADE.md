# Como apresentar o LOUD Analytics 2026 — V8

## 1. O que mostrar primeiro

**Dashboard**: partidas da LOUD em 2026 e aproveitamento por mapa, sem aguardar a API quando o cache está preenchido.

**Jogadores**: K/D, ACS, FK, 2K, 3K, 4K, aces e clutches. Abra os detalhes por jogador.

**Comparar Jogadores**: escolha `2022` e `Chamber` no campo de comparação internacional e clique em **Carregar atletas**; selecione um jogador externo e um da LOUD, se ambos tiverem dados. Explique a diferença de período e amostra.

**Agentes**: classifique por função e consulte composições por mapa.

**Mapas**: mostre a aba de vetos, com bans da LOUD vs. bans dos oponentes.

**Champions (2021–2026)**: rankings Top 10 e posição LOUD por métrica; análises de times, ataque/defesa, first kills e pistols ficam em outra aba.

**Recordes**: máximos entre dados armazenados, com separação de destaques da LOUD, Champions e idades de edições verificadas.

## 2. Baixe e conclua os dados antes da apresentação

- Execute `python app.py --completar` no ambiente virtual para atualizar informações detalhadas da LOUD.
- No painel Champions, carregue antecipadamente o ranking do(s) ano(s) que for apresentar.
- Se quiser dados de pistol, rounds e lados, clique antecipadamente em **Coletar estatísticas completas**; a coleta de todos os mapas de uma edição pode ser longa.
- Feche o programa antes de copiar o SQLite.
- Confira no arquivo `loud_2026.sqlite3` as estatísticas coletadas e faça backup.
- No Windows, execute `build_exe.bat` e leve a **pasta inteira** gerada em `dist`, incluindo o SQLite.

## 3. Perguntas que o professor pode fazer

**Por que SQLite?** Dados persistentes, consultas rápidas e acesso offline, sem instalar servidor.

**Por que Pandas?** Limpeza e agregação por jogador, mapa, agente, edição e lado da partida.

**Por que Tkinter?** Janela desktop nativa para navegação, filtros, tabelas, comparações e gráficos Matplotlib.

**Por que rankings históricos são sob demanda?** Evita coletar centenas de partidas toda vez que o programa abre; cada edição mantém cache próprio.

**Como os clutches são calculados?** Soma das contagens 1v1 a 1v5 retornadas na `series.performance()`. Na comparação histórica, depende da coluna CL do ranking do VLR.gg.

**Como o software evita estatísticas falsas?** Valor ausente vira N/D; nenhuma equipe, idade, veto ou round sem registro é inferido.

**Limitações conhecidas?** Nem todas as partidas trazem estatísticas avançadas, o ranking HTML pode mudar, a coleta histórica precisa de internet, idades têm cobertura parcial, e as posições mudam conforme a cobertura do cache.

## 4. Instalação rápida

```powershell
py -3.13 -m venv .venv
& .\.venv\Scripts\python.exe -m pip install -r requirements.txt
& .\.venv\Scripts\python.exe app.py
```

Para gerar o `.exe`: `& .\.venv\Scripts\python.exe -m pip install pyinstaller` e depois `.\build_exe.bat`.
