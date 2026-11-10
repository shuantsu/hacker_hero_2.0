@echo off
cd /d "%~dp0src"
python -m nuitka --mode=onefile --enable-plugin=pyside6 --assume-yes-for-downloads --windows-console-mode=disable --output-dir=../build --output-filename=hacker-hero hacker_hero
pause