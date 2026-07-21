# Validação pendente — rodar rodada completa

> Registro das correções aplicadas em **2026-07-21** que ainda **não foram
> gravadas por uma rodada completa de eval**. Documento manual (não é gerado).

## O que rodar

```bash
python evals/run_evals.py      # rodada completa (custa orçamento Groq — ver abaixo)
python evals/quality_log.py    # regenera o QUALITY_LOG a partir do novo report
```

⚠️ **Orçamento:** `prompt.py`, `gold_dataset.json` e `checks.py` mudaram desde o
último report, então o **fingerprint mudou** — a rodada **reexecuta as 21
perguntas do zero** (não reaproveita nenhuma). Custo ~94k tokens ≈ orçamento
diário inteiro do free tier da Groq (100k/dia, janela deslizante de 24h). Rodar
só com a janela limpa. O cache exact-match já guarda o SQL correto das perguntas
abaixo, o que reduz chamadas se o cache não for invalidado.

## Por que é preciso

As correções foram **validadas isoladamente** (rerun por pergunta, cache limpo),
mas o report oficial de 21/07 guardou o SQL **anterior** ao fix para três delas.
A reavaliação repontua a partir do SQL guardado, então elas ainda aparecem como
FAIL até uma rodada completa regerar o SQL com o `prompt.py` novo.

| Pergunta | Status na reaval (86%, 18/21) | Fix | Precisa de rodada? |
|---|---|---|---|
| Q004 | ✅ já conta | gold: `AND fv.value IS NOT NULL` (não rankear nutriente NULL) | não (correção de gold) |
| Q016 | ✅ já conta | oráculo: `optional_columns` (coluna decorativa) | não |
| Q017 | ✅ já conta | oráculo: `optional_columns` | não |
| Q020 | ✅ já conta | gold: desempate `, f.food_name` | não |
| **Q005** | ❌ ainda FAIL na reaval | prompt: exemplo few-shot `RANK` + gold `order_matters=false` | **SIM** — SQL guardado é `ROW_NUMBER` |
| **Q007** | ❌ ainda FAIL na reaval | prompt: regra 16 (nutriente composto = `SUM`) | **SIM** — SQL guardado é `MAX(CASE)` |
| **Q012** | ❌ ainda FAIL na reaval | prompt: regra 16 (`SUM`) | **SIM** — SQL guardado ranqueava 1 componente |

**Projeção da rodada completa: 21/21 = 100%**, se o modelo reproduzir os SQLs
dos reruns isolados (que já estão no cache). Confirmar com `test_checks.py` antes
(baseline degenerado tem que dar 0%, gold 100%).

## Depois de rodar

- Apagar este arquivo quando a rodada completa confirmar Q005/Q007/Q012.
- Conferir o `QUALITY_LOG.md` e o histórico por pergunta.
