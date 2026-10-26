# Apuração 2026 — projeção própria do 2º turno

Modelo de projeção para a noite do 2º turno presidencial de 25/10/2026 (Lula 13 × Flávio Bolsonaro 22), alimentado ao vivo pela
divulgação oficial do TSE e exibido numa página local (http://localhost:8099). É uma reconstrução do método de Rodrigo Mahlmeister
(projecao.2026elections.workers.dev), testada em replays das noites reais de 2018 e 2022 antes de ir para a noite real.

## Resultado da noite de 25/10/2026

Resultado quase final às 21:56 (99,95% do eleitorado apurado): **Lula 51,78% × Flávio Bolsonaro 48,22%**. Último instantâneo
(26/10 12:24, 99,99%): 64.255.787 × 59.825.688 votos.

| Apurado | Hora | Projeção Lula | Faixa de 90% | Erro vs. final |
|---|---|---|---|---|
| 2,1% | 19:18 | 51,96 | 49,96 – 53,96 | +0,18 |
| 3,3% | 19:25 | 52,52 | 50,54 – 54,50 | +0,74 |
| 5,5% | 19:32 | 51,86 | 50,84 – 52,89 | +0,08 |
| 10,2% | 19:41 | 51,51 | 50,66 – 52,36 | −0,27 |
| 20,6% | 20:00 | 51,26 | 50,38 – 52,15 | −0,52 |
| 30,8% | 20:11 | 51,65 | 51,38 – 51,91 | −0,13 |
| 51,1% | 20:30 | 51,74 | 51,63 – 51,86 | −0,04 |
| 75,5% | 20:51 | 51,80 | 51,76 – 51,83 | +0,02 |
| 91,2% | 21:05 | 51,79 | 51,76 – 51,82 | +0,01 |

Os 131 pontos com projeção tiveram o resultado dentro da faixa de 90%. Matematicamente definido às 21:10 (98,0% apurado).
A noite foi atípica: o STF prorrogou a votação até 19h em todo o país; o TSE publicou 0,25% às 17:06, pausou às 17:20 e retomou às 19:01.

## Estrutura

- `live/` — noite real: `collector.py` (lê a divulgação do TSE a cada ciclo e grava `saida/`), `live_model.py` (modelo),
  `tse_client.py`, `noite.sh`/`parar.sh` (sobe/para página + coletor), `fake_tse.py` (TSE falso para ensaio com 2022). Ver `live/README.md`.
- `replay/` — reconstrução e testes: `prep.py`/`prep2026.py`/`base.py` (TSE → parquet), `model.py` (1º turno), `model2t.py` (2º turno,
  mesmo modelo de `live_model.py`), `exp2t.py` (experimentos; resultados em `replay/EXPERIMENTOS_2T.md`), `calib2t.py`, `compare2026.py`.
- `site/` — página estática (D3) que faz polling de `site/dados/apuracao.json`; `python -m http.server 8099 --directory site`.
- `saida/` — o que o coletor gravou na noite: `apuracao.json` (estado final + série de pontos), `collector.log` e `historico/`
  (instantâneo completo por ciclo até o fim da apuração, 22:41; depois um por hora).
- `data_tse/` — dados (ver abaixo). `tools/` — capturas de tela com Playwright.

## Como rodar

```sh
python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt
live/noite.sh            # página em http://localhost:8099 + coletor em loop (caffeinate evita o sleep do Mac)
tail -f saida/collector.log
live/parar.sh --tudo     # para coletor e servidor
```

Códigos do pleito/eleição são descobertos no `ele-c.json` do TSE; o prior do intercepto (`PRIOR` em `noite.sh`) vem das pesquisas da véspera.

## Dados: o que está no repositório e como regenerar o resto

No repositório: `data_tse/parquet/votacao_*.parquet` e `detalhe_*.parquet` (1º e 2º turno de 2018 e 2022, 1º turno de 2026, por seção),
CSVs de replays/experimentos, o relatório do 1º turno de 2026 (`rel2026/`) e `saida/` da noite.

Fora do repositório (`.gitignore`), por peso ou por serem derivados:
- `data_tse/raw/*.zip` — zips do TSE (URLs em `data_tse/raw/urls.txt`); `replay/prep.py` gera os parquet de votação, detalhe e locais.
- `data_tse/parquet/locais_*.parquet` e `base_*.parquet` — saídas de `prep.py` e `replay/base.py` (replay do 1º turno).
- `data_tse/api2026/` — boletins de urna do 1º turno de 2026 baixados da API do TSE (`bu/*.ndjson`) e listas de seções (`cs/`);
  `replay/prep2026.py` os converte em `votacao_2026`/`detalhe_2026.parquet`. O script de download não foi preservado (`fetch.log` mostra o ritmo).
- `data_tse/exp/*.parquet` — caches de `replay/exp2t.py`.
- `data_tse/ext/sibila/` e `data_tse/sibila/` — clone e base do projeto Sibila (github.com/carlos-schwabe/sibila), usado só como referência.
- `ensaio/`, `site_artifact/`, `*_backup.*` — ensaios, capturas e cópias de segurança anteriores ao git.

## Modelo (resumo)

Base = 1º turno por seção. Para cada município apurado, swing em log(PT/PL) contra o 1º turno das mesmas seções; regressão ponderada
sobre o perfil do 1º turno (razão log, votos nos eliminados, porte), hierárquica Brasil → região → UF com encolhimento empírico-bayesiano;
seções pendentes = 1º turno + swing previsto; comparecimento e válidos ajustados por UF. Prior do intercepto com peso de 20 mil votos
(só pesa nos primeiros minutos). Incerteza: sd² = (1,3·sd_bootstrap_municípios)² + (sd_bootstrap_UFs · fração pendente)²;
faixa de 90% = ±1,645 sd; P(vitória) = Φ((proj − 50)/sd). Prévia (sem faixa) até 2% apurado; com menos de 20 municípios ou 3 UFs
a prévia usa só o 1º turno + prior.

## Lições da divulgação do TSE (para a próxima)

- A lista de seções por UF (`cs.json`) marca seções horas antes de os votos saírem (exterior desde 14h, votos embargados até 17h).
  Seção só conta como apurada se o arquivo municipal (EA20) tem `st > 0` e comparecimento `> 0`.
- A `cs.json` atrasa ~5 min em relação aos arquivos EA20. O coletor lê os 27 arquivos de UF e, onde o total da UF está à frente,
  relê os municípios incompletos; o modelo trata eleitorado apurado além do marcado como amostra proporcional das seções não marcadas.
- Carga aguentada sem bloqueio: 100 req/s, 24 workers, ~5 mil arquivos municipais por ciclo (ciclos de 45–120 s na fase pesada); 378 mil
  requisições na noite, 28 timeouts, nenhum 403/429. Com ETag/304 a maior parte volta vazia.
- O coletor retoma o estado de `saida/` ao reiniciar, o que segurou a pausa de 17:20–19:01 sem intervenção.
