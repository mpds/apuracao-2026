# Noite do 2º turno (25/10/2026) — como rodar

Pré-requisitos (prontos): `.venv` (pandas/numpy/scipy); `data_tse/parquet/votacao_2026.parquet` e `detalhe_2026.parquet`
(1º turno de 2026 por seção, base do modelo, 499.103 seções).

## Tudo local, um comando
```sh
live/noite.sh            # sobe http://localhost:8099 (página) + coletor em loop com reinício automático (caffeinate evita sleep)
tail -f saida/collector.log
live/parar.sh            # para o coletor (--tudo para também o servidor)
```
- Códigos do 2º turno descobertos sozinhos no `ele-c.json` (hoje: pleito 3221, eleição 6258).
- Prior do intercepto: `PRIOR=49.0` em `noite.sh` (Lula % válidos; Datafolha e Quaest 23–24/10: 49 × 51). Peso 20 mil votos: só pesa nos primeiros minutos.
- A cada ~60 s: lista de seções por UF (28 req, ETag/304 quando nada mudou) + arquivos municipais que mudaram + Brasil. 100 req/s (24 workers); os 27 arquivos de UF indicam municípios que a lista ainda não marcou.
- Grava `saida/apuracao.json` e a cópia `site/dados/apuracao.json` (a página faz polling a cada 60 s) e `saida/historico/*.json.gz`.
- Se o coletor cair, o loop reinicia em 15 s e ele retoma os pontos e o estado do último ciclo (`--sem-retomar` para zerar).
- Antes das 17h os ciclos mostram 0% e a página fica em "Aguardando o início da apuração".

## Modelo (live/live_model.py = replay/model2t.py)
Swing municipal em log(PT/PL) vs. o 1º turno das mesmas seções; regressão ponderada no perfil do 1º turno (razão log, votos nos eliminados,
porte) Brasil → região → UF com encolhimento EB; seções pendentes = 1º turno + swing previsto; comparecimento e válidos ajustados por UF.

Incerteza (nova, 25/10): sd² = (1,3·sd_bootstrap_municípios)² + (sd_bootstrap_UFs · fração pendente)². Faixa 90% = ±1,645 sd;
P(vitória) = Φ((proj − 50)/sd). Calibração nos replays de 2018 e 2022 (26 pontos): cobertura 100%, |z| q90 = 1,05.
Antes era faixa de municípios × 2,7 (calibrada só em 2022).

## Ensaio (TSE falso com a noite do 2º turno de 2022)
```sh
.venv/bin/python live/fake_tse.py --pq data_tse/parquet --ano 2022 --speed 30 --start 8 --port 8787 &
.venv/bin/python live/collector.py --base http://localhost:8787 --pleito 9999 --eleicao 9998 --t1 2022 --out ensaio/x --intervalo 5 --rps 300 --ciclos 7 --sem-retomar --prior-pt 52
```

## Experimentos (replay/exp2t.py, resultados em data_tse/exp/)
Ver `replay/EXPERIMENTOS_2T.md`.
