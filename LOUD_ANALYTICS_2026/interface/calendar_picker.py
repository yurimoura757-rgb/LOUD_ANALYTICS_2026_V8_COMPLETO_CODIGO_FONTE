"""Calendário de cliques com Tkinter puro, sem dependências externas."""
import calendar
from datetime import date
import tkinter as tk
from config import COLORS as C
from core.date_filters import MIN_DATE, MAX_DATE, MONTHS


class CalendarPicker(tk.Toplevel):
    """Seleciona um único dia da temporada, navegando por meses com setas."""
    def __init__(self, parent, initial, on_select, title='Escolha a data',
                 minimum=MIN_DATE, maximum=MAX_DATE):
        super().__init__(parent)
        self.on_select = on_select
        self.minimum, self.maximum = minimum, maximum
        self.year, self.month = initial.year, initial.month
        self.selected = initial
        self.title(title)
        self.configure(bg=C['panel'])
        self.resizable(False, False)
        self.transient(parent.winfo_toplevel())
        self.protocol('WM_DELETE_WINDOW', self.destroy)

        self.header = tk.Frame(self, bg=C['panel'], padx=12, pady=12)
        self.header.pack(fill='x')
        self.prev_button = self._nav('‹', -1)
        self.month_label = tk.Label(self.header, bg=C['panel'], fg=C['fg'],
                                    font=('Segoe UI', 12, 'bold'), width=18)
        self.month_label.pack(side='left', padx=6)
        self.next_button = self._nav('›', 1)
        self.days = tk.Frame(self, bg=C['panel'], padx=12, pady=5)
        self.days.pack(fill='both')
        self.footer = tk.Label(self, text='Clique em um dia para selecionar',
                               bg=C['panel'], fg=C['muted'], font=('Segoe UI', 9), pady=12)
        self.footer.pack()
        self.draw()
        self.update_idletasks()
        self.geometry(f'+{max(0, parent.winfo_rootx()+30)}+{max(0, parent.winfo_rooty()+35)}')
        self.grab_set()
        self.focus_force()

    def _nav(self, text, direction):
        btn = tk.Button(self.header, text=text, bg=C['panel2'], fg=C['fg'],
                        relief='flat', bd=0, font=('Segoe UI', 15, 'bold'),
                        width=3, cursor='hand2', command=lambda:self.move(direction))
        btn.pack(side='left')
        return btn

    def move(self, direction):
        index = self.year * 12 + self.month - 1 + direction
        year, month0 = divmod(index, 12)
        candidate = date(year, month0+1, 1)
        if date(self.minimum.year, self.minimum.month, 1) <= candidate <= date(self.maximum.year, self.maximum.month, 1):
            self.year, self.month = year, month0+1
            self.draw()

    def draw(self):
        self.month_label.config(text=f'{MONTHS[self.month-1]} {self.year}')
        self.prev_button.config(state='disabled' if (self.year,self.month)==(self.minimum.year,self.minimum.month) else 'normal')
        self.next_button.config(state='disabled' if (self.year,self.month)==(self.maximum.year,self.maximum.month) else 'normal')
        for child in self.days.winfo_children():
            child.destroy()
        for col, name in enumerate(('Seg','Ter','Qua','Qui','Sex','Sáb','Dom')):
            tk.Label(self.days,text=name,width=4,bg=C['panel'],fg=C['muted'],
                     font=('Segoe UI',9,'bold')).grid(row=0,column=col,padx=2,pady=4)
        for row, week in enumerate(calendar.Calendar(firstweekday=0).monthdayscalendar(self.year,self.month), start=1):
            for col, day in enumerate(week):
                if not day:
                    tk.Label(self.days, text='',width=4,bg=C['panel']).grid(row=row,column=col)
                    continue
                candidate = date(self.year,self.month,day)
                usable = self.minimum <= candidate <= self.maximum
                active = candidate == self.selected
                b = tk.Button(self.days, text=str(day), width=4, relief='flat', bd=0,
                              bg=C['accent'] if active else C['panel2'],
                              fg=C['bg'] if active else (C['fg'] if usable else C['muted']),
                              cursor='hand2' if usable else 'arrow',
                              state='normal' if usable else 'disabled',
                              command=lambda d=candidate:self.choose(d))
                b.grid(row=row,column=col,padx=2,pady=2,ipady=5)

    def choose(self, selected):
        self.destroy()
        self.on_select(selected)
