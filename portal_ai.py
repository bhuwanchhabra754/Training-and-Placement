import os
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.engine import URL

from langchain_community.utilities import SQLDatabase
from langchain_community.agent_toolkits import create_sql_agent
from langchain_groq import ChatGroq

load_dotenv()

def get_ai_agent():
    llm = ChatGroq(
        model="llama-3.1-8b-instant",
        api_key=os.getenv("GROQ_API_KEY"),
        temperature=0.2
    )

    url = URL.create(
        drivername="mysql+pymysql",
        username=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        host=os.getenv("DB_HOST", "localhost"),
        database=os.getenv("DB_NAME", "training_portal_v2"),
    )
    engine = create_engine(url)
    db = SQLDatabase(engine)

    # ✅ Tool calling agent (BEST for Gemini)
    agent_executor = create_sql_agent(
        llm=llm,
        db=db,
        verbose=True,
        handle_parsing_errors=True
    )
    return agent_executor

agent = get_ai_agent()

def AI(question: str) -> str:
    prompt = f"""
You are an AI assistant for a Training & Placement portal.
Answer user questions using the MySQL database.
Do NOT show SQL queries in the final answer.

Question: {question}
"""
    # ✅ Must use invoke instead of run
    result = agent.invoke({"input": prompt})
    return result["output"]

if __name__ == "__main__":
    print(AI("List me the all tutors Names with Sections"))
