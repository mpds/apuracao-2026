#!/bin/sh
# Para o coletor (e o servidor, com --tudo).
cd "$(dirname "$0")/.." || exit 1
if [ -f saida/loop.pid ]; then pkill -P "$(cat saida/loop.pid)" 2>/dev/null; kill "$(cat saida/loop.pid)" 2>/dev/null; rm -f saida/loop.pid; fi
pkill -f "live/collector.py" 2>/dev/null; echo "coletor parado"
if [ "$1" = "--tudo" ] && [ -f saida/http.pid ]; then kill "$(cat saida/http.pid)" 2>/dev/null; rm -f saida/http.pid; echo "servidor parado"; fi
