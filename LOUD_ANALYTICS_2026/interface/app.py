"""Interface desktop com filtros acessíveis e comparações estatísticas."""
import queue
import threading
import logging
import time
import webbrowser
import tkinter as tk
from tkinter import ttk, messagebox
import pandas as pd
from config import COLORS as C
from core.analytics import Analytics, filtered
from core.data_engine import DataEngine
from core.diagnostics import timed
LOGGER = logging.getLogger(__name__)
from database.db_manager import Database
from interface.charts import ChartPanel
from api.champions import EVENTS, collect_leaderboard, event_url
from core.agent_roles import ROLES, role_of
from core.extra_analytics import compositions, veto_summary, local_records
from core.world_analytics import teams_summary, pistol_summary, side_rankings, agent_top
from core.age_records import verified_champions_ages
from interface.calendar_picker import CalendarPicker
from core.date_filters import (ALL_PERIODS, CUSTOM_PERIOD, MIN_DATE, MAX_DATE,
                               period_range, date_label)
from datetime import date

SECTIONS=['Dashboard','Jogadores','Comparar Jogadores','Partidas','Mapas',
          'Agentes','Campeonatos','Evolução Estatística','Champions (2021–2026)','Recordes']


def fmt(v):
    if v is None or (not isinstance(v,(tuple,list,dict)) and pd.isna(v)):
        return 'N/D'
    if isinstance(v,float):
        return f'{v:.2f}'
    return str(v)


class LoudApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.db=Database();self.ana=Analytics(self.db);self.engine=DataEngine(self.db)
        self.title('LOUD Analytics 2026 | Valorant')
        self.geometry('1440x860');self.minsize(1040,700)
        self.configure(bg=C['bg'])
        self._style()
        self.q=queue.Queue();self.updating=False
        self._closing=False
        self.ready=False
        self._snapshot_generation=0
        self._startup_sync_started=False
        self._has_cached_matches=False
        self._partial_reload_job=None
        self.sync_error=None
        self.local_error=None
        self._local_load_started=0.0
        self._sync_started=0.0
        self._last_sync_stage='Ainda não iniciado'
        self.compare_selected_ids=[]
        self.compare_year=tk.StringVar(value='2022')
        self.compare_agent=tk.StringVar(value='Chamber')
        self.external_year=2022
        self.external_agent='Chamber'
        self.external_pool=pd.DataFrame()
        self.external_loading=False
        self.world_year=tk.StringVar(value='2026')
        self.world_metric=tk.StringVar(value='Kills')
        self.world_tab=0
        self.world_details_tab=0
        self.world_loading=False
        self.deep_loading=False
        self.deep_status=''
        self.role_filter=tk.StringVar(value='Todas as funções')
        self.compare_search=tk.StringVar(value='')
        self.compare_mode=tk.StringVar(value='Radar normalizado')
        self.page=SECTIONS[0]
        self.filters={k:tk.StringVar(value='Todos') for k in ('tournament','opponent','map_name','agent')}
        self.period=tk.StringVar(value='Toda a temporada')
        self.custom_start=MIN_DATE
        self.custom_end=MAX_DATE
        self.minimum=tk.IntVar(value=1)
        self.chart=None;self.current_table=None
        self.sidebar=tk.Frame(self,bg=C['panel'],width=228)
        self.sidebar.pack(side='left',fill='y');self.sidebar.pack_propagate(False)
        self.logo=tk.Label(self.sidebar,text='LOUD  /  ANALYTICS',font=('Segoe UI',15,'bold'),
             fg=C['accent'],bg=C['panel'],pady=28)
        self.logo.pack(fill='x')
        self.nav_buttons={}
        for s in SECTIONS:
            b=tk.Button(self.sidebar,text='  '+s,anchor='w',relief='flat',bd=0,
                padx=15,pady=13,font=('Segoe UI',10),
                fg=C['fg'],bg=C['panel'],highlightthickness=0,activebackground=C['accent_dark'],
                activeforeground=C['fg'],cursor='hand2',
                command=lambda name=s:self.go(name))
            b.pack(fill='x',padx=8,pady=1)
            self.nav_buttons[s]=b
        tk.Label(self.sidebar,text='LOUD  •  VALORANT\nTEMPORADA 2026',
             bg=C['panel'],fg=C['muted'],font=('Segoe UI',9),justify='left').pack(side='bottom',pady=24)
        self.shell=tk.Frame(self,bg=C['bg'])
        self.shell.pack(side='right',expand=True,fill='both')
        head=tk.Frame(self.shell,bg=C['bg'],padx=24,pady=15)
        head.pack(fill='x')
        self.heading=tk.Label(head,text='',fg=C['fg'],bg=C['bg'],font=('Segoe UI',23,'bold'))
        self.heading.pack(side='left')
        # Botão voluntário: nunca é acionado ao abrir com cache preenchido.
        self.refresh_button=tk.Button(head,text='Atualizar dados',
            bg=C['panel2'],fg=C['fg'],activebackground=C['accent_dark'],
            activeforeground=C['fg'],relief='flat',bd=0,cursor='hand2',
            font=('Segoe UI',10,'bold'),padx=16,pady=9,
            command=lambda:self.startup_sync(manual=True))
        self.refresh_button.pack(side='right')
        # Filtro em duas linhas: período com opções prontas e seletores agrupados.
        # Nenhuma data precisa ser digitada manualmente.
        self.filterbox=tk.Frame(self.shell,bg=C['panel'],padx=16,pady=11)
        self.filterbox.pack(fill='x',padx=24,pady=(0,10))
        datebar=tk.Frame(self.filterbox,bg=C['panel'])
        datebar.pack(fill='x',pady=(0,9))
        tk.Label(datebar,text='PERÍODO',bg=C['panel'],fg=C['muted'],
                 font=('Segoe UI',9,'bold')).pack(side='left',padx=(0,12))
        self.period_cb=ttk.Combobox(datebar,textvariable=self.period,
                   values=list(ALL_PERIODS),state='readonly',width=22)
        self.period_cb.pack(side='left')
        self.period_cb.bind('<<ComboboxSelected>>',self.on_period_changed)
        self.period_summary=tk.Label(datebar,text='01/01/2026  —  31/12/2026',
                          bg=C['panel'],fg=C['fg'],font=('Segoe UI',10))
        self.period_summary.pack(side='left',padx=18)
        tk.Button(datebar,text='Limpar filtros',bg=C['panel2'],fg=C['muted'],
                  activeforeground=C['fg'],activebackground=C['panel2'],
                  cursor='hand2',relief='flat',padx=12,pady=6,
                  command=self.reset_filters).pack(side='right')
        self.date_buttons=tk.Frame(self.filterbox,bg=C['panel'])
        self.start_btn=tk.Button(self.date_buttons,bg=C['panel2'],fg=C['fg'],
                   activebackground=C['accent_dark'],activeforeground=C['fg'],
                   relief='flat',bd=0,cursor='hand2',padx=12,pady=8,
                   command=lambda:self.open_calendar('start'))
        self.start_btn.pack(side='left',padx=(0,10))
        self.end_btn=tk.Button(self.date_buttons,bg=C['panel2'],fg=C['fg'],
                   activebackground=C['accent_dark'],activeforeground=C['fg'],
                   relief='flat',bd=0,cursor='hand2',padx=12,pady=8,
                   command=lambda:self.open_calendar('end'))
        self.end_btn.pack(side='left')
        tk.Label(self.date_buttons,text='Selecione os dias no calendário.',
                 bg=C['panel'],fg=C['muted']).pack(side='left',padx=12)
        self.update_date_labels()
        row=tk.Frame(self.filterbox,bg=C['panel'])
        row.pack(fill='x')
        for i,(key,label) in enumerate([('tournament','Campeonato'),('opponent','Adversário'),
                                       ('map_name','Mapa'),('agent','Agente')]):
            cell=tk.Frame(row,bg=C['panel'])
            cell.grid(row=0,column=i,sticky='ew',padx=(0 if i==0 else 8,0))
            row.grid_columnconfigure(i,weight=1,uniform='filter')
            tk.Label(cell,text=label,bg=C['panel'],fg=C['muted'],
                     font=('Segoe UI',9)).pack(anchor='w',pady=(0,3))
            cb=ttk.Combobox(cell,textvariable=self.filters[key],values=['Todos'],
                            state='readonly',width=12)
            cb.pack(fill='x');cb.bind('<<ComboboxSelected>>',lambda _e:self.render())
            setattr(self,'cb_'+key,cb)
        # Mensagem de cobertura, não um indicador de sincronização: permanece
        # discreta e só aparece quando faltam estatísticas no arquivo local.
        self.coverage_panel=tk.Frame(self.shell,bg=C['panel2'],padx=13,pady=9)
        self.coverage_info=tk.Label(self.coverage_panel,text='',bg=C['panel2'],
            fg=C['fg'],font=('Segoe UI',9),anchor='w')
        self.coverage_info.pack(side='left',fill='x',expand=True)
        self.complete_button=tk.Button(self.coverage_panel,text='Completar estatísticas',
            bg=C['accent_dark'],fg=C['fg'],activebackground=C['accent'],
            activeforeground=C['bg'],cursor='hand2',relief='flat',bd=0,
            font=('Segoe UI',9,'bold'),padx=11,pady=7,
            command=lambda:self.startup_sync(manual=True,details_only=True))
        self.complete_button.pack(side='right',padx=(9,0))
        self.main=tk.Frame(self.shell,bg=C['bg'])
        self.main.pack(fill='both',expand=True,padx=24,pady=(2,3))
        # Renderiza a janela ANTES de consultar a base ou desenhar gráficos.
        # A carga de dados ocorre fora da thread do Tkinter.
        self.go('Dashboard')
        # Primeiro carrega o SQLite. A rede só será consultada se a base estiver vazia.
        self.after(120,self.poll)
        self.after(80,self.load_local_snapshot)
        self.after(8000,self._watch_cache)
        self.after(20000,self._watch_sync)
        self.protocol("WM_DELETE_WINDOW", self.close)

    def close(self):
        """Interrompe callbacks agendados antes de destruir a janela."""
        if self._closing:
            return
        self._closing=True
        for job in self.tk.call('after', 'info'):
            try:
                self.after_cancel(job)
            except tk.TclError:
                pass
        self.destroy()

    def update_date_labels(self):
        self.start_btn.config(text='📅  Início: '+date_label(self.custom_start))
        self.end_btn.config(text='📅  Fim: '+date_label(self.custom_end))

    def on_period_changed(self, _event=None):
        is_custom=self.period.get()==CUSTOM_PERIOD
        if is_custom:
            self.date_buttons.pack(fill='x',before=self.date_buttons.master.winfo_children()[-1],pady=(0,9))
        else:
            self.date_buttons.pack_forget()
        self.update_period_summary()
        self.render()

    def update_period_summary(self):
        start,end=period_range(self.period.get(),self.custom_start,self.custom_end)
        if start=='9999-12-31':
            text='Nenhum dia de 2026 neste período'
        else:
            text=f'{date_label(start)}  —  {date_label(end)}'
        self.period_summary.config(text=text)

    def open_calendar(self, which):
        initial=self.custom_start if which=='start' else self.custom_end
        title='Selecionar data inicial' if which=='start' else 'Selecionar data final'
        def selected(value):
            if which=='start':
                self.custom_start=value
                if self.custom_end<value:
                    self.custom_end=value
            else:
                self.custom_end=value
                if self.custom_start>value:
                    self.custom_start=value
            self.update_date_labels()
            self.update_period_summary()
            self.render()
        CalendarPicker(self,initial,selected,title=title)

    def reset_filters(self):
        for v in self.filters.values():v.set('Todos')
        self.period.set('Toda a temporada')
        self.custom_start,self.custom_end=MIN_DATE,MAX_DATE
        self.update_date_labels()
        self.date_buttons.pack_forget()
        self.update_period_summary()
        self.render()

    def _style(self):
        sty=ttk.Style(self)
        sty.theme_use('clam')
        sty.configure('Treeview',background=C['panel'],foreground=C['fg'],fieldbackground=C['panel'],
                rowheight=33,borderwidth=1,relief='flat',bordercolor=C['line'],font=('Segoe UI',10))
        sty.configure('Treeview.Heading',background=C['panel2'],foreground=C['accent'],
                      relief='flat',borderwidth=1,font=('Segoe UI',10,'bold'))
        sty.map('Treeview',background=[('selected',C['accent_dark'])])
        sty.configure('TCombobox',fieldbackground=C['panel2'],background=C['panel2'],
                      foreground=C['fg'],selectbackground=C['panel2'],selectforeground=C['fg'])
        sty.map('TCombobox',fieldbackground=[('readonly',C['panel2'])],
                foreground=[('readonly',C['fg'])],background=[('readonly',C['panel2'])],
                selectbackground=[('readonly',C['panel2'])],
                selectforeground=[('readonly',C['fg'])])
        sty.configure('Vertical.TScrollbar',background=C['panel2'],
                      troughcolor=C['panel'],arrowcolor=C['fg'],
                      bordercolor=C['panel'])
        sty.configure('TEntry',fieldbackground=C['panel2'],foreground=C['fg'])
        sty.configure('TButton',background=C['panel2'],foreground=C['fg'],padding=8)
        sty.configure('TNotebook',background=C['bg'],borderwidth=0)
        sty.configure('TNotebook.Tab',background=C['panel'],foreground=C['fg'],
                      padding=(19,10),font=('Segoe UI',10,'bold'))
        sty.map('TNotebook.Tab',background=[('selected',C['accent_dark'])],
                foreground=[('selected',C['fg'])])

    def go(self,name):
        self.page=name
        for s,b in self.nav_buttons.items():
            b.configure(bg=C['accent_dark'] if s==name else C['panel'])
        self.render()

    def clear(self):
        job=getattr(self,'_compare_redraw_job',None)
        if job is not None:
            self.after_cancel(job)
            self._compare_redraw_job=None
        for child in self.main.winfo_children():child.destroy()
        self.chart=None;self.current_table=None
        self.heading.configure(text=self.page)

    def refresh_filters(self):
        d={ 'tournament':self.ana.matches().get('tournament',pd.Series(dtype=str)),
            'opponent':self.ana.matches().get('opponent',pd.Series(dtype=str)),
            'map_name':self.ana.maps().get('map_name',pd.Series(dtype=str)),
            'agent':self.ana.players().get('agent',pd.Series(dtype=str)) }
        for k,series in d.items():
            values=['Todos']+sorted(set(str(x) for x in series.dropna() if str(x)))
            getattr(self,'cb_'+k)['values']=values
            if self.filters[k].get() not in values:self.filters[k].set('Todos')

    def update_coverage(self):
        if not self.ready:
            return
        matches=self.ana.matches()
        completed=matches[matches.status.eq('completed')]
        total=len(completed)
        done=int(completed.details_complete.eq(1).sum()) if total else 0
        map_count=len(self.ana.maps())
        player_count=len(self.ana.players())
        if total>done:
            self.coverage_info.config(text=(
                f'Cache parcial: {done}/{total} partidas com estatísticas completas '
                f' • {map_count} mapas • {player_count} registros de jogador'))
            if not self.coverage_panel.winfo_manager():
                self.coverage_panel.pack(fill='x',padx=24,pady=(0,8),before=self.main)
        else:
            self.coverage_panel.pack_forget()
        self.complete_button.config(state='disabled' if self.updating else 'normal')

    def missing_stats(self, title, detail):
        pane=tk.Frame(self.main,bg=C['panel'],padx=22,pady=22)
        pane.pack(fill='x',pady=14)
        tk.Label(pane,text=title,bg=C['panel'],fg=C['fg'],
            font=('Segoe UI',13,'bold')).pack(anchor='w')
        tk.Label(pane,text=detail,bg=C['panel'],fg=C['muted'],
            font=('Segoe UI',10),wraplength=760,justify='left').pack(anchor='w',pady=(8,12))
        if not self.ana.matches().empty:
            self.action_button(pane,'Completar estatísticas',
                lambda:self.startup_sync(manual=True,details_only=True),True).pack(anchor='w')

    def data(self):
        f={k:v.get() for k,v in self.filters.items()}
        beginning,ending=period_range(self.period.get(),self.custom_start,self.custom_end)
        base={'start':beginning,'end':ending}
        matches=filtered(self.ana.matches(),tournament=f['tournament'],
                         opponent=f['opponent'],**base)
        maps=filtered(self.ana.maps(),tournament=f['tournament'],
                      opponent=f['opponent'],map_name=f['map_name'],**base)
        players=filtered(self.ana.players(),**f,**base)
        # Filtros de mapas/agentes também restringem as outras visões por ID.
        if f['map_name']!='Todos':
            match_ids=set(maps.match_id)
            matches=matches[matches.id.isin(match_ids)].copy()
            players=players[players.match_id.isin(match_ids)].copy()
        if f['agent']!='Todos':
            match_ids=set(players.match_id)
            map_keys=set(zip(players.match_id,players.map_index))
            matches=matches[matches.id.isin(match_ids)].copy()
            if not maps.empty:
                maps=maps[[tuple(x) in map_keys for x in maps[['match_id','map_index']].to_numpy()]].copy()
        return matches,maps,players

    def section_label(self,text,parent=None):
        return tk.Label(parent or self.main,text=text,bg=C['bg'],fg=C['fg'],
                        font=('Segoe UI',13,'bold'),anchor='w')

    def note(self,text,parent=None):
        t=tk.Label(parent or self.main,text=text,fg=C['muted'],bg=C['bg'],
                    justify='left',wraplength=900,font=('Segoe UI',9))
        t.pack(anchor='w',pady=6)
        return t

    def card_row(self,items):
        holder=tk.Frame(self.main,bg=C['bg']);holder.pack(fill='x',pady=(2,12))
        for k,v in items:
            panel=tk.Frame(holder,bg=C['panel'],padx=15,pady=13)
            panel.pack(side='left',fill='both',expand=True,padx=(0,9))
            tk.Label(panel,text=str(k).upper(),bg=C['panel'],fg=C['muted'],
                     font=('Segoe UI',9)).pack(anchor='w')
            tk.Label(panel,text=fmt(v),bg=C['panel'],fg=C['accent'],
                     font=('Segoe UI',23,'bold')).pack(anchor='w')

    def table(self,parent,df,height=12,onselect=None):
        box=tk.Frame(parent,bg=C['panel'],highlightbackground=C['line'],
                     highlightthickness=1);box.pack(fill='both',expand=True,pady=6)
        if df is None or df.empty:
            tk.Label(box,text='Nenhum registro disponível para os filtros atuais.\nEscolha outro período ou abra novamente após a coleta inicial.',
                fg=C['muted'],bg=C['panel'],font=('Segoe UI',11),pady=26).pack(fill='both',expand=True)
            return None
        cols=list(df.columns)
        tree=ttk.Treeview(box,columns=cols,show='headings',height=height,selectmode='browse')
        yscroll=ttk.Scrollbar(box,orient='vertical',command=tree.yview)
        xscroll=ttk.Scrollbar(box,orient='horizontal',command=tree.xview)
        tree.configure(yscrollcommand=yscroll.set,xscrollcommand=xscroll.set)
        tree.grid(row=0,column=0,sticky='nsew');yscroll.grid(row=0,column=1,sticky='ns')
        xscroll.grid(row=1,column=0,sticky='ew')
        box.grid_rowconfigure(0,weight=1);box.grid_columnconfigure(0,weight=1)
        tree.tag_configure('even',background=C['panel'])
        tree.tag_configure('odd',background=C['panel2'])
        tree.tag_configure('selected',foreground=C['fg'])
        for col in cols:
            tree.heading(col,text=col,command=lambda c=col:self.sort_tree(tree,c,False))
            numeric=pd.api.types.is_numeric_dtype(df[col])
            width=max(115,min(260,len(str(col))*12+28))
            if col in ('Composição','Jogador','Campeonato','Partidas (IDs)'):
                width=250 if col!='Partidas (IDs)' else 180
            tree.column(col,width=width,stretch=False,anchor='e' if numeric else 'w')
        for index,(_,r) in enumerate(df.iterrows()):
            tree.insert('','end',values=[fmt(x) for x in r.tolist()],tags=('even' if index%2==0 else 'odd',))
        if onselect:tree.bind('<Double-1>',lambda _e:onselect(tree,cols))
        self.current_table=df.copy()
        return tree

    @staticmethod
    def sort_tree(tree,col,reverse):
        rows=[(tree.set(i,col),i) for i in tree.get_children('')]
        def to_value(v):
            try:return (0,float(v))
            except ValueError:return (1,v.casefold())
        rows.sort(key=lambda x:to_value(x[0]),reverse=reverse)
        for n,(_,item) in enumerate(rows):
            tree.move(item,'',n)
            tree.item(item,tags=('even' if n%2==0 else 'odd',))
        tree.heading(col,command=lambda:LoudApp.sort_tree(tree,col,not reverse))

    def chart_at(self,parent):
        panel=tk.Frame(parent,bg=C['panel'])
        panel.pack(fill='both',expand=True,pady=10)
        self.chart=ChartPanel(panel)
        return self.chart

    def render(self):
        if not self.ready:
            self.clear()
            pane=tk.Frame(self.main,bg=C['panel'],padx=28,pady=26)
            pane.pack(fill='x',pady=16)
            tk.Label(pane,text='LOUD  /  ANALYTICS',bg=C['panel'],fg=C['accent'],
                font=('Segoe UI',20,'bold')).pack(anchor='w')
            tk.Label(pane,text='Preparando suas estatísticas locais…',bg=C['panel'],
                fg=C['muted'],font=('Segoe UI',11)).pack(anchor='w',pady=(10,0))
            return
        try:
            self.clear()
            matches,maps,players=self.data()
            if self.page=='Dashboard' and matches.empty:
                self.empty_dashboard()
            elif self.page=='Dashboard':self.dashboard(matches,maps)
            elif self.page=='Jogadores':self.jogadores(players)
            elif self.page=='Comparar Jogadores':self.comparar(players)
            elif self.page=='Partidas':self.partidas(matches)
            elif self.page=='Mapas':self.mapas(maps,players)
            elif self.page=='Agentes':self.agentes(players)
            elif self.page=='Campeonatos':self.campeonatos(matches)
            elif self.page=='Evolução Estatística':self.evolucao(players)
            elif self.page=='Champions (2021–2026)':self.champions_page()
            elif self.page=='Recordes':self.recordes_page(players)
        except Exception as exc:
            LOGGER.exception('Erro na visualização: %s',exc)
            self.note(f'Não foi possível exibir esta tela: {exc}')

    def empty_dashboard(self):
        """Estado inicial informativo; não exibe progresso de sincronização."""
        panel=tk.Frame(self.main,bg=C['panel'],padx=30,pady=28,
                       highlightbackground=C['line'],highlightthickness=1)
        panel.pack(fill='x',pady=16)
        tk.Label(panel,text='Nenhuma partida disponível ainda',bg=C['panel'],
                 fg=C['fg'],font=('Segoe UI',16,'bold')).pack(anchor='w')
        tk.Label(panel,text='Coletando dados na primeira execução. Nas próximas aberturas, os dados salvos serão exibidos diretamente. Você também pode usar Atualizar dados.',
                 bg=C['panel'],fg=C['muted'],font=('Segoe UI',10),
                 justify='left',wraplength=740).pack(anchor='w',pady=(10,6))
        error=self.sync_error or self.local_error
        if error:
            tk.Label(panel,text='Não foi possível carregar os dados:',
                     bg=C['panel'],fg=C['red'],font=('Segoe UI',10,'bold')).pack(anchor='w',pady=(14,3))
            tk.Label(panel,text=str(error),bg=C['panel'],fg=C['fg'],
                     font=('Segoe UI',10),justify='left',wraplength=750).pack(anchor='w')
            tk.Label(panel,text='No terminal: python app.py --diagnostico  |  Para tentar novamente: python app.py --update',
                     bg=C['panel'],fg=C['muted'],font=('Segoe UI',9),
                     justify='left',wraplength=750).pack(anchor='w',pady=(12,0))

    def dashboard(self,matches,maps):
        x=self.ana.overview(matches,maps)
        self.card_row([('Partidas',x['partidas']),('Vitórias',x['vitórias']),
                ('Derrotas',x['derrotas']),('Win rate %',x['win_rate']),
                ('Mapas',x['mapas']),('Saldo rounds',x['round_diff'])])
        split=tk.Frame(self.main,bg=C['bg'])
        split.pack(fill='both',expand=True,pady=(0,6))
        split.grid_columnconfigure(0,weight=5,uniform='dash')
        split.grid_columnconfigure(1,weight=5,uniform='dash')
        split.grid_rowconfigure(0,weight=1)
        left=tk.Frame(split,bg=C['bg'])
        left.grid(row=0,column=0,sticky='nsew',padx=(0,10))
        right=tk.Frame(split,bg=C['bg'])
        right.grid(row=0,column=1,sticky='nsew')
        c=self.chart_at(left)
        c.bars(self.ana.maps_summary(maps),'Mapa','WR %','Win rate por mapa')
        if maps.empty:
            self.note('Win rate por mapa: faltam placares detalhados no cache. Use Completar estatísticas.',left)
        self.recent_matches(right,matches)
        a,b=self.ana.streaks(matches)
        self.note(f'Maior sequência de vitórias: {a}   •   Maior sequência de derrotas: {b}')

    def recent_matches(self,parent,matches):
        """Destaque da última série e cards legíveis dos jogos anteriores."""
        title=tk.Frame(parent,bg=C['bg'])
        title.pack(fill='x',pady=(0,9))
        tk.Label(title,text='ÚLTIMAS PARTIDAS',font=('Segoe UI',13,'bold'),
                 fg=C['fg'],bg=C['bg']).pack(side='left')
        tk.Button(title,text='Ver histórico  ›',bg=C['bg'],fg=C['accent'],
                  activebackground=C['bg'],activeforeground=C['fg'],
                  bd=0,relief='flat',cursor='hand2',font=('Segoe UI',9,'bold'),
                  command=lambda:self.go('Partidas')).pack(side='right')

        completed=(matches[matches.status.eq('completed') & matches.won.isin([0,1])]
                   .sort_values('date_utc',ascending=False))
        if completed.empty:
            empty=tk.Frame(parent,bg=C['panel'],padx=24,pady=32)
            empty.pack(fill='x')
            tk.Label(empty,text='Ainda não há resultados neste período.',
                     fg=C['fg'],bg=C['panel'],font=('Segoe UI',11,'bold')).pack(anchor='w')
            tk.Label(empty,text='Escolha outro período para visualizar os resultados.',
                     fg=C['muted'],bg=C['panel'],font=('Segoe UI',9)).pack(anchor='w',pady=(6,0))
            return

        latest=completed.iloc[0]
        won=latest.won==1
        accent=C['accent'] if won else C['red']
        panel=tk.Frame(parent,bg=C['panel'],padx=18,pady=16,
                       highlightbackground=C['line'],highlightthickness=1)
        panel.pack(fill='x',pady=(0,12))
        top=tk.Frame(panel,bg=C['panel']);top.pack(fill='x')
        tk.Label(top,text='CONFRONTO MAIS RECENTE',bg=C['panel'],fg=C['muted'],
                 font=('Segoe UI',9,'bold')).pack(side='left')
        tk.Label(top,text='VITÓRIA' if won else 'DERROTA',bg=C['accent_dark'] if won else '#572d35',
                 fg=C['fg'],font=('Segoe UI',9,'bold'),padx=10,pady=5).pack(side='right')
        score=tk.Frame(panel,bg=C['panel']);score.pack(fill='x',pady=(12,4))
        score.grid_columnconfigure(0,weight=1)
        score.grid_columnconfigure(2,weight=1)
        tk.Label(score,text='LOUD',bg=C['panel'],fg=C['accent'],
                 font=('Segoe UI',17,'bold')).grid(row=0,column=0,sticky='w')
        tk.Label(score,text=fmt(latest.team_score)+'  :  '+fmt(latest.opponent_score),
                 bg=C['panel'],fg=C['fg'],font=('Segoe UI',25,'bold')).grid(row=0,column=1,padx=6)
        tk.Label(score,text=str(latest.opponent),bg=C['panel'],fg=C['fg'],
                 wraplength=175,justify='right',font=('Segoe UI',12,'bold')).grid(row=0,column=2,sticky='e')
        dt=self.match_date(latest.date_utc)
        tk.Label(panel,text=f'{latest.tournament}   •   {dt}',bg=C['panel'],
                 fg=C['muted'],font=('Segoe UI',9),wraplength=400).pack(anchor='w',pady=(7,11))
        actions=tk.Frame(panel,bg=C['panel']);actions.pack(fill='x')
        self.action_button(actions,'Ver detalhes',lambda mid=int(latest.id):self.open_match_detail(mid),True).pack(side='left',padx=(0,9))
        if self.valid_match_url(latest.url):
            self.action_button(actions,'Abrir no VLR.gg',lambda url=latest.url:webbrowser.open(url),False).pack(side='left')

        other=completed.iloc[1:6]
        if other.empty:return
        tk.Label(parent,text='CONFRONTOS ANTERIORES',font=('Segoe UI',9,'bold'),
                 bg=C['bg'],fg=C['muted']).pack(anchor='w',pady=(0,7))
        # A lista usa uma área rolável, evitando cortes nas janelas menores.
        listing=tk.Frame(parent,bg=C['bg']);listing.pack(fill='both',expand=True)
        canvas=tk.Canvas(listing,bg=C['bg'],highlightthickness=0,bd=0)
        scrollbar=ttk.Scrollbar(listing,orient='vertical',command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side='right',fill='y');canvas.pack(side='left',fill='both',expand=True)
        inner=tk.Frame(canvas,bg=C['bg'])
        window=canvas.create_window((0,0),window=inner,anchor='nw')
        inner.bind('<Configure>',lambda _e:canvas.configure(scrollregion=canvas.bbox('all')))
        canvas.bind('<Configure>',lambda e:canvas.itemconfigure(window,width=e.width))
        for _,m in other.iterrows():
            self.mini_match(inner,m)

    @staticmethod
    def match_date(value):
        try:
            return date.fromisoformat(str(value)[:10]).strftime('%d/%m/%Y')
        except (TypeError,ValueError):
            return 'Data não informada'

    @staticmethod
    def valid_match_url(value):
        return isinstance(value,str) and value.startswith('https://www.vlr.gg/')

    def action_button(self,parent,text,command,accent=False):
        return tk.Button(parent,text=text,command=command,cursor='hand2',relief='flat',bd=0,
                 bg=C['accent'] if accent else C['panel2'],
                 fg=C['bg'] if accent else C['fg'],
                 activebackground=C['accent_dark'],activeforeground=C['fg'],
                 padx=13,pady=8,font=('Segoe UI',9,'bold'))

    def mini_match(self,parent,m):
        won=m.won==1
        panel=tk.Frame(parent,bg=C['panel'],padx=12,pady=10)
        panel.pack(fill='x',pady=(0,5))
        left=tk.Frame(panel,bg=C['panel']);left.pack(side='left',fill='both',expand=True)
        tk.Label(left,text=f'LOUD  ×  {m.opponent}',bg=C['panel'],fg=C['fg'],
                 font=('Segoe UI',10,'bold'),anchor='w').pack(anchor='w')
        tk.Label(left,text=f'{self.match_date(m.date_utc)}  •  {m.tournament}',
                 bg=C['panel'],fg=C['muted'],font=('Segoe UI',8),anchor='w',
                 wraplength=220,justify='left').pack(anchor='w',pady=(2,0))
        right=tk.Frame(panel,bg=C['panel']);right.pack(side='right',padx=(8,0))
        tk.Label(right,text=f'{fmt(m.team_score)} : {fmt(m.opponent_score)}',
                 bg=C['panel'],fg=C['accent'] if won else C['red'],
                 font=('Segoe UI',14,'bold')).pack(anchor='e')
        tk.Button(right,text='Detalhes  ›',fg=C['muted'],bg=C['panel'],
                  bd=0,relief='flat',cursor='hand2',font=('Segoe UI',8),
                  command=lambda mid=int(m.id):self.open_match_detail(mid)).pack(anchor='e')

    def jogadores(self,players):
        if players.empty:
            self.missing_stats('Estatísticas dos jogadores ainda não salvas',
                'O cache contém resultados de partidas, mas falta baixar o placar individual de cada mapa. '
                'Use Completar estatísticas uma vez. Os dados serão armazenados para as próximas aberturas.')
            return
        summary=self.ana.player_summary(players)
        self.section_label('Jogadores que efetivamente disputaram mapas em 2026').pack(anchor='w')
        self.note('Duplo clique em uma linha para detalhar os mapas. ACS, ADR, KAST e Rating são ponderados por rounds; HS é média por mapa.')
        self.table(self.main,summary,height=17,onselect=lambda tree,cols:self.player_detail(tree,cols,players))

    def player_detail(self,tree,cols,players):
        choice=tree.selection()
        if not choice:return
        r=dict(zip(cols,tree.item(choice[0],'values')))
        try:pid=int(r['ID'])
        except (KeyError,ValueError):return
        info=players[players.player_id==pid].copy()
        window=tk.Toplevel(self);window.title('Jogador | '+r['Jogador'])
        window.geometry('1120x560');window.configure(bg=C['bg'])
        tk.Label(window,text=f"{r['Jogador']} | {len(info)} mapas | {info.match_id.nunique()} partidas",
            bg=C['bg'],fg=C['accent'],font=('Segoe UI',17,'bold')).pack(anchor='w',padx=15,pady=12)
        cols2=['date_utc','tournament','opponent','map_name','agent','kills','deaths',
                'assists','acs','adr','kast','hs','fk','fd','rating','two_k','three_k','four_k','five_k','clutches']
        self.table(window,info[cols2],height=15)

    def comparar(self,players):
        """Seleção por cards clicáveis, sem Ctrl/clique ou lista multi-select.

        O usuário pode escolher dois ou mais atletas e trocar a visualização.
        Os filtros globais continuam sendo respeitados.
        """
        summary=self.ana.player_summary(players)
        extra=self._external_summary()
        if not extra.empty:
            summary=pd.concat([summary,extra.dropna(axis=1,how='all')],ignore_index=True)
        if summary.empty:
            self._compare_source_controls()
            self.missing_stats('Comparação indisponível neste filtro',
                'Não há estatísticas individuais salvas para este período ou filtro.')
            return
        try:
            minimum=max(1,self.minimum.get())
        except tk.TclError:
            minimum=1
        valid=summary[summary['Mapas']>=minimum].reset_index(drop=True)
        if valid.empty:
            self.note('Nenhum jogador atende à quantidade mínima de mapas.')
            return
        info={r['ID']:r for _,r in valid.iterrows()}
        self.compare_selected_ids=[pid for pid in self.compare_selected_ids if pid in info]
        if not self.compare_selected_ids:
            self.compare_selected_ids=list(info)[:2]

        self._compare_source_controls()
        top=tk.Frame(self.main,bg=C['panel'],padx=18,pady=15,
                     highlightbackground=C['line'],highlightthickness=1)
        top.pack(fill='x',pady=(0,12))
        bar=tk.Frame(top,bg=C['panel']);bar.pack(fill='x')
        tk.Label(bar,text='ESCOLHA OS JOGADORES',bg=C['panel'],fg=C['fg'],
                 font=('Segoe UI',12,'bold')).pack(side='left')
        counter=tk.Label(bar,text='',bg=C['panel'],fg=C['accent'],
                         font=('Segoe UI',10,'bold'))
        counter.pack(side='right')
        tk.Label(top,text='Clique nos cards para adicionar ou remover. Você pode comparar 2 ou mais jogadores.',
                 bg=C['panel'],fg=C['muted'],font=('Segoe UI',9)).pack(anchor='w',pady=(5,11))
        tools=tk.Frame(top,bg=C['panel']);tools.pack(fill='x',pady=(0,12))
        tk.Label(tools,text='Buscar',bg=C['panel'],fg=C['muted']).pack(side='left',padx=(0,7))
        search=tk.Entry(tools,textvariable=self.compare_search,
                fg=C['fg'],bg=C['panel2'],insertbackground=C['fg'],
                relief='flat',highlightbackground=C['line'],highlightthickness=1,
                font=('Segoe UI',10),width=22)
        search.pack(side='left',ipady=7,padx=(0,20))
        tk.Label(tools,text='Mínimo de mapas',bg=C['panel'],fg=C['muted']).pack(side='left',padx=(0,7))
        spin=ttk.Spinbox(tools,from_=1,to=999,textvariable=self.minimum,width=5,
                         command=self.render)
        spin.pack(side='left')
        spin.bind('<Return>',lambda _e:self.render())
        spin.bind('<FocusOut>',lambda _e:self.render())
        tk.Button(tools,text='Limpar seleção',relief='flat',bd=0,cursor='hand2',
                  bg=C['panel2'],fg=C['muted'],padx=11,pady=7,
                  command=lambda:(self.compare_selected_ids.clear(),self.render())).pack(side='right')
        # Área de seleção tem altura fixa: muitos atletas não empurram os gráficos
        # para fora da tela em notebooks e monitores menores.
        cards_holder=tk.Frame(top,bg=C['panel']);cards_holder.pack(fill='x')
        cards_canvas=tk.Canvas(cards_holder,bg=C['panel'],bd=0,height=138,
                               highlightthickness=0)
        cards_scroll=ttk.Scrollbar(cards_holder,orient='vertical',command=cards_canvas.yview)
        cards_canvas.configure(yscrollcommand=cards_scroll.set)
        cards_canvas.pack(side='left',fill='x',expand=True)
        cards_scroll.pack(side='right',fill='y')
        cards=tk.Frame(cards_canvas,bg=C['panel'])
        cards_window=cards_canvas.create_window((0,0),window=cards,anchor='nw')
        cards.bind('<Configure>',lambda _e:cards_canvas.configure(scrollregion=cards_canvas.bbox('all')))
        cards_canvas.bind('<Configure>',lambda e:cards_canvas.itemconfigure(cards_window,width=e.width))
        for i in range(3):cards.grid_columnconfigure(i,weight=1,uniform='pick')
        selected_panel=tk.Frame(top,bg=C['panel']);selected_panel.pack(fill='x',pady=(10,0))

        lowerbar=tk.Frame(self.main,bg=C['bg']);lowerbar.pack(fill='x',pady=(0,8))
        tk.Label(lowerbar,text='VISUALIZAÇÃO',fg=C['muted'],bg=C['bg'],
                 font=('Segoe UI',9,'bold')).pack(side='left',padx=(0,10))
        modes=['Radar normalizado','Barras: ACS','Barras: K/D','Evolução ACS',
               'Evolução K/D','Agentes por jogador','Mapas por jogador']
        combo=ttk.Combobox(lowerbar,textvariable=self.compare_mode,values=modes,
                  state='readonly',width=23)
        combo.pack(side='left')
        below=tk.Frame(self.main,bg=C['bg']);below.pack(fill='both',expand=True)
        below.grid_columnconfigure(0,weight=1,uniform='comp')
        below.grid_columnconfigure(1,weight=1,uniform='comp')
        below.grid_rowconfigure(0,weight=1)
        tablebox=tk.Frame(below,bg=C['bg']);tablebox.grid(row=0,column=0,sticky='nsew',padx=(0,8))
        plotbox=tk.Frame(below,bg=C['bg']);plotbox.grid(row=0,column=1,sticky='nsew')

        self._compare_redraw_job=None
        def display():
            self._compare_redraw_job=None
            for w in tablebox.winfo_children():w.destroy()
            for w in plotbox.winfo_children():w.destroy()
            ids=[pid for pid in self.compare_selected_ids if pid in info]
            if len(ids)<2:
                panel=tk.Frame(tablebox,bg=C['panel'],padx=20,pady=24)
                panel.pack(fill='both',expand=True)
                tk.Label(panel,text='Selecione ao menos 2 jogadores',
                    fg=C['fg'],bg=C['panel'],font=('Segoe UI',12,'bold')).pack(anchor='w')
                tk.Label(panel,text='Os resultados aparecerão automaticamente.',
                    fg=C['muted'],bg=C['panel']).pack(anchor='w',pady=(7,0))
                return
            chosen=summary.set_index('ID').loc[ids].reset_index()
            show=chosen.drop(columns=['ID']).set_index('Jogador').transpose().reset_index().rename(columns={'index':'Métrica'})
            self.table(tablebox,show,height=14)
            chart=self.chart_at(plotbox)
            mode=self.compare_mode.get()
            if mode.startswith('Radar'):
                chart.radar(chosen,'Comparação relativa (máx.=100%)')
            elif mode=='Barras: ACS':
                chart.bars(chosen,'Jogador','ACS','ACS por jogador')
            elif mode=='Barras: K/D':
                chart.bars(chosen,'Jogador','K/D','K/D por jogador')
            elif mode.startswith('Evolução'):
                metric='ACS' if 'ACS' in mode else 'K/D'
                evo=self.ana.evolution(players[players.player_id.isin([x for x in ids if isinstance(x,int)])])
                chart.lines(evo,'data',metric,'Jogador',f'Evolução de {metric}')
            elif mode.startswith('Agentes'):
                subset=players[players.player_id.isin([x for x in ids if isinstance(x,int)])]
                chart.heatmap(subset,'nickname','agent','acs','ACS médio por agente')
            else:
                subset=players[players.player_id.isin([x for x in ids if isinstance(x,int)])]
                chart.heatmap(subset,'nickname','map_name','acs','ACS médio por mapa')

        def schedule_display():
            if self._compare_redraw_job is not None:
                self.after_cancel(self._compare_redraw_job)
            self._compare_redraw_job=self.after(120,display)

        def refresh_chips():
            for w in selected_panel.winfo_children():w.destroy()
            counter.configure(text=f'{len(self.compare_selected_ids)} selecionado(s)')
            if not self.compare_selected_ids:
                tk.Label(selected_panel,text='Nenhum jogador escolhido',
                         bg=C['panel'],fg=C['muted']).pack(side='left')
            for pid in self.compare_selected_ids:
                r=info.get(pid)
                if r is None:continue
                tk.Button(selected_panel,text=f"{r['Jogador']}  ×",
                    font=('Segoe UI',9,'bold'),relief='flat',bd=0,
                    bg=C['accent_dark'],fg=C['fg'],padx=10,pady=5,cursor='hand2',
                    command=lambda x=pid:toggle(x)).pack(side='left',padx=(0,7))

        def toggle(pid):
            if pid in self.compare_selected_ids:
                self.compare_selected_ids.remove(pid)
            else:
                self.compare_selected_ids.append(pid)
            refresh_cards()
            refresh_chips()
            schedule_display()

        def refresh_cards(*_):
            for w in cards.winfo_children():w.destroy()
            q=self.compare_search.get().strip().casefold()
            matches=[(pid,r) for pid,r in info.items() if q in str(r['Jogador']).casefold()]
            for index,(pid,r) in enumerate(matches):
                active=pid in self.compare_selected_ids
                acs=fmt(r.get('ACS'))
                text=f"{'✓  ' if active else '+  '}{r['Jogador']}\n{int(r['Mapas'])} mapas   ·   ACS {acs}"
                btn=tk.Button(cards,text=text,justify='left',anchor='w',cursor='hand2',
                    font=('Segoe UI',10,'bold'),bd=0,relief='flat',
                    bg=C['accent_dark'] if active else C['panel2'],
                    fg=C['fg'],activebackground=C['accent_dark'],activeforeground=C['fg'],
                    padx=14,pady=11,command=lambda x=pid:toggle(x))
                btn.grid(row=index//3,column=index%3,sticky='ew',padx=4,pady=4)
                btn.bind('<MouseWheel>',lambda e:cards_canvas.yview_scroll(-int(e.delta/120),'units'))
            cards_canvas.yview_moveto(0)
            if not matches:
                tk.Label(cards,text='Nenhum jogador encontrado',bg=C['panel'],
                         fg=C['muted']).grid(row=0,column=0,sticky='w',pady=14)

        # Tk variable trace removed when page is destroyed via callback cleanup,
        # avoiding stale callbacks when navigating between pages.
        trace_id=self.compare_search.trace_add('write',refresh_cards)
        def remove_trace(_e=None):
            try:self.compare_search.trace_remove('write',trace_id)
            except (tk.TclError,ValueError):pass
        top.bind('<Destroy>',lambda event:remove_trace() if event.widget is top else None)
        combo.bind('<<ComboboxSelected>>',lambda _e:schedule_display())
        refresh_cards();refresh_chips();schedule_display()

    def partidas(self,matches):
        self.section_label('Histórico de partidas da LOUD').pack(anchor='w')
        self.note('Duplo clique para ver mapas e estatísticas. Partidas futuras aparecem separadas, sem placares.')
        table=matches.rename(columns={'date_utc':'Data UTC','tournament':'Campeonato',
              'opponent':'Adversário','team_score':'LOUD','opponent_score':'Oponente',
              'won':'Vitória','status':'Status','url':'Link','id':'ID'})
        cols=['ID','Data UTC','Campeonato','Adversário','LOUD','Oponente','Vitória','Status','Link']
        self.table(self.main,table[cols],height=20,onselect=self.match_detail)

    def match_detail(self,tree,cols):
        selected=tree.selection()
        if not selected:return
        r=dict(zip(cols,tree.item(selected[0],'values')))
        try:mid=int(r['ID'])
        except (KeyError,ValueError):return
        self.open_match_detail(mid)

    def open_match_detail(self,mid):
        """Exibe detalhes da série tanto pela tabela quanto pelo Dashboard."""
        with self.db.connect() as con:
            match=con.execute('SELECT * FROM matches WHERE id=?',(mid,)).fetchone()
            maps=[dict(r) for r in con.execute(
                'SELECT * FROM match_maps WHERE match_id=? ORDER BY map_index',(mid,))]
            players=[dict(r) for r in con.execute(
                 'SELECT s.*,p.nickname FROM player_map_stats s '
                 'JOIN players p ON p.id=s.player_id WHERE s.match_id=? '
                 'ORDER BY s.map_index,s.acs DESC',(mid,))]
        if match is None:
            messagebox.showinfo('Partida','Essa partida não está mais no banco local.');return
        m=dict(match)
        win=tk.Toplevel(self);win.title(f'Partida {mid} | LOUD Analytics')
        win.geometry('1200x750');win.configure(bg=C['bg'])
        tk.Label(win,text=f"LOUD vs {m['opponent']}  |  {m['tournament']}",
            bg=C['bg'],fg=C['accent'],font=('Segoe UI',18,'bold')).pack(anchor='w',padx=15,pady=12)
        if maps:
            tk.Label(win,text='Mapas jogados',fg=C['fg'],bg=C['bg']).pack(anchor='w',padx=15)
            self.table(win,pd.DataFrame(maps)[['map_name','loud_rounds','opponent_rounds',
                      'attack_rounds','defense_rounds']],height=5)
        if players:
            tk.Label(win,text='Jogadores / estatísticas por mapa',fg=C['fg'],bg=C['bg']).pack(anchor='w',padx=15)
            self.table(win,pd.DataFrame(players)[['map_index','nickname','agent','kills',
                'deaths','assists','acs','adr','kast','hs','rating','fk','fd','clutches']],height=13)
        if not maps:self.note('Detalhes indisponíveis; a partida ainda não foi enriquecida.',win)
        if self.valid_match_url(m.get('url')):
            ttk.Button(win,text='Abrir partida original no VLR.gg',
                command=lambda:webbrowser.open(m['url'])).pack(padx=20,pady=12,anchor='w')

    def mapas(self,maps,players):
        if maps.empty:
            self.missing_stats('Mapa e placares ainda não disponíveis',
                'A lista de confrontos está salva, mas falta consultar o placar por mapa. '
                'Você pode completar os detalhes sem baixar novamente a lista de partidas.')
            return
        self.section_label('MAPAS  /  ANÁLISE E VETOS').pack(anchor='w',pady=(0,8))
        tabs=ttk.Notebook(self.main)
        tabs.pack(fill='both',expand=True)
        results=tk.Frame(tabs,bg=C['bg']);vetos=tk.Frame(tabs,bg=C['bg'])
        tabs.add(results,text='Desempenho por mapa')
        tabs.add(vetos,text='Bans e picks')
        self.table(results,self.ana.maps_summary(maps),height=12)
        vetoes=self.db.veto_frame()
        if vetoes.empty:
            tk.Label(vetos,text='Ainda não existem vetos salvos. Use Completar estatísticas.',
                    fg=C['muted'],bg=C['bg'],pady=24).pack(anchor='w')
        else:
            ids=set(maps.match_id)
            vetoes=vetoes[vetoes.match_id.isin(ids)]
            self.table(vetos,veto_summary(vetoes),height=12)
            self.note('Bans/picks identificados na sequência de veto oficial de cada série, não inferidos.',vetos)

    def agentes(self,players):
        self.section_label('AGENTES  /  FUNÇÕES E COMPOSIÇÕES').pack(anchor='w',pady=(0,7))
        tabs=ttk.Notebook(self.main)
        tabs.pack(fill='both',expand=True)
        stats=tk.Frame(tabs,bg=C['bg']);comps_panel=tk.Frame(tabs,bg=C['bg'])
        tabs.add(stats,text='Estatísticas por função')
        tabs.add(comps_panel,text='Composições por mapa')
        filterrow=tk.Frame(stats,bg=C['panel'],padx=13,pady=10)
        filterrow.pack(fill='x',pady=(0,8))
        tk.Label(filterrow,text='FUNÇÃO',fg=C['muted'],bg=C['panel']).pack(side='left',padx=(0,12))
        role_cb=ttk.Combobox(filterrow,textvariable=self.role_filter,state='readonly',width=22,
            values=['Todas as funções']+list(ROLES)+['Não classificado'])
        role_cb.pack(side='left')
        role_cb.bind('<<ComboboxSelected>>',lambda _e:self.render())
        if players.empty or players.agent.dropna().empty:
            tk.Label(stats,text='Estatísticas individuais ausentes; use Completar estatísticas.',
                     bg=C['bg'],fg=C['muted']).pack(anchor='w',pady=12)
        else:
            summary=self.ana.agents_summary(players)
            summary.insert(1,'Função',summary['Agente'].map(role_of))
            role=self.role_filter.get()
            if role!='Todas as funções':summary=summary[summary['Função']==role]
            self.table(stats,summary,height=13)
        comps=self.db.team_compositions()
        if comps.empty:
            comps=compositions(players,self.ana.maps())
        if comps.empty:
            tk.Label(comps_panel,text='Composições indisponíveis. Use Atualizar dados para consultar a fonte.',
                     bg=C['bg'],fg=C['muted']).pack(anchor='w',pady=12)
        else:
            self.table(comps_panel,comps,height=14)
            self.note('Composições identificadas por cinco agentes do mesmo mapa ou por estatísticas de equipe da fonte.',comps_panel)

    def campeonatos(self,matches):
        self.section_label('Resultados por campeonato').pack(anchor='w')
        table=self.ana.tournament_summary(matches)
        self.table(self.main,table,height=12)
        c=self.chart_at(self.main);c.bars(table,'Campeonato','WR %','Win rate em cada campeonato')

    def evolucao(self,players):
        if players.empty:
            self.missing_stats('Evolução ainda não disponível',
                'É necessário salvar estatísticas de jogos individuais para calcular a evolução durante 2026.')
            return
        self.section_label('Evolução individual durante a temporada').pack(anchor='w')
        mode=tk.StringVar(value='ACS')
        combo=ttk.Combobox(self.main,textvariable=mode,values=['ACS','K/D'],state='readonly',width=20)
        combo.pack(anchor='w',pady=8)
        c=self.chart_at(self.main)
        def plot(*_):
            evo=self.ana.evolution(players)
            c.lines(evo,'data',mode.get(),'Jogador','Evolução '+mode.get())
        combo.bind('<<ComboboxSelected>>',plot);plot()
        self.note('Cada ponto representa o desempenho diário do jogador nos mapas registrados (não extrapolado).')

    def _external_summary(self):
        columns=self.ana.player_summary(pd.DataFrame()).columns
        df=self.external_pool
        if df.empty:return pd.DataFrame(columns=columns)
        rows=[]
        for _,r in df.iterrows():
            if pd.isna(r['maps']) or r['maps']<1:continue
            key=f"ext:{self.external_year}:{self.external_agent}:{r['player']}:{r['team']}"
            row={c:float('nan') for c in columns}
            row.update({'Jogador':f"{r['player']} · {r['team']} ({self.external_year}/{self.external_agent})",
                        'ID':key,'Mapas':r['maps'],'Rounds':r['rounds'],
                        'Kills':r['kills'],'Deaths':r['deaths'],'Assists':r['assists'],
                        'K/D':r['kd'],'ACS':r['acs'],'ADR':r['adr'],'KAST %':r['kast'],
                        'Rating VLR':r['rating'],'HS %':r['hs'],'FK':r['fk'],'FD':r['fd'],
                        'Clutches':r['clutches'],'Agente mais usado':self.external_agent})
            if pd.notna(r['deaths']) and r['deaths']>0 and pd.notna(r['kills']) and pd.notna(r['assists']):
                row['KDA']=(r['kills']+r['assists'])/r['deaths']
            rows.append(row)
        return pd.DataFrame(rows,columns=columns)

    def _compare_source_controls(self):
        wrap=tk.Frame(self.main,bg=C['panel'],padx=14,pady=10,
                      highlightbackground=C['line'],highlightthickness=1)
        wrap.pack(fill='x',pady=(0,10))
        tk.Label(wrap,text='COMPARAR COM JOGADORES DE OUTROS TIMES / ANOS',
                bg=C['panel'],fg=C['accent'],font=('Segoe UI',10,'bold')).pack(anchor='w',pady=(0,8))
        row=tk.Frame(wrap,bg=C['panel']);row.pack(fill='x')
        tk.Label(row,text='Champions',bg=C['panel'],fg=C['muted']).pack(side='left')
        ttk.Combobox(row,textvariable=self.compare_year,state='readonly',width=7,
                     values=[str(y) for y in EVENTS]).pack(side='left',padx=(5,12))
        tk.Label(row,text='Agente',bg=C['panel'],fg=C['muted']).pack(side='left')
        names=sorted(set(x for group in ROLES.values() for x in group))
        ttk.Combobox(row,textvariable=self.compare_agent,state='readonly',width=14,
                     values=['Todos']+names).pack(side='left',padx=(5,12))
        self.action_button(row,'Carregar atletas',lambda:self._load_champions(
            int(self.compare_year.get()),self.compare_agent.get(),'compare'),True).pack(side='left')
        if self.external_loading:
            tk.Label(row,text='Coletando dados…',bg=C['panel'],fg=C['muted']).pack(side='left',padx=10)
        else:
            tk.Label(row,text=f'{len(self.external_pool)} atletas externos carregados',
                     bg=C['panel'],fg=C['muted']).pack(side='left',padx=10)
        tk.Label(wrap,text='Use o filtro global Agente = Chamber para o jogador LOUD; selecione 2022 / Chamber para yay. '
                         'Esses recortes são de períodos diferentes e a comparação deve considerar o número de rounds.',
                bg=C['panel'],fg=C['muted'],wraplength=950,justify='left').pack(anchor='w',pady=(7,0))

    def _load_champions(self,year,agent='Todos',target='world',force=False):
        if (target=='world' and self.world_loading) or (target=='compare' and self.external_loading):return
        event=EVENTS[year]
        def apply():
            if target=='world':self.world_loading=False
            else:
                self.external_loading=False
                self.external_year=year;self.external_agent=agent
                self.external_pool=self.db.get_champions(event,agent)
                self.compare_selected_ids=[x for x in self.compare_selected_ids if isinstance(x,int)]
            self.render()
        if self.db.champions_cached(event,agent) and not force:
            apply();return
        if target=='world':self.world_loading=True
        else:self.external_loading=True
        self.render()
        def worker():
            try:
                rows,url=collect_leaderboard(year,agent)
                self.db.save_champions(event,year,agent,rows,url)
                self.q.put(('champions_done',(target,year,agent,None)))
            except Exception as exc:
                LOGGER.exception('Falha ao coletar ranking Champions %s/%s',year,agent)
                self.q.put(('champions_done',(target,year,agent,str(exc))))
        threading.Thread(target=worker,daemon=True,name='ChampionsLeaderboard').start()

    def champions_page(self):
        self.section_label('VALORANT CHAMPIONS TOUR  /  MUNDIAIS').pack(anchor='w')
        self.note('Champions 2021–2026 • Dados consultados sob demanda e salvos por edição. '
                  'Consulte rankings e desempenho round a round nas abas abaixo.')
        bar=tk.Frame(self.main,bg=C['panel'],padx=12,pady=12,
                     highlightbackground=C['line'],highlightthickness=1)
        bar.pack(fill='x',pady=(4,11))
        tk.Label(bar,text='EDIÇÃO',fg=C['muted'],bg=C['panel']).pack(side='left')
        year=ttk.Combobox(bar,textvariable=self.world_year,state='readonly',width=8,
                          values=[str(y) for y in EVENTS]);year.pack(side='left',padx=(9,20))
        year.bind('<<ComboboxSelected>>',lambda _e:self.render())
        tk.Label(bar,text='RANKING',fg=C['muted'],bg=C['panel']).pack(side='left')
        metrics=['Kills','Assists','Clutches','K/D','KDA','Rating','ACS','FK']
        cb=ttk.Combobox(bar,textvariable=self.world_metric,state='readonly',width=15,values=metrics)
        cb.pack(side='left',padx=(9,16));cb.bind('<<ComboboxSelected>>',lambda _e:self.render())
        self.action_button(bar,'Carregar ranking',lambda:self._load_champions(
            int(self.world_year.get())) ,True).pack(side='left',padx=(0,7))
        self.action_button(bar,'Recarregar',lambda:self._load_champions(
            int(self.world_year.get()),force=True)).pack(side='left')
        yearnum=int(self.world_year.get());event=EVENTS[yearnum]
        pages=ttk.Notebook(self.main)
        pages.pack(fill='both',expand=True)
        rank_page=tk.Frame(pages,bg=C['bg']);deep_page=tk.Frame(pages,bg=C['bg'])
        pages.add(rank_page,text='Ranking geral da edição')
        pages.add(deep_page,text='Times, lados e pistol')
        pages.select(self.world_tab)
        pages.bind('<<NotebookTabChanged>>',lambda _e:setattr(self,'world_tab',pages.index(pages.select())))
        df=self.db.get_champions(event)
        if df.empty:
            self.note('Nenhum ranking armazenado para esta edição. Clique em Carregar ranking. '
                      'O histórico geral de rounds pode ser baixado independentemente na segunda aba.',rank_page)
        else:
            status=tk.Frame(rank_page,bg=C['panel'],padx=13,pady=10)
            status.pack(fill='x',pady=7)
            tk.Label(status,text=f'{yearnum}  •  {len(df)} atletas  •  {df.team.nunique()} equipes  •  '
                     f'{fmt(df.maps.max())} mapas (maior amostra)',bg=C['panel'],fg=C['accent'],
                     font=('Segoe UI',10,'bold')).pack(anchor='w')
            if self.world_metric.get()=='KDA':
                df=df.copy()
                df['kda']=(df.kills+df.assists)/df.deaths.replace(0,float('nan'))
            key={'Kills':'kills','Assists':'assists','Clutches':'clutches','K/D':'kd','KDA':'kda',
                 'Rating':'rating','ACS':'acs','FK':'fk'}[self.world_metric.get()]
            table=df.dropna(subset=[key]).sort_values(key,ascending=False).reset_index(drop=True)
            table.insert(0,'Posição',range(1,len(table)+1))
            chosen=table[(table.Posição<=10)|(table.team.str.upper()=='LOUD')].copy()
            chosen=chosen.rename(columns={'player':'Jogador','team':'Time','maps':'Mapas',
                'rounds':'Rounds','kills':'Kills','deaths':'Deaths','assists':'Assists',
                'clutches':'Clutches','fk':'FK','kd':'K/D','kda':'KDA','acs':'ACS','rating':'Rating'})
            self.section_label('TOP 10 + POSIÇÕES DA LOUD',rank_page).pack(anchor='w',pady=(10,5))
            self.table(rank_page,chosen[['Posição','Jogador','Time','Mapas','Rounds',
                       {'kills':'Kills','assists':'Assists','clutches':'Clutches','kd':'K/D','kda':'KDA',
                        'rating':'Rating','acs':'ACS','fk':'FK'}[key]]],height=15)
            self.note('Valores agregados do campeonato; a classificação depende da cobertura da fonte. '
                      'As estatísticas por lado e por round ficam na segunda aba.',rank_page)
            self.action_button(rank_page,'Ver tabela original',
                lambda:webbrowser.open(event_url(yearnum))).pack(anchor='w',pady=5)
        if self.world_loading:self.note('Coletando dados…',rank_page)
        self._world_detailed_panel(yearnum,deep_page)


    def _load_world_details(self,year):
        if self.deep_loading:return
        self.deep_loading=True
        self.deep_status='Coletando dados do campeonato escolhido no terminal; apenas séries ainda não salvas.'
        self.render()
        def worker():
            try:
                from api.world_deep import fetch_world_series
                result=fetch_world_series(self.db,year,
                        on_progress=lambda msg:self.q.put(('world_stage',msg)))
                self.q.put(('world_done',(year,result,None)))
            except Exception as exc:
                LOGGER.exception('Erro na coleta avançada do Champions %s',year)
                self.q.put(('world_done',(year,None,str(exc))))
        threading.Thread(target=worker,daemon=True,name='WorldDeep').start()

    def _world_detailed_panel(self,year,parent=None):
        host=parent or self.main
        event=EVENTS[year]
        bar=tk.Frame(host,bg=C['bg']);bar.pack(fill='x',pady=(8,3))
        self.action_button(bar,'Coletar estatísticas completas (por demanda)',
            lambda:self._load_world_details(year),True).pack(side='left',padx=(0,8))
        if self.deep_loading:
            tk.Label(bar,text=self.deep_status,bg=C['bg'],fg=C['muted'],
                     wraplength=600).pack(side='left')
        teams,players,rounds,agents=self.db.world_frames(event)
        if teams.empty:
            self.note('Para ver agentes mais usados, lados ataque/defesa, times, pistol e 2º round, '
                      'clique em Coletar estatísticas completas. A coleta percorre TODAS as partidas '
                      'desta edição e pode ser demorada; os resultados ficam salvos e retomam de onde pararam.',host)
            return
        self.section_label(f'ANÁLISE APROFUNDADA  /  {len(teams)//2} MAPAS PROCESSADOS',host).pack(anchor='w',pady=(8,6))
        tabs=ttk.Notebook(host)
        tabs.pack(fill='both',expand=True,pady=(0,4))
        page_names=['Top 5 agentes','Times e rounds','Pistol / 2º round','Jogadores no ataque','Jogadores na defesa']
        frames={n:tk.Frame(tabs,bg=C['bg']) for n in page_names}
        for name,pane in frames.items():tabs.add(pane,text=name)
        tabs.select(min(self.world_details_tab,len(page_names)-1))
        tabs.bind('<<NotebookTabChanged>>',lambda _e:setattr(self,'world_details_tab',tabs.index(tabs.select())))
        self.table(frames['Top 5 agentes'],agent_top(agents))
        self.table(frames['Times e rounds'],teams_summary(teams))
        self.table(frames['Pistol / 2º round'],pistol_summary(teams,rounds))
        for name,side in [('Jogadores no ataque','Ataque'),('Jogadores na defesa','Defesa')]:
            frame=frames[name]
            bar=tk.Frame(frame,bg=C['bg']);bar.pack(fill='x',pady=7)
            tk.Label(bar,text='TOP 10 + ATLETAS LOUD  ·  ORDENAR POR',
                     bg=C['bg'],fg=C['muted']).pack(side='left',padx=(0,10))
            chosen_metric=tk.StringVar(value='ACS')
            choice=ttk.Combobox(bar,textvariable=chosen_metric,state='readonly',width=14,
                                values=['ACS','First Kills'])
            choice.pack(side='left')
            tablebox=tk.Frame(frame,bg=C['bg']);tablebox.pack(fill='both',expand=True)
            def draw(_e=None,frame_box=tablebox,sv=chosen_metric,which=side):
                for child in frame_box.winfo_children():child.destroy()
                stats=side_rankings(players,which,sv.get())
                if not stats.empty:stats=stats[(stats.Posição<=10)|(stats.Equipe.str.upper()=='LOUD')]
                self.table(frame_box,stats)
            choice.bind('<<ComboboxSelected>>',draw)
            draw()
        self.note('Os rankings são parciais enquanto existirem séries pendentes. Pistols: rounds 1 e 13; '
                  '2º round: rounds 2 e 14. Dados ausentes são apresentados como N/D.',host)

    def recordes_page(self,players):
        self.section_label('RECORDES  /  TEMPORADA E HISTÓRICO').pack(anchor='w')
        self.note('Destaques entre partidas e edições armazenadas, não recordes mundiais absolutos.')
        tabs=ttk.Notebook(self.main)
        tabs.pack(fill='both',expand=True,pady=(8,4))
        local=tk.Frame(tabs,bg=C['bg']);world=tk.Frame(tabs,bg=C['bg'])
        ages=tk.Frame(tabs,bg=C['bg'])
        tabs.add(local,text='LOUD · 2026')
        tabs.add(world,text='Champions · 2021–2026')
        tabs.add(ages,text='Idades verificadas')
        self.section_label('Destaques individuais da LOUD',local).pack(anchor='w',pady=(9,4))
        self.table(local,local_records(self.ana.player_summary(players)),height=16)
        self.section_label('Recordes por edição já salva',world).pack(anchor='w',pady=(9,4))
        ranking=[]
        for year,event in EVENTS.items():
            d=self.db.get_champions(event)
            if d.empty:continue
            for metric,label in [('kills','Kills'),('assists','Assists'),('clutches','Clutches'),
                                 ('fk','First kills'),('acs','ACS')]:
                ok=d.dropna(subset=[metric])
                if ok.empty:continue
                m=ok.sort_values(metric,ascending=False).iloc[0]
                ranking.append({'Ano':year,'Destaque':label,'Jogador':m.player,
                                'Equipe':m.team,'Valor':m[metric]})
        self.table(world,pd.DataFrame(ranking),height=16)
        self.section_label('Mais jovem e mais velho por edição',ages).pack(anchor='w',pady=(9,4))
        ages_data=verified_champions_ages()
        self.table(ages,ages_data.drop(columns=['Fonte']),height=12)
        self.note('Idade em anos completos no início de cada campeonato, conforme Liquipedia. '
                  'Cobertura confirmada para 2021–2023; 2024–2026: N/D. '
                  'O painel não afirma ser um ranking completo de todos os jogadores.',ages)
        self.action_button(ages,'Conferir fonte (2022)',lambda:webbrowser.open(
            ages_data[ages_data.Ano==2022].iloc[0]['Fonte'])).pack(anchor='w',pady=10)


    def load_local_snapshot(self):
        """Pandas e SQLite fora do Tk. O terminal mostra cada fase e duração."""
        self._snapshot_generation += 1
        generation = self._snapshot_generation
        self._local_load_started = time.monotonic()
        LOGGER.info('CACHE: iniciar leitura local, geração=%s', generation)

        def worker():
            try:
                reader = Analytics(self.db)
                with timed('CACHE: ler partidas do SQLite'):
                    matches = reader.matches()
                with timed('CACHE: ler mapas do SQLite'):
                    maps = reader.maps()
                with timed('CACHE: ler estatísticas individuais do SQLite'):
                    players = reader.players()
                self.q.put(('local', (generation, dict(
                    matches=matches, maps=maps, players=players), None)))
                LOGGER.info('CACHE: carregado | partidas=%d | mapas=%d | estatísticas=%d',
                            len(matches), len(maps), len(players))
            except Exception as exc:
                LOGGER.exception('CACHE: leitura local falhou')
                self.q.put(('local', (generation, None, str(exc))))
        threading.Thread(target=worker, daemon=True,
                         name='LoudCacheWorker').start()

    def startup_sync(self, manual=False, details_only=False):
        """Acesso online APENAS no primeiro uso sem cache ou por ação voluntária.

        Nenhuma rotina de atualização periódica é criada. A thread da API nunca
        manipula widgets: entrega mensagens ao Tk pela fila.
        """
        if self.updating:
            LOGGER.info('COLETA: já em execução; solicitação adicional ignorada')
            return
        if not manual:
            if self._startup_sync_started or self._has_cached_matches:
                LOGGER.info('CACHE: abertura com dados locais; nenhuma chamada HTTP')
                return
        self._startup_sync_started = True
        self.updating = True
        self.sync_error = None
        self._sync_started = time.monotonic()
        self.refresh_button.config(state='disabled')
        self.complete_button.config(state='disabled')
        LOGGER.info('COLETA: %s', 'preenchimento de estatísticas locais' if details_only else
                    'atualização manual' if manual else 'primeira execução sem cache')

        def worker():
            try:
                result = self.engine.update(
                    # No primeiro uso: lista recente e até uma série.
                    # Manualmente: histórico completo, até 5 séries pendentes.
                    auto=not manual,
                    limit=None if details_only else (5 if manual else None),
                    details_only=details_only,
                    callback=lambda message,*_:self.q.put(('progress', message)),
                    on_data=lambda phase:self.q.put(('partial', phase)))
                self.q.put(('done', result))
            except Exception as exc:
                LOGGER.exception('COLETA: falha inesperada: %s', exc)
                self.q.put(('done', dict(changed=False, errors=1,
                                         message=f'{type(exc).__name__}: {exc}')))
        threading.Thread(target=worker, daemon=True,
                         name='LoudDataWorker').start()

    def _watch_cache(self):
        if not self.ready and self._local_load_started:
            duration = time.monotonic() - self._local_load_started
            if duration >= 7:
                LOGGER.warning('CACHE: leitura está demorando %.0fs; verificar SQLite/disco.', duration)
                self.local_error = 'Leitura do cache local está demorando; veja as etapas no terminal.'
                self.ready = True
                self.render()

    def _watch_sync(self):
        if self.updating and self._sync_started:
            duration = time.monotonic() - self._sync_started
            LOGGER.warning('ONLINE: ainda em andamento após %.0fs; etapa: %s. Veja as chamadas API no terminal.',
                           duration, self._last_sync_stage)
            # Apenas diagnóstico em terminal. Nenhum indicador permanente na GUI.
            self.after(20000, self._watch_sync)

    def _partial_reload(self):
        self._partial_reload_job = None
        self.load_local_snapshot()

    def poll(self):
        if self._closing:
            return
        try:
            # Limite por ciclo evita que uma fila grande bloqueie o Tk.
            for _ in range(40):
                try:
                    kind,item = self.q.get_nowait()
                except queue.Empty:
                    break
                if kind == 'local':
                    generation,snapshot,error = item
                    if generation != self._snapshot_generation:
                        continue
                    if snapshot is not None:
                        self.ana._snapshot = snapshot
                        self.local_error = None
                        self.ready = True
                        self._has_cached_matches = not snapshot['matches'].empty
                        self.refresh_filters()
                        self.update_coverage()
                        self.render()
                        if not self._has_cached_matches and not self._startup_sync_started:
                            if self.db.can_retry_empty_cache():
                                LOGGER.info('CACHE: nenhuma partida de 2026 salva; coletar uma vez')
                                self.after(50, self.startup_sync)
                            else:
                                LOGGER.warning('CACHE: tentativa anterior falhou recentemente; '
                                               'sem repetição automática nesta abertura')
                                self.sync_error = ('A última coleta falhou recentemente. '
                                                   'Clique em Atualizar dados para tentar novamente.')
                                self.render()
                        elif self._has_cached_matches:
                            LOGGER.info('CACHE: partidas carregadas, início SEM consultas de rede')
                    elif error:
                        self.local_error = error
                        self.ready = True
                        self.render()
                elif kind == 'world_stage':
                    self.deep_status=str(item)
                    LOGGER.info('%s',item)
                elif kind == 'world_done':
                    year,result,error=item
                    self.deep_loading=False
                    if error:
                        self.deep_status='Falha na coleta: '+error
                        messagebox.showerror('Erro na coleta',error)
                    else:
                        self.deep_status=f"Coleta: {result['saved']} séries salvas, {result['skipped']} já armazenadas, {result['errors']} falhas."
                    if int(self.world_year.get())==year:self.render()
                elif kind == 'champions_done':
                    target,year,agent,error=item
                    self.world_loading=False if target=='world' else self.world_loading
                    self.external_loading=False if target=='compare' else self.external_loading
                    if error:
                        LOGGER.error('Não foi possível carregar Champions %s: %s',year,error)
                        messagebox.showerror('Falha na coleta do Champions',str(error))
                    elif target=='compare':
                        self.external_year=year;self.external_agent=agent
                        self.external_pool=self.db.get_champions(EVENTS[year],agent)
                        self.compare_selected_ids=[x for x in self.compare_selected_ids if isinstance(x,int)]
                    self.render()
                elif kind == 'progress':
                    self._last_sync_stage = str(item)
                elif kind == 'partial':
                    # Atualizar progressivamente sem reconstruir o dashboard a cada mapa.
                    # Uma única leitura a cada ~1.5s protege a fluidez do Tkinter.
                    if self._partial_reload_job is None:
                        self._partial_reload_job = self.after(1500, self._partial_reload)
                elif kind == 'done':
                    self.updating = False
                    self.refresh_button.config(state='normal')
                    self.complete_button.config(state='normal')
                    self.update_coverage()
                    self.sync_error = item.get('message') if item.get('errors') else None
                    LOGGER.info('ONLINE: terminou em %.1fs, alterações=%s, erros=%s',
                                time.monotonic()-self._sync_started,
                                item.get('changed'), item.get('errors'))
                    # Se já houver leitura agendada, ela inclui o resultado final.
                    if self._partial_reload_job is not None:
                        self.after_cancel(self._partial_reload_job)
                        self._partial_reload_job = None
                        self.load_local_snapshot()
                    elif item.get('changed'):
                        self.load_local_snapshot()
                    elif self.sync_error and self.ready and not self.ana.matches().shape[0]:
                        self.render()
        except Exception:
            LOGGER.exception('ERRO no processamento da fila do Tkinter')
        finally:
            try:
                if not self._closing:
                    self.after(120, self.poll)
            except tk.TclError:
                return
