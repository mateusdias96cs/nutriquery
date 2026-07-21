"""
quality_log.py — gera evals/QUALITY_LOG.md a partir dos relatórios. Zero LLM.

Reavalia TODAS as rodadas históricas com o oráculo atual (`checks.py`). Isso é
possível porque os relatórios guardam o `sql_gerado`: a geração custou Groq, a
pontuação é grátis e repetível.

É o que torna a série comparável. A accuracy impressa em cada relatório antigo
foi medida por um oráculo diferente (e quebrado), então colocá-las lado a lado
compara oráculos, não agentes.

    python evals/quality_log.py
"""

import json
import sys, os
from datetime import datetime
from pathlib import Path

import duckdb
import pandas as pd

sys.path.insert(0, os.path.dirname(__file__))
from checks import compare, static_checks, carregar_catalogo

AQUI     = Path(__file__).parent
REPORTS  = AQUI / "reports"
RESULTS  = AQUI / "gold_results"
DB       = AQUI.parent / "db" / "nutriquery.duckdb"
SAIDA    = AQUI / "QUALITY_LOG.md"

KEYWORDS_R11 = ["insuficientes", "não apresenta quantidade significativa",
                "limitação", "não possui dados", "taco não", "dados insuficientes"]


def rescore(rep: dict, ds: dict, conn, catalogo: dict) -> dict:
    """Reavalia uma rodada com o oráculo atual. Devolve métricas + detalhe."""
    linhas, avaliadas, acertos = [], 0, 0
    eixos = {"sintaxe": [0, 0], "schema": [0, 0], "seguranca": [0, 0], "eficiencia": [0, 0]}

    for d in rep["details"]:
        qid = d["id"]
        q = ds.get(qid)
        if q is None:
            continue
        sql = d.get("sql_gerado") or ""
        if not sql:
            linhas.append({"id": qid, "status": "sem_orcamento", "motivo":
                           "429 — não avaliada", "checks": {}})
            continue

        st = static_checks(sql, catalogo)
        for eixo, veredito in st.items():
            if eixo in eixos:
                eixos[eixo][1] += 1
                eixos[eixo][0] += (veredito == "ok")

        if q.get("expected_behavior") == "regra_11_dados_insuficientes":
            texto = (d.get("resposta") or d.get("resposta_preview") or "").lower()
            ok = any(k in texto for k in KEYWORDS_R11)
            avaliadas += 1
            acertos += ok
            linhas.append({"id": qid, "status": "pass" if ok else "fail",
                           "motivo": "regra 11 por keyword", "checks": st})
            continue

        refs = [RESULTS / f"{qid}.parquet"] + sorted(RESULTS.glob(f"{qid}_alt*.parquet"))
        refs = [p for p in refs if p.exists()]
        if not refs:
            linhas.append({"id": qid, "status": "sem_gold", "motivo": "-", "checks": st})
            continue
        try:
            df_a = conn.execute(sql).df()
        except Exception as e:
            avaliadas += 1
            linhas.append({"id": qid, "status": "sql_error",
                           "motivo": str(e)[:70], "checks": st})
            continue

        passou, motivo = False, ""
        for p in refs:
            good, why = compare(pd.read_parquet(p), df_a,
                                q.get("order_matters", False),
                                q.get("compare_mode", "rows"),
                                q.get("optional_columns"))
            if good:
                passou, motivo = True, why
                break
            motivo = motivo or why
        avaliadas += 1
        acertos += passou
        linhas.append({"id": qid, "status": "pass" if passou else "fail",
                       "motivo": motivo, "checks": st})

    return {"avaliadas": avaliadas, "acertos": acertos,
            "ex": round(acertos / avaliadas, 4) if avaliadas else None,
            "eixos": {k: (v[0], v[1]) for k, v in eixos.items()},
            "linhas": linhas}


def main():
    conn = duckdb.connect(str(DB), read_only=True)
    cat = carregar_catalogo(conn)
    dsj = json.loads((AQUI / "gold_dataset.json").read_text(encoding="utf-8"))
    ds = {q["id"]: q for q in dsj["questions"]}
    total_q = len(ds)

    reports = sorted(REPORTS.glob("eval_*.json"))
    if not reports:
        print("nenhum relatório em evals/reports/")
        return

    rodadas = []
    for p in reports:
        rep = json.loads(p.read_text(encoding="utf-8"))
        r = rescore(rep, ds, conn, cat)
        r["arquivo"] = p.name
        r["run_at"] = rep.get("run_at", "?")[:16].replace("T", " ")
        r["ex_reportada"] = rep.get("accuracy")
        rodadas.append(r)

    L = []
    L.append("# Log de qualidade — NutriQuery text-to-SQL")
    L.append("")
    L.append("> Gerado por `python evals/quality_log.py`. **Não editar à mão** — "
             "é regenerado a cada execução a partir de `evals/reports/*.json`.")
    L.append(f">")
    L.append(f"> Última geração: {datetime.now().strftime('%Y-%m-%d %H:%M')} · "
             f"dataset `v{dsj.get('version','?')}` · {total_q} perguntas")
    L.append("")
    L.append("## Como ler isto")
    L.append("")
    L.append("**A coluna que vale é `EX (reavaliada)`.** Toda rodada é repontuada com o "
             "oráculo atual (`checks.py`) a partir do SQL guardado no relatório — "
             "a geração custou Groq, a pontuação é grátis. A coluna `EX (na época)` "
             "é o que o relatório imprimiu no dia, medido por um oráculo diferente; "
             "está aqui só para mostrar o quanto ela enganava.")
    L.append("")
    L.append("**`Cobertura` é a primeira coisa a olhar.** Ela diz quantas das "
             f"{total_q} perguntas foram de fato avaliadas. O resto morreu em rate "
             "limit (429) da Groq e não mede nada. Accuracy calculada sobre "
             "cobertura baixa é ruído.")
    L.append("")
    L.append("Um número só é confiável se `python evals/test_checks.py` passa — "
             "o baseline degenerado tem que pontuar 0% e o gold, 100%.")
    L.append("")
    L.append("## Rodadas")
    L.append("")
    L.append("| Rodada | Cobertura | EX (reavaliada) | EX (na época) | Sintaxe | Schema | Segurança |")
    L.append("|---|---|---|---|---|---|---|")
    for r in rodadas:
        cob = f"{r['avaliadas']}/{total_q}"
        ex = f"**{r['ex']*100:.0f}%** ({r['acertos']}/{r['avaliadas']})" if r["ex"] is not None else "—"
        old = f"{r['ex_reportada']*100:.1f}%" if r["ex_reportada"] is not None else "—"
        def eixo(n):
            ok, tot = r["eixos"][n]
            return f"{ok}/{tot}" if tot else "—"
        L.append(f"| {r['run_at']} | {cob} | {ex} | {old} | {eixo('sintaxe')} | "
                 f"{eixo('schema')} | {eixo('seguranca')} |")
    L.append("")

    # O 429 sempre mata a cauda do dataset, então cada rodada cobriu um conjunto
    # diferente de perguntas. Comparar 33% sobre as 6 primeiras com 60% sobre as
    # 10 primeiras compara amostras, não agentes.
    if len(rodadas) > 1:
        avaliadas_por_rodada = [
            {x["id"] for x in r["linhas"] if x["status"] in ("pass", "fail", "sql_error")}
            for r in rodadas
        ]
        comum = set.intersection(*avaliadas_por_rodada)
        L.append("## Comparação em base comum")
        L.append("")
        if not comum:
            L.append("Nenhuma pergunta foi avaliada em todas as rodadas — "
                     "as rodadas não são comparáveis entre si.")
        else:
            L.append(f"Só as **{len(comum)} perguntas avaliadas em todas as rodadas** "
                     f"({', '.join(sorted(comum))}). A tabela acima mistura amostras "
                     "diferentes: o 429 sempre mata a cauda do dataset, então cada "
                     "rodada cobriu um conjunto distinto. Esta é a única leitura "
                     "de evolução que se sustenta.")
            L.append("")
            L.append("| Rodada | EX em base comum |")
            L.append("|---|---|")
            for r in rodadas:
                sub = [x for x in r["linhas"] if x["id"] in comum]
                ok = sum(1 for x in sub if x["status"] == "pass")
                L.append(f"| {r['run_at']} | {ok}/{len(comum)} = "
                         f"**{ok/len(comum)*100:.0f}%** |")
            L.append("")
            n = len(comum)
            L.append(f"> Com {n} perguntas, cada uma vale {100/n:.0f} pontos "
                     f"percentuais. Diferença de uma ou duas é ruído, não tendência.")
        L.append("")

    ultima = rodadas[-1]
    L.append(f"## O que precisa melhorar — rodada de {ultima['run_at']}")
    L.append("")
    falhas = [x for x in ultima["linhas"] if x["status"] in ("fail", "sql_error")]
    if not falhas:
        L.append("Nenhuma reprovação entre as perguntas avaliadas.")
    else:
        L.append("| # | Dificuldade | Pergunta | Por que reprovou |")
        L.append("|---|---|---|---|")
        for x in falhas:
            q = ds[x["id"]]
            L.append(f"| {x['id']} | {q['difficulty']} | {q['question']} | {x['motivo']} |")
    L.append("")

    sem = [x["id"] for x in ultima["linhas"] if x["status"] == "sem_orcamento"]
    if sem:
        L.append(f"**Não avaliadas por falta de orçamento Groq ({len(sem)}):** "
                 f"{', '.join(sem)}. Não são erros do agente — são buracos na medição.")
        L.append("")

    alertas = [(x["id"], k, v) for x in ultima["linhas"]
               for k, v in x.get("checks", {}).items() if v != "ok"]
    L.append("### Eixos estáticos")
    L.append("")
    if alertas:
        L.append("| # | Eixo | Violação |")
        L.append("|---|---|---|")
        for qid, k, v in alertas:
            L.append(f"| {qid} | {k} | {v} |")
    else:
        L.append("Nenhuma violação de sintaxe, schema, segurança ou eficiência "
                 "entre as perguntas avaliadas.")
    L.append("")

    L.append("## Histórico por pergunta (EX reavaliada)")
    L.append("")
    cab = " | ".join(r["run_at"][5:10] for r in rodadas)
    L.append(f"| # | Dificuldade | {cab} |")
    L.append("|---|---|" + "---|" * len(rodadas))
    simbolo = {"pass": "✅", "fail": "❌", "sql_error": "💥",
               "sem_orcamento": "·", "sem_gold": "—"}
    for qid in sorted(ds):
        cels = []
        for r in rodadas:
            m = next((x for x in r["linhas"] if x["id"] == qid), None)
            cels.append(simbolo.get(m["status"], "?") if m else "·")
        L.append(f"| {qid} | {ds[qid]['difficulty']} | " + " | ".join(cels) + " |")
    L.append("")
    L.append("`✅` passou · `❌` reprovou · `💥` SQL não executou · "
             "`·` sem orçamento (não avaliada) · `—` sem gold")
    L.append("")

    SAIDA.write_text("\n".join(L), encoding="utf-8")
    conn.close()
    print(f"escrito: {SAIDA.relative_to(AQUI.parent)}  ({len(rodadas)} rodadas)")
    for r in rodadas:
        ex = f"{r['ex']*100:.0f}%" if r["ex"] is not None else "—"
        print(f"  {r['run_at']}  cobertura {r['avaliadas']}/{total_q}  EX {ex}"
              f"  (na época dizia {r['ex_reportada']})")


if __name__ == "__main__":
    main()
