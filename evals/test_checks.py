"""
test_checks.py — testa o ORÁCULO, não o agente. Zero LLM, zero token.

O eval anterior aprovava um SQL que ignora a pergunta em 15/16 casos. Um
comparador sem teste é um comparador que mente com confiança, então o baseline
degenerado abaixo é regressão permanente: se ele voltar a passar, o oráculo
quebrou de novo.

    python evals/test_checks.py
"""

import sys, os
import duckdb
import pandas as pd
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))
from checks import compare_exact, compare_subset, static_checks, carregar_catalogo

DB = Path(__file__).parent.parent / "db" / "nutriquery.duckdb"

falhas = []


def check(nome, cond):
    print(f"  {'✅' if cond else '❌'} {nome}")
    if not cond:
        falhas.append(nome)


def main():
    conn = duckdb.connect(str(DB), read_only=True)
    cat = carregar_catalogo(conn)

    gold = pd.DataFrame({
        "food_name": ["Frango, fígado, cru", "Carne, bovina, fígado, cru"],
        "value": [9.54, 5.626667],
    })

    print("\nComparador — o que DEVE passar")
    check("idêntico", compare_subset(gold, gold.copy(), False)[0])
    ordem_trocada = gold.iloc[::-1].reset_index(drop=True)
    check("linhas em outra ordem, ordem não importa",
          compare_subset(gold, ordem_trocada, False)[0])
    extra = gold.copy()
    extra["unit"] = ["mg", "mg"]
    check("agente devolve coluna 'unit' a mais (subset por coluna)",
          compare_subset(gold, extra, False)[0])
    quase = gold.copy()
    quase["value"] = [9.5401, 5.6266]
    check("float dentro da tolerância", compare_subset(gold, quase, False)[0])

    print("\nComparador — o que DEVE reprovar")
    check("linhas em outra ordem quando a ordem IMPORTA",
          not compare_subset(gold, ordem_trocada, True)[0])
    valor_errado = gold.copy()
    valor_errado["value"] = [1.0, 2.0]
    check("valores errados", not compare_subset(gold, valor_errado, False)[0])
    check("agente devolve vazio", not compare_subset(gold, gold.iloc[0:0], False)[0])
    faltando = gold.iloc[[0]].reset_index(drop=True)
    check("agente devolve menos linhas", not compare_subset(gold, faltando, False)[0])

    print("\nBASELINE DEGENERADO — a regressão que importa")
    dump = conn.execute("""
        SELECT f.food_name, fv.value, n.unit
        FROM fact_nutrient_values fv
        JOIN dim_food f ON fv.food_id = f.food_id
        JOIN dim_nutrient n ON fv.nutrient_id = n.nutrient_id
    """).df()
    print(f"  (dump sem WHERE: {len(dump)} linhas)")
    passou = []
    refs = sorted(Path(__file__).parent.joinpath("gold_results").glob("*.parquet"))
    for p in refs:
        ref = pd.read_parquet(p)
        if compare_subset(ref, dump, False)[0]:
            passou.append(p.stem)
    check(f"dump da tabela inteira reprova em TODAS as {len(refs)} perguntas "
          f"(passou em {len(passou)}: {passou or '-'})", not passou)

    vazio = dump.iloc[0:0]
    passou_vazio = [p.stem for p in refs
                    if compare_subset(pd.read_parquet(p), vazio, False)[0]]
    check(f"resultado vazio reprova em todas (passou em {len(passou_vazio)})",
          not passou_vazio)

    print("\nChecagens estáticas")
    ok = static_checks(
        "SELECT f.food_name FROM dim_food f WHERE f.food_name_normalized LIKE '%figado%'", cat)
    check("SQL válido passa em tudo", all(v == "ok" for v in ok.values()))

    alias = static_checks(
        "SELECT SUM(fv.value) AS total_calcio_mg FROM fact_nutrient_values fv", cat)
    check("alias de coluna NÃO é acusado de alucinação (bug do protótipo)",
          alias["schema"] == "ok")

    cte = static_checks("""
        WITH ranked_foods AS (
          SELECT f.food_name, ROW_NUMBER() OVER (ORDER BY fv.value DESC) AS row_num
          FROM fact_nutrient_values fv JOIN dim_food f ON fv.food_id = f.food_id
        ) SELECT food_name FROM ranked_foods WHERE row_num <= 5
    """, cat)
    check("CTE NÃO é acusada de tabela inexistente (bug do protótipo)",
          cte["schema"] == "ok")

    halluc = static_checks("SELECT vitamina_z_mg FROM dim_food", cat)
    check("coluna alucinada É detectada", halluc["schema"].startswith("alucinou"))

    bad = static_checks("SELECT * FROM naotem_essa_tabela", cat)
    check("tabela inexistente É detectada", bad["schema"].startswith("alucinou"))

    dml = static_checks("DROP TABLE dim_food", cat)
    check("DROP é bloqueado", dml["seguranca"] != "ok")

    cart = static_checks("SELECT * FROM dim_food f CROSS JOIN dim_nutrient n", cat)
    check("produto cartesiano é sinalizado", cart["eficiencia"] != "ok")

    sintaxe = static_checks("SELECT FROM WHERE", cat)
    check("SQL inválido é pego", sintaxe["sintaxe"] != "ok")

    conn.close()
    print(f"\n{'═'*60}")
    if falhas:
        print(f"  {len(falhas)} FALHA(S) no oráculo:")
        for f in falhas:
            print(f"    - {f}")
        sys.exit(1)
    print("  Oráculo íntegro — todas as checagens passaram")


if __name__ == "__main__":
    main()
