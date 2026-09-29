#!/bin/zsh
# Dvoklik na Mac-u: pokreni lokalni SSH meni i otvori ga u pregledaču.
d="${0:A:h}"
cd "$d"
if ! command -v python3 >/dev/null 2>&1; then
  echo "Potreban je Python 3. Instaliraj ga pa ponovo pokreni SSH-UI.command."
  read -r "?Pritisni Enter za zatvaranje..."
  exit 1
fi
exec python3 "$d/prototip/server.py"
