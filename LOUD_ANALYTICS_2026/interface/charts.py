"""Gráficos do Matplotlib incorporados em quadros Tkinter."""
import numpy as np
import pandas as pd
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from config import COLORS as C

class ChartPanel:
    def __init__(self,parent):
        self.figure=Figure(figsize=(8,3.6),dpi=100,facecolor=C['panel'])
        self.canvas=FigureCanvasTkAgg(self.figure,master=parent)
        self.canvas.get_tk_widget().pack(fill='both',expand=True)
        self.figure.tight_layout(pad=2)

    def ax(self,title=''):
        self.figure.clear()
        ax=self.figure.add_subplot(111,facecolor=C['panel'])
        ax.set_title(title,loc='left',color=C['fg'],fontsize=12,fontweight='bold',pad=12)
        ax.tick_params(colors=C['muted'],labelsize=9)
        for spine in ax.spines.values():
            spine.set_color(C['line'])
        ax.grid(axis='y',alpha=.16,color=C['muted'])
        ax.set_axisbelow(True)
        return ax

    def render(self):
        self.figure.tight_layout(pad=2)
        self.canvas.draw_idle()

    def message(self,title,text):
        a=self.ax(title);a.text(.5,.5,text,ha='center',va='center',color=C['muted'],transform=a.transAxes)
        a.set_xticks([]);a.set_yticks([]);self.render()

    def bars(self,df,x,y,title,limit=16):
        if df.empty or not {x,y}.issubset(df.columns):
            return self.message(title,'Dados indisponíveis para este filtro')
        d=df[[x,y]].dropna().head(limit)
        if d.empty:
            return self.message(title,'Métricas indisponíveis (N/D)')
        a=self.ax(title)
        labels=d[x].astype(str).to_list()
        a.bar(range(len(d)),d[y],color=C['accent'],alpha=.85,width=.65)
        a.set_xticks(range(len(d)),labels,rotation=30,ha='right')
        self.render()

    def lines(self,df,x,y,category,title):
        if df.empty or not {x,y,category}.issubset(df.columns):
            return self.message(title,'Não existem séries temporais disponíveis')
        if not df[y].notna().any():
            return self.message(title,'Séries temporais ainda sem valores conhecidos')
        a=self.ax(title)
        for i,(name,g) in enumerate(df.groupby(category)):
            if g[y].notna().sum()<1:
                continue
            a.plot(g[x].astype(str),g[y],label=str(name),marker='o',markersize=3,
                   color=[C['accent'],C['fg'],C['gold'],C['muted'],C['red']][i%5])
        if len(df[x].unique())>8:
            a.xaxis.set_major_locator(__import__('matplotlib').ticker.MaxNLocator(8))
        a.tick_params(axis='x',rotation=30)
        a.legend(facecolor=C['panel'],labelcolor=C['fg'],fontsize=8,loc='best')
        self.render()

    def radar(self,df,title):
        metrics=['ACS','ADR','KAST %','K/D','HS %']
        if df.empty or len(df)<2:
            return self.message(title,'Selecione ao menos dois jogadores')
        self.figure.clear()
        a=self.figure.add_subplot(111,polar=True,facecolor=C['panel'])
        values=df[metrics].apply(pd.to_numeric,errors='coerce')
        # Não apresentar dados ausentes como zero nas comparações.
        if values.isna().any().any():
            return self.message(title,'Radar precisa de todas as cinco métricas. Use Barras ou a tabela.')
        maxes=values.max(axis=0).replace(0,np.nan)
        if maxes.isna().any():
            return self.message(title,'Não há dados suficientes para normalizar as métricas')
        norm=values.divide(maxes).clip(0,1)
        angles=np.linspace(0,2*np.pi,len(metrics),endpoint=False).tolist()
        for i,(_,row) in enumerate(norm.iterrows()):
            vals=row.to_list()+[row.iloc[0]]
            ang=angles+[angles[0]]
            col=[C['accent'],C['gold'],C['red'],C['fg'],C['muted']][i%5]
            a.plot(ang,vals,color=col,lw=2,label=str(df.iloc[i]['Jogador']))
            a.fill(ang,vals,color=col,alpha=.08)
        a.set_xticks(angles,metrics,color=C['fg'])
        a.set_yticks([.25,.5,.75,1.0],['25%','50%','75%','100%'],color=C['muted'])
        a.grid(color=C['line'])
        a.spines['polar'].set_color(C['line'])
        a.set_ylim(0,1)
        a.legend(loc='upper right',bbox_to_anchor=(1.38,1.14),labelcolor=C['fg'],facecolor=C['panel'])
        self.render()

    def heatmap(self,df,row,col,value,title):
        if df.empty or not {row,col,value}.issubset(df.columns):
            return self.message(title,'Sem dados suficientes')
        subset=df[[row,col,value]].dropna(subset=[row,col,value]).copy()
        subset[value]=pd.to_numeric(subset[value],errors='coerce')
        subset=subset.dropna(subset=[value])
        if subset.empty:
            return self.message(title,'Estatísticas ainda não disponíveis no cache')
        matrix=subset.pivot_table(index=row,columns=col,values=value,aggfunc='mean')
        if matrix.empty:
            return self.message(title,'Sem valores conhecidos')
        a=self.ax(title)
        data=np.ma.masked_invalid(matrix.to_numpy(dtype=float))
        a.imshow(data,aspect='auto',cmap='YlGn')
        a.set_xticks(range(len(matrix.columns)),matrix.columns,rotation=30,ha='right')
        a.set_yticks(range(len(matrix.index)),matrix.index)
        a.grid(False)
        for (i,j),v in np.ndenumerate(matrix.to_numpy(dtype=float)):
            if np.isfinite(v):
                a.text(j,i,f'{v:.0f}',ha='center',va='center',fontsize=8,color='#111a13')
        self.render()
