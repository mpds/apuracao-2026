# Experimentos do modelo do 2º turno (25/10/2026, manhã da eleição)

Duas noites reais, base = 1º turno da mesma eleição na mesma seção, ordem real de totalização:
- 2018: Haddad 38,9% (1T, entre os dois) → 44,9% final (swing +6, 25% de votos em eliminados no 1T).
- 2022: Lula 52,9% → 50,9% (swing −2, 8% em eliminados — o análogo mais próximo de 2026: 7,8% em eliminados, polls = 1T).

Harness: `replay/exp2t.py` (`variantes` e `boot`), saídas em `data_tse/exp/`.

## Estimativa pontual — MAE do erro (proj − final) por faixa de % apurado
| variante | 2018 1–3% | 2018 3–10% | 2018 10–30% | 2022 1–3% | 2022 3–10% | 2022 10–30% |
|---|---|---|---|---|---|---|
| **base** (modelo atual) | 0,135 | 0,164 | 0,058 | 0,521 | 0,223 | 0,120 |
| int (só intercepto hierárquico) | 0,290 | 0,440 | 0,782 | 0,254 | 0,221 | 0,135 |
| lp (só razão log) | 1,093 | 0,256 | 0,260 | 0,367 | 0,101 | 0,078 |
| lp_out (sem porte) | 0,746 | 0,515 | 0,103 | 0,295 | 0,174 | 0,091 |
| base + resíduo municipal (K=2000) | 0,129 | 0,181 | 0,075 | 0,521 | 0,225 | 0,127 |
| base + ridge nas inclinações (3e5, padronizado) | 0,082 | 0,193 | 0,058 | 0,489 | 0,223 | 0,120 |
| interceptos aleatórios por UF, inclinações nacionais | 0,613 | 0,542 | 0,602 | 0,329 | 0,293 | 0,186 |
| pesos √votos | 0,522 | 0,177 | 0,097 | 0,441 | 0,246 | 0,089 |
| ensemble CV leave-one-UF-out (melhor membro) | 0,746 | 0,515 | 0,094 | 0,367 | 0,160 | 0,117 |
| ensemble CV (pesos 1/mse²) | 0,350 | 0,363 | 0,039 | 0,331 | 0,176 | 0,104 |

Leituras:
- Nenhuma variante domina as duas noites. As covariáveis por UF (eliminados, porte) são essenciais em 2018 e atrapalham
  cedo em 2022; o ridge nacional quase não muda nada porque o encolhimento EB no nível UF é fraco (τ² estimado grande).
- Resíduo municipal, prior mais forte da pesquisa, pesos √votos, piso de τ²: ganhos marginais ou inconsistentes.
- Ensemble com pesos por validação cruzada deixando uma UF de fora falha: a CV mede o erro nos municípios já apurados
  (pequenos, cedo) e não a extrapolação para as capitais; em 2018 escolhe o membro errado.
- Decisão: manter o modelo base para a estimativa pontual. Erro < 0,5 pp sustentado a partir de 3,0% (2022) e 0,5% (2018).

## Incerteza — 26 pontos (13 por noite, 0,5% a 70%), modelo base, 60 réplicas
| fórmula do sd | cobertura 90% | q90 de |z| | máx |z| | meia-faixa mediana (≥10%) |
|---|---|---|---|---|
| bootstrap municípios ×1,0 | 0,77 | 2,17 | 2,86 | 0,11 |
| bootstrap municípios ×1,5 | 0,92 | 1,45 | 1,91 | 0,17 |
| bootstrap UFs | 0,92 | 1,57 | 2,23 | 0,24 |
| √(mun² + (UF·pendente)²) | 1,00 | 1,19 | 1,45 | 0,20 |
| **√((1,3·mun)² + (UF·pendente)²)** (adotada) | 1,00 | 1,05 | 1,34 | 0,24 |
| antes: faixa municípios × 2,7 | ~1,00 | ~0,80 | — | ~0,45 |

Adotada em `live/live_model.py::ModeloVivo.ciclo`: 150 réplicas por município + 60 por UF; faixa ±1,645 sd; P(vitória) = Φ((proj−50)/sd).
Ensaio contra o TSE falso (2022, 30×): 7 ciclos de 10–17 s, projeções 50,85–51,34 (final 50,90), todas dentro da faixa.
