#!/bin/zsh
# Pokretanje iz macOS aplikacije bez prozora terminala.
export PATH="/opt/homebrew/bin:/usr/local/bin:/Library/Frameworks/Python.framework/Versions/Current/bin:/usr/bin:/bin:/usr/sbin:/sbin:$PATH"
resources_dir="${0:A:h}"
python_path="$(command -v python3)"
if [[ -z "$python_path" ]] || ! "$python_path" -c 'import sys; assert sys.version_info >= (3, 10)' >/dev/null 2>&1; then
    print -u2 'Potreban je Python 3.10 ili noviji. Instaliraj Python sa python.org pa ponovo otvori aplikaciju.'
    exit 1
fi
log_dir="$HOME/Library/Application Support/SSH UI"
mkdir -p "$log_dir" || exit 1
chmod 700 "$log_dir"
nohup "$python_path" "$resources_dir/prototip/server.py" >>"$log_dir/server.log" 2>&1 </dev/null &
