@echo off
chcp 65001 >nul 2>&1
title Stremio Turkce Dublaj Addon
cd /d "%~dp0"
python start_all.py
pause
