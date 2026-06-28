import os
import duckdb
from langgraph.graph import StateGraph, END
from langchain_groq import ChatGroq
from typing import TypedDict, Optional
from prompt import SYSTEM_PROMPT

class AgentState(TypedDict):
    question: str
    sql: Optional[str]
    result: Optional[str]
    error: Optional[str]
    attempts: int

DB_PATH = "/home/wsl/nutriquery/db/nutriquery.duckdb"

llm = ChatGroq(
    model="llama-3.3-70b-versatile",
    temperature=0,
    api_key=os.environ["GROQ_API_KEY"]
)

def generate_sql(state: AgentState) -> AgentState:
    question = state["question"]
    error = state.get("error")
    if error:
        user_message = f"""Pergunta: {question}\n\nSQL anterior gerou este erro: {error}\n\nGere um novo SQL corrigido."""
    else:
        user_message = f"Pergunta: {question}"
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_message}
    ]
    response = llm.invoke(messages)
    sql = response.content.strip()
    if sql.startswith("```"):
        lines = sql.split("\n")
        sql = "\n".join(lines[1:-1]).strip()
    return {**state, "sql": sql, "error": None}

def execute_sql(state: AgentState) -> AgentState:
    sql = state["sql"]
    try:
        conn = duckdb.connect(DB_PATH, read_only=True)
        result = conn.execute(sql).df()
        conn.close()
        return {**state, "result": result.to_string(index=False), "error": None}
    except Exception as e:
        return {**state, "result": None, "error": str(e)}

def respond(state: AgentState) -> AgentState:
    question = state["question"]
    result = state["result"]
    sql = state["sql"]
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"""Pergunta: {question}\n\nSQL executado:\n{sql}\n\nResultado:\n{result}\n\nResponda ao usuário em português de forma clara, informando os valores com unidades e sempre mencionando que os valores são por 100g do alimento."""}
    ]
    response = llm.invoke(messages)
    return {**state, "result": response.content}

def check_result(state: AgentState) -> str:
    if state.get("error") and state["attempts"] < 3:
        return "retry"
    elif state.get("error"):
        return "fail"
    return "respond"

def increment_attempts(state: AgentState) -> AgentState:
    return {**state, "attempts": state["attempts"] + 1}

graph = StateGraph(AgentState)
graph.add_node("generate_sql", generate_sql)
graph.add_node("execute_sql", execute_sql)
graph.add_node("respond", respond)
graph.add_node("increment_attempts", increment_attempts)
graph.set_entry_point("generate_sql")
graph.add_edge("generate_sql", "execute_sql")
graph.add_conditional_edges("execute_sql", check_result, {
    "respond": "respond",
    "retry": "increment_attempts",
    "fail": "respond"
})
graph.add_edge("increment_attempts", "generate_sql")
graph.add_edge("respond", END)
agent = graph.compile()

if __name__ == "__main__":
    print("NutriQuery — Agente Text-to-SQL (Groq llama-3.3-70b)")
    print("Digite 'sair' para encerrar\n")
    while True:
        question = input("Pergunta: ").strip()
        if question.lower() == "sair":
            break
        result = agent.invoke({
            "question": question,
            "sql": None,
            "result": None,
            "error": None,
            "attempts": 0
        })
        print(f"\n📊 SQL gerado:\n{result['sql']}")
        print(f"\n💬 Resposta:\n{result['result']}\n")
        print("-" * 60)
