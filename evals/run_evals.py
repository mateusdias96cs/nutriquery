"""
run_evals.py — v4

Duas trilhas separadas:

  determinística (aqui)  — validade sintática, correção do resultado, uso de
                           schema, eficiência e segurança. Zero LLM, zero token.
  LLM-as-judge (judge.py) — só a prosa das perguntas de regra 11.

Cada eixo é reportado como métrica independente. Um gate único ("passou/não
passou") foi o que escondeu, por três rodadas, que metade das perguntas nem
tinha sido avaliada por falta de orçamento.

A geração é cara (Groq) e a pontuação é grátis: o relatório guarda o SQL e a
prosa inteiros, então dá para reavaliar rodadas antigas sem gastar token.

RETOMADA ENTRE RODADAS (ver FINGERPRINT_FILES / load_previous_results):
uma pergunta só é pulada (0 chamadas ao agente) se ela já passou numa rodada
anterior. Falha, erro e "sem orçamento" (429 do free tier da Groq — o cenário
mais comum de reexecução) sempre retestam. Isso é o que faz reexecutar o
harness depois de bater o limite diário custar só as perguntas que faltaram,
não as 21 de novo.

A pulada só vale se nada que possa mudar o veredito mudou desde a última
rodada: prompt.py (a geração em si), checks.py (o comparador) e
gold_dataset.json (pergunta/gold/regras de comparação) entram num fingerprint
sha256 gravado em `prompt_fingerprint` no relatório. Qualquer diferença nesse
fingerprint invalida o histórico INTEIRO, não só a pergunta que mudou — um
ajuste de prompt para consertar uma pergunta pode quebrar outra que antes
passava, e reaproveitar o resultado antigo dela esconderia a regressão.
"""

import hashlib
import json
import time
import duckdb
import pandas as pd
import numpy as np
import sys, os
from pathlib import Path
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))
from agent import agent_stateless, agent_sql_only, _is_rate_limit, query_cache
from checks import compare, static_checks, carregar_catalogo

DATASET_PATH   = Path(__file__).parent / "gold_dataset.json"
RESULTS_DIR    = Path(__file__).parent / "gold_results"
REPORTS_DIR    = Path(__file__).parent / "reports"
DB_PATH        = Path(__file__).parent.parent / "db" / "nutriquery.duckdb"
ROUND_DECIMALS = 2
DELAY_SECONDS  = 15

REPORTS_DIR.mkdir(exist_ok=True)

# Retomada entre rodadas: uma pergunta só é pulada (sem chamar o agente) se já
# passou numa rodada anterior E nada que possa mudar o veredito mudou desde
# então — prompt (geração), checks.py (comparador) ou o próprio gold dataset
# (pergunta, sql_reference, order_matters). Qualquer mudança nesses arquivos
# invalida TODO o histórico, não só a pergunta afetada, porque um ajuste no
# prompt pode consertar uma pergunta e quebrar outra ao mesmo tempo.
FINGERPRINT_FILES = [
    Path(__file__).parent.parent / "prompt.py",
    Path(__file__).parent / "checks.py",
    DATASET_PATH,
]


def compute_fingerprint() -> str:
    h = hashlib.sha256()
    for p in FINGERPRINT_FILES:
        h.update(p.read_bytes())
    return h.hexdigest()[:16]


def load_previous_results() -> tuple[dict, str | None]:
    """Lê o relatório mais recente já gravado (se existir) para decidir o que
    pular nesta rodada. {question_id: detail} + o fingerprint gravado nele."""
    reports = sorted(REPORTS_DIR.glob("eval_*.json"))
    if not reports:
        return {}, None
    with open(reports[-1], encoding="utf-8") as f:
        anterior = json.load(f)
    por_id = {d["id"]: d for d in anterior.get("details", [])}
    return por_id, anterior.get("prompt_fingerprint")

def normalize_value(v):
    """Normaliza um valor para comparação: float arredondado ou string lower."""
    if isinstance(v, float) or isinstance(v, np.floating):
        return round(float(v), ROUND_DECIMALS)
    if isinstance(v, str):
        return v.strip().lower()
    return v

def row_to_key(row: pd.Series) -> tuple:
    """Converte uma linha em tupla normalizável para comparação set-based."""
    return tuple(normalize_value(v) for v in row.values)

def get_numeric_columns(df: pd.DataFrame) -> list:
    return df.select_dtypes(include=[np.number, np.floating]).columns.tolist()

def smart_compare(df_agent: pd.DataFrame, df_ref: pd.DataFrame) -> tuple[bool, str]:
    """
    Comparação inteligente em 3 níveis:
    1. Exact match (após normalização)
    2. Subset match — ref está contida no agente (agente pode ter mais colunas/linhas)
    3. Numeric subset — valores numéricos do ref aparecem no agente com tolerância
    """
    if df_agent.empty and df_ref.empty:
        return True, "ambos vazios"
    if df_agent.empty:
        return False, "agente retornou vazio"

    # Pega só colunas numéricas e a primeira coluna de texto (food_name) para comparar
    # Identifica coluna de nome do alimento no ref
    str_cols_ref   = df_ref.select_dtypes(include=["object"]).columns.tolist()
    num_cols_ref   = get_numeric_columns(df_ref)

    str_cols_agent = df_agent.select_dtypes(include=["object"]).columns.tolist()
    num_cols_agent = get_numeric_columns(df_agent)

    # Se não há colunas numéricas (ex: Q010 — COUNT)
    if not num_cols_ref:
        val_ref   = set(str(v).strip().lower() for v in df_ref.values.flatten())
        val_agent = set(str(v).strip().lower() for v in df_agent.values.flatten())
        if val_ref == val_agent:
            return True, "exact match (sem numéricos)"
        if val_ref.issubset(val_agent):
            return True, "subset match (sem numéricos)"
        return False, f"valores divergem: ref={val_ref} agente={val_agent}"

    # Nível 1 — exact match por valores numéricos (ignora nomes de colunas)
    if len(num_cols_ref) <= len(num_cols_agent) and len(df_ref) == len(df_agent):
        try:
            vals_ref   = np.sort(df_ref[num_cols_ref].values.astype(float).flatten())
            vals_agent = np.sort(df_agent[num_cols_agent[:len(num_cols_ref)]].values.astype(float).flatten())
            if np.allclose(vals_ref, vals_agent, atol=0.01, equal_nan=True):
                return True, "exact match numérico"
        except Exception:
            pass

    # Nível 2 — subset match: todos os valores numéricos do ref aparecem no agente
    try:
        ref_vals   = set(round(float(v), ROUND_DECIMALS)
                        for v in df_ref[num_cols_ref].values.flatten()
                        if v is not None and not (isinstance(v, float) and np.isnan(v)))
        agent_vals = set(round(float(v), ROUND_DECIMALS)
                        for v in df_agent[num_cols_agent].values.flatten()
                        if v is not None and not (isinstance(v, float) and np.isnan(v)))
        if ref_vals.issubset(agent_vals):
            return True, "subset match numérico"
    except Exception:
        pass

    # Nível 3 — verifica se food_names do ref aparecem no agente (quando ambos têm coluna texto)
    if str_cols_ref and str_cols_agent:
        try:
            names_ref   = set(df_ref[str_cols_ref[0]].str.strip().str.lower())
            names_agent = set(df_agent[str_cols_agent[0]].str.strip().str.lower())
            overlap = len(names_ref & names_agent) / len(names_ref)
            if overlap >= 0.8:
                return True, f"food_name match {overlap*100:.0f}%"
            return False, f"food_name overlap baixo: {overlap*100:.0f}% ({len(names_ref & names_agent)}/{len(names_ref)})"
        except Exception:
            pass

    return False, f"linhas ref={len(df_ref)} agente={len(df_agent)}, sem match"


def check_regra11(response_text: str) -> bool:
    keywords = ["insuficientes", "não apresenta quantidade significativa",
                "limitação", "não possui dados", "taco não", "dados insuficientes"]
    return any(k in response_text.lower() for k in keywords)


def run_eval(q: dict, conn, catalogo: dict) -> dict:
    qid      = q["id"]
    question = q["question"]
    behavior = q.get("expected_behavior", None)
    diff     = q["difficulty"]
    # Vem da semântica da pergunta, declarado no dataset — nunca inferido do
    # ORDER BY do gold: "quanto de ferro tem o fígado" não pede ordem alguma,
    # mesmo com o gold ordenando por valor.
    order_matters = q.get("order_matters", False)
    compare_mode  = q.get("compare_mode", "rows")

    print(f"\n{'─'*60}")
    print(f"[{qid}] {question}")

    # Só as perguntas de regra 11 avaliam a resposta em prosa; as demais são
    # julgadas reexecutando o SQL, então pulam o nó `respond`.
    needs_prose = behavior == "regra_11_dados_insuficientes"
    graph = agent_stateless if needs_prose else agent_sql_only

    try:
        result = graph.invoke({
            "messages": [{"role": "user", "content": question}],
            "question": question,
            "sql": None, "result": None,
            "error": None, "attempts": 0
        })
        sql_gerado = result.get("sql", "")
        resposta   = result.get("result", "") if needs_prose else ""
    except Exception as e:
        # Um 429 diz que o orçamento acabou, não que o agente errou. Contar isso
        # como reprovação afundou a accuracy das rodadas anteriores (4.7%, 23.8%,
        # 33.3%) — os números mediam o free tier da Groq, não o text-to-SQL.
        if _is_rate_limit(e):
            print(f"  ⏭️  SEM ORÇAMENTO — pergunta não avaliada")
            return {"id": qid, "difficulty": diff, "question": question,
                    "status": "skipped_rate_limit", "passed": False,
                    "skipped": True, "sql_gerado": "", "error": str(e)}
        print(f"  ❌ ERRO no agente: {e}")
        return {"id": qid, "difficulty": diff, "question": question,
                "status": "agent_error", "passed": False,
                "sql_gerado": "", "error": str(e)}

    print(f"  SQL: {sql_gerado[:100]}{'...' if len(sql_gerado) > 100 else ''}")

    # ── eixos estáticos: valem para toda pergunta, inclusive as de regra 11 ──
    estatico = static_checks(sql_gerado, catalogo) if sql_gerado else {}
    for eixo, veredito in estatico.items():
        if veredito != "ok":
            print(f"  ⚠️  {eixo}: {veredito}")

    base = {"id": qid, "difficulty": diff, "question": question,
            "sql_gerado": sql_gerado, "checks": estatico}

    # Regra 11 — a prosa é julgada à parte (judge.py); aqui só se registra.
    # A resposta vai inteira, não truncada: a geração custa Groq, a pontuação
    # não. Guardar o texto completo deixa reavaliar a prosa sem regerar nada.
    if behavior == "regra_11_dados_insuficientes":
        passed = check_regra11(resposta)
        print(f"  {'✅' if passed else '❌'} Regra 11 (keyword) — "
              f"{'detectada' if passed else 'NÃO detectada'}")
        return {**base, "status": "regra11_ok" if passed else "regra11_fail",
                "passed": passed, "resposta": resposta}

    # ── correção do resultado ──
    refs = [RESULTS_DIR / f"{qid}.parquet"]
    refs += sorted(RESULTS_DIR.glob(f"{qid}_alt*.parquet"))
    refs = [p for p in refs if p.exists()]
    if not refs:
        print(f"  ⚠️  Parquet não encontrado")
        return {**base, "status": "ref_missing", "passed": False}

    try:
        df_agent = conn.execute(sql_gerado).df()
    except Exception as e:
        print(f"  ❌ SQL falhou: {e}")
        return {**base, "status": "sql_error", "passed": False, "error": str(e)}

    # Acertar QUALQUER referência conta: quando a pergunta admite mais de uma
    # resposta correta, gold único vira reprovação arbitrária.
    motivo = ""
    passed = False
    for ref_path in refs:
        df_ref = pd.read_parquet(ref_path)
        ok, por_que = compare(df_ref, df_agent, order_matters, compare_mode,
                              q.get("optional_columns"))
        if ok:
            passed, motivo = True, f"{por_que} [{ref_path.stem}]"
            break
        if not motivo:
            motivo = por_que
    print(f"  {'✅' if passed else '❌'} agente:{len(df_agent)}L — {motivo}")
    return {**base, "status": "pass" if passed else "fail", "passed": passed,
            "rows_agent": len(df_agent), "motivo": motivo,
            "order_matters": order_matters, "compare_mode": compare_mode}


def main():
    with open(DATASET_PATH, encoding="utf-8") as f:
        dataset = json.load(f)

    fingerprint = compute_fingerprint()
    resultados_anteriores, fingerprint_anterior = load_previous_results()
    mudou_algo = fingerprint_anterior is not None and fingerprint_anterior != fingerprint

    conn     = duckdb.connect(str(DB_PATH), read_only=True)
    catalogo = carregar_catalogo(conn)
    results  = []
    reaproveitadas = []

    # Delta de hits nesta rodada = quantas chamadas de LLM foram evitadas pelo
    # cache exact-match (query_cache.py) — relevante sobretudo ao reexecutar o
    # harness várias vezes iterando em prompt.py, quando o gold dataset não muda.
    cache_hits_antes = query_cache.stats()["total_hits"]

    for i, q in enumerate(dataset["questions"]):
        qid = q["id"]
        anterior = resultados_anteriores.get(qid)

        # Só pula quem já passou E nada mudou desde então (ver FINGERPRINT_FILES).
        # Falha, erro e "sem orçamento" retestam sempre — é exatamente o que
        # não deve ficar pra trás numa retomada.
        if (not mudou_algo and anterior is not None
                and anterior.get("passed") and not anterior.get("skipped")):
            print(f"\n{'─'*60}\n[{qid}] {q['question']}"
                  f"\n  ↩️  já validado numa rodada anterior, sem mudança no "
                  f"prompt/comparador/gold — pulando (0 tokens)")
            r = {**anterior, "reused_from_previous_run": True}
            results.append(r)
            reaproveitadas.append(r)
            continue

        r = run_eval(q, conn, catalogo)
        results.append(r)
        if i < len(dataset["questions"]) - 1:
            print(f"  ⏳ aguardando {DELAY_SECONDS}s...")
            time.sleep(DELAY_SECONDS)

    conn.close()

    cache_stats = query_cache.stats()
    cache_hits_nesta_rodada = cache_stats["total_hits"] - cache_hits_antes

    evaluated = [r for r in results if not r.get("skipped")]
    skipped   = [r for r in results if r.get("skipped")]
    total     = len(evaluated)
    passed    = sum(1 for r in evaluated if r["passed"])
    by_diff = {}
    for r in evaluated:
        d = r["difficulty"]
        by_diff.setdefault(d, {"total": 0, "passed": 0})
        by_diff[d]["total"] += 1
        if r["passed"]:
            by_diff[d]["passed"] += 1

    # Eixos independentes, não um gate único: um número agregado esconde qual
    # dimensão quebrou — foi assim que "33%" passou por accuracy quando na
    # verdade metade das perguntas não tinha sido avaliada.
    def taxa(eixo):
        vistos = [r for r in evaluated if r.get("checks", {}).get(eixo)]
        if not vistos:
            return None
        ok = sum(1 for r in vistos if r["checks"][eixo] == "ok")
        return {"ok": ok, "total": len(vistos), "taxa": round(ok / len(vistos), 4)}

    metricas = {
        "execution_accuracy": {
            "passed": passed, "total": total,
            "taxa": round(passed / total, 4) if total else None,
        },
        "validade_sintatica": taxa("sintaxe"),
        "uso_de_schema":      taxa("schema"),
        "seguranca":          taxa("seguranca"),
        "eficiencia":         taxa("eficiencia"),
    }

    report = {
        "run_at": datetime.now().isoformat(),
        "dataset_version": dataset.get("version"),
        "prompt_fingerprint": fingerprint,
        "total": total, "passed": passed,
        "skipped": len(skipped),
        "skipped_ids": [r["id"] for r in skipped],
        "complete": len(skipped) == 0,
        "accuracy": round(passed / total, 4) if total else None,
        "metricas": metricas,
        "cache": {
            "hits_nesta_rodada": cache_hits_nesta_rodada,
            "perguntas_guardadas_no_total": cache_stats["entries"],
        },
        "by_difficulty": by_diff,
        "details": results
    }

    report_path = REPORTS_DIR / f"eval_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print(f"\n{'═'*60}")
    if total:
        print(f"  EXECUTION ACCURACY: {passed}/{total} = {report['accuracy']*100:.1f}%")
    else:
        print(f"  SEM ACCURACY — nenhuma pergunta avaliada")
    print(f"{'─'*60}")
    for nome, m in metricas.items():
        if nome == "execution_accuracy" or not m:
            continue
        print(f"  {nome:20} {m['ok']}/{m['total']} ({m['taxa']*100:.0f}%)")
    if skipped:
        print(f"  ⚠️  PARCIAL — {len(skipped)}/{len(results)} sem orçamento: "
              f"{', '.join(r['id'] for r in skipped)}")
        print(f"     A accuracy acima cobre só as {total} avaliadas.")
    if cache_hits_nesta_rodada:
        print(f"  💾 CACHE: {cache_hits_nesta_rodada} chamada(s) de LLM evitada(s) "
              f"nesta rodada ({cache_stats['entries']} perguntas guardadas no total)")
    if reaproveitadas:
        print(f"  ↩️  RETOMADA: {len(reaproveitadas)} pergunta(s) já validada(s) antes, "
              f"reaproveitada(s) sem chamar o agente: "
              f"{', '.join(sorted(r['id'] for r in reaproveitadas))}")
    elif mudou_algo:
        print(f"  🔄 prompt.py, checks.py ou gold_dataset.json mudaram desde a "
              f"última rodada — nada foi reaproveitado, tudo retestado do zero.")
    print(f"{'═'*60}")
    for d, m in sorted(by_diff.items()):
        pct = m['passed'] / m['total'] * 100
        bar = "█" * m['passed'] + "░" * (m['total'] - m['passed'])
        print(f"  {d:20} {bar}  {m['passed']}/{m['total']} ({pct:.0f}%)")
    print(f"\n  Relatório: {report_path.name}")
    print(f"{'═'*60}")

if __name__ == "__main__":
    main()
