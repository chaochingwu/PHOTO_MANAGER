"""R02d desktop design tokens, shared by the gallery and workspace."""
import tkinter as tk
from tkinter import ttk
BG='#171b21'; PANEL='#222831'; FIELD='#2b333e'; LINE='#3a4552'; TEXT='#e6ebf1'; MUTED='#a7b3c2'; ACCENT='#5799e5'; SELECT='#344f70'; CANVAS='#11151b'
def apply(root):
    root.configure(bg=BG)
    root.option_add('*Font', 'Microsoft\\ JhengHei 10')
    root.option_add('*Toplevel.background', BG)
    root.option_add('*Listbox.background', PANEL)
    root.option_add('*Listbox.foreground', TEXT)
    root.option_add('*Listbox.selectBackground', SELECT)
    root.option_add('*Listbox.selectForeground', TEXT)
    root.option_add('*Listbox.highlightThickness', 0)
    root.option_add('*Listbox.borderWidth', 0)
    root.option_add('*Listbox.relief', 'flat')
    s=ttk.Style(root);s.theme_use('clam')
    s.configure('.',background=BG,foreground=TEXT,font=('Microsoft JhengHei',10),bordercolor=LINE,lightcolor=LINE,darkcolor=LINE,focuscolor=ACCENT)
    s.configure('TFrame',background=BG);s.configure('Panel.TFrame',background=PANEL)
    s.configure('TLabel',background=BG,foreground=TEXT);s.configure('Muted.TLabel',foreground=MUTED);s.configure('Heading.TLabel',font=('Microsoft JhengHei',12,'bold'));s.configure('Brand.TLabel',font=('Segoe UI',19,'bold'));s.configure('Preview.TLabel',background=CANVAS,foreground=MUTED)
    s.configure('TButton',background=FIELD,foreground=TEXT,padding=(10,5),relief='flat');s.map('TButton',background=[('disabled',PANEL),('pressed',SELECT),('active',LINE)],foreground=[('disabled',MUTED)])
    s.configure('Accent.TButton',background='#3069a5',foreground='#ffffff');s.map('Accent.TButton',background=[('disabled',PANEL),('active','#397dbf')])
    s.configure('TEntry',fieldbackground=FIELD,foreground=TEXT,insertcolor=TEXT,padding=5)
    s.configure('TCombobox',fieldbackground=FIELD,foreground=TEXT,arrowcolor=TEXT,padding=4);s.map('TCombobox',fieldbackground=[('readonly',FIELD)],foreground=[('readonly',TEXT)],selectbackground=[('readonly',SELECT)],selectforeground=[('readonly',TEXT)])
    root.option_add('*TCombobox*Listbox.background',FIELD);root.option_add('*TCombobox*Listbox.foreground',TEXT)
    for name in ('TCheckbutton','TRadiobutton'):
        s.configure(name,background=BG,foreground=TEXT,indicatorbackground=FIELD);s.map(name,background=[('active',BG)],indicatorbackground=[('selected',ACCENT)])
    s.configure('TLabelframe',background=BG,bordercolor=LINE,relief='solid');s.configure('TLabelframe.Label',background=BG,foreground=MUTED,font=('Microsoft JhengHei',10,'bold'))
    s.configure('Treeview',background=PANEL,fieldbackground=PANEL,foreground=TEXT,rowheight=29,borderwidth=0);s.map('Treeview',background=[('selected',SELECT)],foreground=[('selected',TEXT)]);s.configure('Treeview.Heading',background=FIELD,foreground=TEXT,relief='flat',padding=5)
    s.configure('TPanedwindow',background=LINE);s.configure('Vertical.TScrollbar',background=FIELD,troughcolor=BG,arrowcolor=MUTED)
    return s
