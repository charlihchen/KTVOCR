@echo off
:: KTVOCR one-click Windows setup — double-click this file.
:: Uses the py -3.11 launcher on purpose: bare "py" picks Python 3.15 on
:: machines with both installed, and numpy 1.26.4 has no prebuilt wheel
:: for 3.15, so pip tries (and fails) to compile it from source.
cd /d %~dp0
py -3.11 -m pip install -r requirements.txt
py -3.11 batch.py check
pause
