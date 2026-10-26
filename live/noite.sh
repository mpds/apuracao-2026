#!/bin/sh
# Sobe o servidor local da página e o coletor (com reinício automático). Uso: live/noite.sh [--sem-retomar]
cd "$(dirname "$0")/.." || exit 1
PY=.venv/bin/python; PORTA=8099; PRIOR=49.0
mkdir -p saida site/dados
if ! lsof -nP -iTCP:$PORTA -sTCP:LISTEN >/dev/null 2>&1; then
  nohup $PY -m http.server $PORTA --bind 127.0.0.1 --directory site >> saida/http.log 2>&1 &
  echo $! > saida/http.pid; echo "servidor: http://localhost:$PORTA (pid $!)"
else echo "servidor já no ar: http://localhost:$PORTA"; fi
if [ -f saida/loop.pid ] && kill -0 "$(cat saida/loop.pid)" 2>/dev/null; then echo "coletor já rodando (loop pid $(cat saida/loop.pid))"; exit 0; fi
nohup caffeinate -i -s sh -c "
  while true; do
    $PY live/collector.py --pq data_tse/parquet --t1 2026 --data 25/10/2026 --out saida --site site/dados/apuracao.json --prior-pt $PRIOR --rps 100 $* >> saida/collector.log 2>&1
    rc=\$?; echo \"[\$(date +%H:%M:%S)] coletor terminou com código \$rc\" >> saida/collector.log
    [ \$rc -eq 0 ] && exit 0
    sleep 15
  done" > /dev/null 2>&1 &
echo $! > saida/loop.pid; echo "coletor: loop pid $! (log em saida/collector.log)"
