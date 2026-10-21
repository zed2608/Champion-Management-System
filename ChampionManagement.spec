# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for the Champion Management System.
#
#   STATUS: UNTESTED. It was written without running PyInstaller (the build was not possible in the unattended session).
#   Build on a Windows PC that has Python 3.11 and the project's venv:
#       pip install pyinstaller
#       pyinstaller ChampionManagement.spec
#   The program lands in dist\ChampionManagement\ (a folder, "onedir"). Copy the whole folder to each terminal.
#   Why onedir and not a single .exe: the program writes next to itself (remember_config.json, scanner_config.json, logs\,
#   assets\profiles\) and a single-file build unpacks to a temporary folder that is deleted on exit, so those would be lost.
#
#   Each terminal still needs, next to ChampionManagement.exe: a .env (see .env.example), the Microsoft Visual C++ runtime
#   (needed by OpenCV and pyzbar), and mysqldump.exe / mysql.exe on PATH for backup and restore.
from PyInstaller.utils.hooks import collect_submodules, collect_data_files

hiddenimports = (
    collect_submodules("services")
    + collect_submodules("views")
    + collect_submodules("db")
    + collect_submodules("utils")
    + ["tkcalendar", "babel.numbers", "babel.dates", "PIL._tkinter_finder", "mysql.connector.plugins.mysql_native_password",
       "mysql.connector.plugins.caching_sha2_password", "mysql.connector.plugins.sha256_password"]
)

datas = [
    ("assets", "assets"),
    ("db/schema.sql", "db"),
    ("db/triggers.sql", "db"),
    ("db/grants.sql", "db"),
    (".env.example", "."),
]
datas += collect_data_files("customtkinter")      # themes and fonts customtkinter loads from its own folder
datas += collect_data_files("tkcalendar")
datas += collect_data_files("babel")
datas += collect_data_files("pyzbar")             # libzbar DLLs ship inside the wheel on Windows

a = Analysis(
    ["main.py"],
    pathex=["."],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["pytest", "PyQt5", "PyQt6", "PySide2", "PySide6"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="ChampionManagement",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,                 # no black console window; errors go to logs\app.log
    icon=None,
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="ChampionManagement")
