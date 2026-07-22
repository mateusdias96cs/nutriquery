# Log de qualidade — NutriQuery text-to-SQL

> Gerado por `python evals/quality_log.py`. **Não editar à mão** — é regenerado a cada execução a partir de `evals/reports/*.json`.
>
> Última geração: 2026-07-22 09:17 · dataset `v2.0` · 21 perguntas

## Como ler isto

**A coluna que vale é `EX (reavaliada)`.** Toda rodada é repontuada com o oráculo atual (`checks.py`) a partir do SQL guardado no relatório — a geração custou Groq, a pontuação é grátis. A coluna `EX (na época)` é o que o relatório imprimiu no dia, medido por um oráculo diferente; está aqui só para mostrar o quanto ela enganava.

**`Cobertura` é a primeira coisa a olhar.** Ela diz quantas das 21 perguntas foram de fato avaliadas. O resto morreu em rate limit (429) da Groq e não mede nada. Accuracy calculada sobre cobertura baixa é ruído.

Um número só é confiável se `python evals/test_checks.py` passa — o baseline degenerado tem que pontuar 0% e o gold, 100%.

## Rodadas

| Rodada | Cobertura | EX (reavaliada) | EX (na época) | Sintaxe | Schema | Segurança |
|---|---|---|---|---|---|---|
| 2026-06-26 17:21 | 6/21 | **33%** (2/6) | 4.8% | 6/6 | 6/6 | 5/6 |
| 2026-06-28 09:31 | 11/21 | **36%** (4/11) | 23.8% | 11/11 | 11/11 | 10/11 |
| 2026-07-16 11:05 | 10/21 | **70%** (7/10) | 33.3% | 10/10 | 10/10 | 10/10 |
| 2026-07-17 16:46 | 21/21 | **62%** (13/21) | 52.4% | 21/21 | 21/21 | 21/21 |
| 2026-07-20 20:49 | 14/21 | **79%** (11/14) | 71.4% | 14/14 | 14/14 | 14/14 |
| 2026-07-21 15:25 | 21/21 | **86%** (18/21) | 66.7% | 21/21 | 21/21 | 21/21 |
| 2026-07-22 09:17 | 21/21 | **100%** (21/21) | 100.0% | 21/21 | 21/21 | 21/21 |

## Comparação em base comum

Só as **6 perguntas avaliadas em todas as rodadas** (Q001, Q002, Q003, Q004, Q005, Q006). A tabela acima mistura amostras diferentes: o 429 sempre mata a cauda do dataset, então cada rodada cobriu um conjunto distinto. Esta é a única leitura de evolução que se sustenta.

| Rodada | EX em base comum |
|---|---|
| 2026-06-26 17:21 | 2/6 = **33%** |
| 2026-06-28 09:31 | 2/6 = **33%** |
| 2026-07-16 11:05 | 4/6 = **67%** |
| 2026-07-17 16:46 | 4/6 = **67%** |
| 2026-07-20 20:49 | 5/6 = **83%** |
| 2026-07-21 15:25 | 5/6 = **83%** |
| 2026-07-22 09:17 | 6/6 = **100%** |

> Com 6 perguntas, cada uma vale 17 pontos percentuais. Diferença de uma ou duas é ruído, não tendência.

## O que precisa melhorar — rodada de 2026-07-22 09:17

Nenhuma reprovação entre as perguntas avaliadas.

### Eixos estáticos

Nenhuma violação de sintaxe, schema, segurança ou eficiência entre as perguntas avaliadas.

## Histórico por pergunta (EX reavaliada)

| # | Dificuldade | 06-26 | 06-28 | 07-16 | 07-17 | 07-20 | 07-21 | 07-22 |
|---|---|---|---|---|---|---|---|---|
| Q001 | simple_filter | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Q002 | join_group | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Q003 | aggregation | ❌ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Q004 | join_group | ❌ | ❌ | ❌ | ❌ | ✅ | ✅ | ✅ |
| Q005 | aggregation | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ |
| Q006 | ambiguous | ❌ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Q007 | ambiguous | · | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ |
| Q008 | simple_filter | · | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Q009 | ambiguous | · | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Q010 | ambiguous | · | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Q011 | simple_filter | · | ✅ | · | ✅ | ✅ | ✅ | ✅ |
| Q012 | join_group | · | · | · | ❌ | ❌ | ❌ | ✅ |
| Q013 | simple_filter | · | · | · | ✅ | ✅ | ✅ | ✅ |
| Q014 | join_group | · | · | · | ✅ | ✅ | ✅ | ✅ |
| Q015 | aggregation | · | · | · | ❌ | · | ✅ | ✅ |
| Q016 | join_group | · | · | · | ❌ | · | ✅ | ✅ |
| Q017 | aggregation | · | · | · | ❌ | · | ✅ | ✅ |
| Q018 | simple_filter | · | · | · | ❌ | · | ✅ | ✅ |
| Q019 | join_group | · | · | · | ✅ | · | ✅ | ✅ |
| Q020 | aggregation | · | · | · | ✅ | · | ✅ | ✅ |
| Q021 | ambiguous | · | · | · | ✅ | · | ✅ | ✅ |

`✅` passou · `❌` reprovou · `💥` SQL não executou · `·` sem orçamento (não avaliada) · `—` sem gold
