import os
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.engine import URL

from langchain_community.utilities import SQLDatabase
from langchain_community.agent_toolkits import create_sql_agent
from langchain_groq import ChatGroq


# ✅ Load .env only for local development
# On Railway, variables come from Railway Dashboard → Variables
load_dotenv()


def get_ai_agent():
    """Creates and returns LangChain SQL Agent."""
    groq_api_key = os.getenv("GROQ_API_KEY")
    if not groq_api_key:
        raise ValueError("GROQ_API_KEY is missing. Add it in Railway Variables.")

    # ✅ Groq LLM
    llm = ChatGroq(
        model="llama-3.1-8b-instant",
        api_key=groq_api_key,
        temperature=0.2
    )

    # ✅ DB Env Variables
    db_user = os.getenv("DB_USER")
    db_password = os.getenv("DB_PASSWORD")
    db_host = os.getenv("DB_HOST")
    db_port = os.getenv("DB_PORT", "3306")
    db_name = os.getenv("DB_NAME")

    # Validate DB variables
    missing = []
    if not db_user: missing.append("DB_USER")
    if not db_password: missing.append("DB_PASSWORD")
    if not db_host: missing.append("DB_HOST")
    if not db_name: missing.append("DB_NAME")

    if missing:
        raise ValueError(f"Missing DB env variables: {', '.join(missing)}. Add them in Railway Variables.")

    # ✅ SQLAlchemy URL with port
    url = URL.create(
        drivername="mysql+pymysql",
        username=db_user,
        password=db_password,
        host=db_host,
        port=int(db_port),
        database=db_name,
    )

    engine = create_engine(
        url,
        pool_pre_ping=True,   # ✅ avoids stale connection issues
        pool_recycle=280,     # ✅ helps Railway connection stability
    )

    db = SQLDatabase(engine)

    # ✅ SQL Agent
    agent_executor = create_sql_agent(
        llm=llm,
        db=db,
        verbose=True,
        handle_parsing_errors=True
    )

    return agent_executor


# ✅ Lazy-loaded global agent (Railway safe)
_AGENT = None


def get_agent():
    """Create agent only when required (prevents Railway crash at startup)."""
    global _AGENT
    if _AGENT is None:
        _AGENT = get_ai_agent()
    return _AGENT


def AI(question: str) -> str:
    """Main function called by Flask route."""
    prompt = f"""
You are an AI assistant for a Training & Placement portal.
Answer user questions using the MySQL database.
Do NOT show SQL queries in the final answer.

Question: {question}
"""

    try:
        agent = get_agent()
        result = agent.invoke({"input": prompt})
        return result.get("output", "No output returned.")
    except Exception as e:
        # ✅ return readable error rather than crashing whole app
        return f"AI Error: {str(e)}"


if __name__ == "__main__":
    print(AI("List me all tutors names with sections"))
