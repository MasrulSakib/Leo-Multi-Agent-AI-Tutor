from crewai import Task

from models import Evaluation, Plan, Quiz
from prompts import TASKS


def make_task(name, agent, output_model=None):
    return Task(
        description=TASKS[name]["description"],
        expected_output=TASKS[name]["expected_output"],
        agent=agent,
        output_pydantic=output_model,
    )


def plan_task(agent):
    return make_task("plan", agent, Plan)


def explain_task(agent):
    return make_task("explain", agent)


def followup_task(agent):
    return make_task("followup", agent)


def quiz_task(agent):
    return make_task("quiz", agent, Quiz)


def evaluate_task(agent):
    return make_task("evaluate", agent, Evaluation)


def reteach_task(agent):
    return make_task("reteach", agent)


def wrapup_task(agent):
    return make_task("wrapup", agent)
