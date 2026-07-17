import os
import time
import uuid
import random
import sqlite3
import argparse
import duckdb
from pathlib import Path
from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages
from langgraph.checkpoint.sqlite import SqliteSaver
from langchain_core.messages import AIMessage
from langchain_groq import ChatGroq
from typing import TypedDict, Optional, Annotated
from prompt import SYSTEM_PROMPT, RESPONSE_PROMPT

MAX_RESULT_ROWS = 50
MAX_LLM_RETRIES = 5
MAX_HISTORY_TURNS = 3

# Acima disto o 429 é o limite diário, não o por minuto: esperar não adianta
# dentro de uma rodada, então falha na hora e deixa quem chamou decidir.
MAX_RATE_LIMIT_WAIT = 120.0

class AgentState(TypedDict):
    # A conversa em si. O checkpoint guarda esta lista inteira por thread; é ela
    # que sobrevive ao restart. Os demais campos são de trabalho, válidos por turno.
    messages: Annotated[list, add_messages]
    question: str
    sql: Optional[str]
    result: Optional[str]
    error: Optional[str]
    attempts: int

DB_PATH = "/home/wsl/nutriquery/db/nutriquery.duckdb"
CHECKPOINT_PATH = Path(__file__).parent / "db" / "checkpoints.sqlite"

llm = ChatGroq(
    model="llama-3.3-70b-versatile",
    temperature=0,
    api_key=os.environ["GROQ_API_KEY"]
)

def _is_rate_limit(exc: Exception) -> bool:
    if getattr(exc, "status_code", None) == 429:
        return True
    msg = str(exc).lower()
    return "429" in msg or "rate limit" in msg


def _retry_after(exc: Exception) -> Optional[float]:
    """Groq devolve o tempo de espera sugerido no corpo do erro 429.

    O formato varia com o limite atingido: o de tokens por minuto vem como
    `8.412s`, o de tokens por dia como `27m23.328s`. Ler só os segundos faria
    o backoff esperar 23s por uma janela que só abre em 27 minutos.
    """
    import re
    m = re.search(
        r"try again in (?:([\d.]+)h)?(?:([\d.]+)m)?(?:([\d.]+)s)?",
        str(exc), re.IGNORECASE
    )
    if not m or not any(m.groups()):
        return None
    h, mi, s = (float(g) if g else 0.0 for g in m.groups())
    return h * 3600 + mi * 60 + s


def invoke_llm(messages: list):
    """llm.invoke com backoff exponencial em 429 — o free tier da Groq
    derruba rodadas inteiras de eval sem isso."""
    delay = 2.0
    for attempt in range(MAX_LLM_RETRIES):
        try:
            return llm.invoke(messages)
        except Exception as e:
            if not _is_rate_limit(e) or attempt == MAX_LLM_RETRIES - 1:
                raise
            wait = _retry_after(e) or delay
            if wait > MAX_RATE_LIMIT_WAIT:
                raise
            wait += random.uniform(0, 0.5)  # jitter
            print(f"  ⏳ rate limit — aguardando {wait:.1f}s (tentativa {attempt + 1}/{MAX_LLM_RETRIES})")
            time.sleep(wait)
            delay = min(delay * 2, 60)


def _initial_state(question: str) -> dict:
    """Entrada de um turno.

    Os campos de trabalho são zerados explicitamente: com checkpointer o state
    do turno anterior persiste na thread, e `error` ainda setado faria
    `generate_sql` entrar no ramo de correção numa pergunta nova, enquanto
    `attempts` acumulado mandaria `check_result` direto para "fail".
    `messages` não é zerado — tem reducer, então a pergunta é anexada ao histórico.
    """
    return {
        "messages": [{"role": "user", "content": question}],
        "question": question,
        "sql": None,
        "result": None,
        "error": None,
        "attempts": 0,
    }


def _render_history(messages: list) -> str:
    linhas = []
    for m in messages:
        role = getattr(m, "type", None) or m.get("role")
        content = getattr(m, "content", None) or m.get("content")
        if role in ("human", "user"):
            linhas.append(f"Usuário: {content}")
            continue
        # O SQL viaja junto da resposta que ele produziu: é o registro exato dos
        # filtros que atenderam à pergunta, e é o que permite a um follow-up herdar
        # qualificadores ("grelhado", "cru") que a prosa não delimita sem ambiguidade.
        sql = (getattr(m, "additional_kwargs", None) or {}).get("sql")
        if sql:
            linhas.append(f"SQL usado: {' '.join(sql.split())}")
        linhas.append(f"NutriQuery: {content}")
    return "\n".join(linhas)


def generate_sql(state: AgentState) -> dict:
    question = state["question"]
    error = state.get("error")

    # Janela deslizante: o checkpoint guarda a conversa inteira, mas só os
    # últimos turnos entram no prompt — histórico ilimitado estoura o contexto.
    prior = state.get("messages", [])[:-1][-(MAX_HISTORY_TURNS * 2):]

    partes = []
    if prior:
        # O histórico vai como texto dentro de UMA mensagem de usuário, e não como
        # replay das mensagens cruas: o SYSTEM_PROMPT é few-shot de SQL puro, e
        # turnos de assistente em prosa ensinariam o modelo a responder prosa aqui.
        partes.append(
            'Histórico da conversa. Use-o para resolver referências como "e de gordura?" ou '
            '"e o cru?": quando a pergunta nova NÃO nomear um alimento, reaproveite o filtro '
            "de alimento do SQL anterior e troque só o que ela pedir — se o SQL anterior "
            "filtrava '%frango%grelhado%', um follow-up sobre gordura mantém "
            "'%frango%grelhado%' e muda apenas o nutriente. Quando a pergunta nova nomear "
            "um alimento próprio, ignore o filtro anterior e trate-a como pergunta nova.\n"
            f"{_render_history(prior)}\n"
        )
    partes.append(f"Pergunta: {question}")
    if error:
        partes.append(f"\nSQL anterior gerou este erro: {error}\n\nGere um novo SQL corrigido.")

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": "\n".join(partes)}
    ]
    response = invoke_llm(messages)
    sql = response.content.strip()
    if sql.startswith("```"):
        lines = sql.split("\n")
        sql = "\n".join(lines[1:-1]).strip()
    return {"sql": sql, "error": None}

def execute_sql(state: AgentState) -> dict:
    sql = state["sql"]
    try:
        conn = duckdb.connect(DB_PATH, read_only=True)
        result = conn.execute(sql).df()
        conn.close()
        total_rows = len(result)
        if total_rows > MAX_RESULT_ROWS:
            result_str = result.head(MAX_RESULT_ROWS).to_string(index=False)
            result_str += f"\n... (mostrando {MAX_RESULT_ROWS} de {total_rows} resultados — refine sua busca para ver todos)"
        else:
            result_str = result.to_string(index=False)
        return {"result": result_str, "error": None}
    except Exception as e:
        return {"result": None, "error": str(e)}

def respond(state: AgentState) -> dict:
    question = state["question"]
    result = state["result"]
    sql = state["sql"]
    messages = [
        {"role": "system", "content": RESPONSE_PROMPT},
        {"role": "user", "content": f"""Pergunta: {question}\n\nSQL executado:\n{sql}\n\nResultado:\n{result}\n\nResponda ao usuário em português de forma clara, informando os valores com unidades e sempre mencionando que os valores são por 100g do alimento."""}
    ]
    response = invoke_llm(messages)
    # A resposta em prosa é o turno do assistente na conversa — anexá-la aqui é o
    # que dá contexto ao `generate_sql` do próximo turno. O SQL vai em
    # additional_kwargs para não haver duas listas paralelas a manter em sincronia.
    return {
        "result": response.content,
        "messages": [AIMessage(content=response.content, additional_kwargs={"sql": sql})],
    }

def check_result(state: AgentState) -> str:
    if state.get("error") and state["attempts"] < 3:
        return "retry"
    elif state.get("error"):
        return "fail"
    return "respond"

def increment_attempts(state: AgentState) -> dict:
    return {"attempts": state["attempts"] + 1}

def _build_graph(with_respond: bool, checkpointer=None):
    graph = StateGraph(AgentState)
    graph.add_node("generate_sql", generate_sql)
    graph.add_node("execute_sql", execute_sql)
    graph.add_node("increment_attempts", increment_attempts)
    graph.set_entry_point("generate_sql")
    graph.add_edge("generate_sql", "execute_sql")
    if with_respond:
        graph.add_node("respond", respond)
        graph.add_conditional_edges("execute_sql", check_result, {
            "respond": "respond",
            "retry": "increment_attempts",
            "fail": "respond"
        })
        graph.add_edge("respond", END)
    else:
        graph.add_conditional_edges("execute_sql", check_result, {
            "respond": END,
            "retry": "increment_attempts",
            "fail": END
        })
    graph.add_edge("increment_attempts", "generate_sql")
    return graph.compile(checkpointer=checkpointer)


def _make_checkpointer() -> SqliteSaver:
    CHECKPOINT_PATH.parent.mkdir(parents=True, exist_ok=True)
    # check_same_thread=False: o LangGraph pode tocar o checkpointer de outra thread.
    conn = sqlite3.connect(CHECKPOINT_PATH, check_same_thread=False)
    return SqliteSaver(conn)


agent = _build_graph(with_respond=True, checkpointer=_make_checkpointer())

# Variantes sem checkpointer para o eval harness. Cada pergunta do gold dataset é
# independente — memória entre elas seria contaminação — e um grafo com checkpointer
# recusa invoke sem thread_id (ValueError).
agent_stateless = _build_graph(with_respond=True)

# Sem o nó `respond` — o eval de execution accuracy reexecuta o SQL por conta
# própria e descarta a resposta em prosa, então gerá-la é 1 chamada de LLM
# jogada fora por pergunta.
agent_sql_only = _build_graph(with_respond=False)


def ask(question: str, thread_id: str) -> dict:
    """Um turno de conversa na thread `thread_id`, com histórico e persistência."""
    return agent.invoke(_initial_state(question), {"configurable": {"thread_id": thread_id}})


def get_history(thread_id: str) -> list:
    """Mensagens já salvas nesta thread (vazio se a thread é nova)."""
    snapshot = agent.get_state({"configurable": {"thread_id": thread_id}})
    return snapshot.values.get("messages", []) if snapshot.values else []

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="NutriQuery — agente Text-to-SQL sobre a TACO")
    parser.add_argument("--thread", help="retoma uma conversa salva; omita para começar uma nova")
    args = parser.parse_args()

    thread_id = args.thread or f"cli-{uuid.uuid4().hex[:8]}"

    print("NutriQuery — Agente Text-to-SQL (Groq llama-3.3-70b)")
    print(f"Thread: {thread_id}")
    print(f"Para retomar esta conversa depois: python3 agent.py --thread {thread_id}")

    anteriores = get_history(thread_id)
    if anteriores:
        print(f"\n↩️  Conversa retomada — {len(anteriores)} mensagens salvas. Últimas:")
        for m in anteriores[-4:]:
            quem = "Você" if m.type == "human" else "NutriQuery"
            texto = m.content if len(m.content) <= 100 else m.content[:100] + "…"
            print(f"   {quem}: {texto}")

    print("\nDigite 'sair' para encerrar\n")
    while True:
        question = input("Pergunta: ").strip()
        if question.lower() == "sair":
            break
        result = ask(question, thread_id)
        print(f"\n📊 SQL gerado:\n{result['sql']}")
        print(f"\n💬 Resposta:\n{result['result']}\n")
        print("-" * 60)
