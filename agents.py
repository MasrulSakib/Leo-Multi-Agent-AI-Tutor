import os

from crewai import Agent, LLM

from prompts import PROMPTS


def get_llm():
    return LLM(
        model=os.getenv("MODEL_NAME", "openai/gpt-oss-120b"),
        base_url=os.getenv("BASE_URL", "https://api.groq.com/openai/v1"),
        api_key=os.getenv("API_KEY"),
        temperature=0.3,
    )


def build_agent(role_key, llm):
    prompt = PROMPTS[role_key]
    return Agent(
        role=prompt["role"],
        goal=prompt["goal"],
        backstory=prompt["backstory"],
        llm=llm,
        allow_delegation=False,
        max_iter=3,
        verbose=False,
    )
