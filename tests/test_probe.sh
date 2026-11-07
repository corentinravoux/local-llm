#!/usr/bin/env bash
# Run llm_probe.py against a mock llama-server in each mode and check exit codes.
set -u
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
probe="$here/../skills/local-llm/scripts/llm_probe.py"
port=18931; fail=0
check() {  # mode expected_exit
    python3 -I "$here/mock_server.py" "$port" "$1" & pid=$!
    sleep 0.5
    python3 -I "$probe" --url "http://127.0.0.1:$port" >/dev/null; got=$?
    kill "$pid"; wait "$pid" 2>/dev/null
    if [[ "$got" == "$2" ]]; then echo "ok   $1 (exit $got)"; else echo "FAIL $1 (exit $got, want $2)"; fail=1; fi
    port=$((port+1))
}
check good 0
check leak 1
check nocache 1
python3 -I "$probe" --url "http://127.0.0.1:18999" >/dev/null
[[ $? == 1 ]] && echo "ok   down (exit 1)" || { echo "FAIL down"; fail=1; }
exit $fail
