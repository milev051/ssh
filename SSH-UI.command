#!/bin/zsh
# Dvoklik na Mac-u: pokreni skriveni lokalni server i otvori ga u pregledaču.
d="${0:A:h}"
cd "$d"
if ! command -v python3 >/dev/null 2>&1; then
  echo "Potreban je Python 3. Instaliraj ga pa ponovo pokreni SSH-UI.command."
  read -r "?Pritisni Enter za zatvaranje..."
  exit 1
fi
log_dir="$HOME/Library/Application Support/SSH UI"
mkdir -p "$log_dir"
nohup python3 "$d/prototip/server.py" >>"$log_dir/server.log" 2>&1 </dev/null &
exit 0
