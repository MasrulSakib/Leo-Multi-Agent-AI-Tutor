import os
import sys

from dotenv import load_dotenv

load_dotenv()
os.environ.setdefault("OTEL_SDK_DISABLED", "true")

from crewai import Crew, Process

from agents import build_agent, get_llm
from memory import get_student, load_memory, notes_for_prompt, remember_session, save_memory
from models import Evaluation, Plan, Quiz
from tasks import (evaluate_task, explain_task, followup_task, plan_task,
                   quiz_task, reteach_task, wrapup_task)

MAX_ROUNDS = 2
PASS_MARK = 0.6
NUM_QUESTIONS = "3"

COLORS = {
    "Coordinator": "\033[95m",
    "Explainer": "\033[94m",
    "Quiz Master": "\033[93m",
    "Evaluator": "\033[92m",
}
RESET = "\033[0m"


def say(agent_name, text):
    print(f"\n{COLORS[agent_name]}[{agent_name}]{RESET} {text}")


def handoff(from_agent, to_agent, what):
    print(f"\n  >> {from_agent} hands {what} to {to_agent}")


def ask(prompt):
    answer = input(prompt).strip()
    if answer.lower() in ("quit", "exit"):
        print("\nBye! See you next time.")
        sys.exit(0)
    return answer


def run_crew(agents, tasks, inputs, tries=2):
    for attempt in range(1, tries + 1):
        try:
            crew = Crew(agents=agents, tasks=tasks, process=Process.sequential, verbose=False)
            return crew.kickoff(inputs=inputs)
        except Exception as error:
            say("Coordinator", f"Something went wrong (try {attempt} of {tries}): {error}")
    return None


def get_data(result, model):
    if result is None:
        return None
    if result.pydantic:
        return result.pydantic
    raw = result.raw
    start, end = raw.find("{"), raw.rfind("}")
    try:
        return model.model_validate_json(raw[start:end + 1])
    except Exception:
        return None


def quiz_to_text(quiz):
    lines = []
    for number, item in enumerate(quiz.questions, 1):
        lines.append(f"Q{number}: {item.question}\nIdeal answer: {item.ideal_answer}")
    return "\n\n".join(lines)


def get_plan(coordinator, base):
    request = ask("What do you want to learn today? ")
    for _ in range(3):
        say("Coordinator", "Looking at your request...")
        result = run_crew([coordinator], [plan_task(coordinator)], {**base, "request": request})
        plan = get_data(result, Plan)
        if plan and plan.clear:
            return plan
        question = plan.question_for_student if plan else "Sorry, I did not get that. Which topic do you want to study?"
        say("Coordinator", question)
        request = request + ". " + ask("> ")
    return None


def teach(explainer, inputs):
    say("Explainer", "Preparing your lesson...")
    result = run_crew([explainer], [explain_task(explainer)], inputs)
    if result is None:
        return None
    lesson = result.raw
    say("Explainer", "\n" + lesson)

    while True:
        question = ask("\nYour turn: press Enter to start the quiz, or type a question about the lesson: ")
        if not question:
            return lesson
        say("Explainer", "Thinking about your question...")
        extra = {**inputs, "lesson": lesson, "student_question": question}
        result = run_crew([explainer], [followup_task(explainer)], extra)
        if result is None:
            say("Coordinator", "The Explainer is stuck on that one, so let's move on to the quiz.")
            return lesson
        say("Explainer", result.raw)


def take_quiz(quiz):
    print(f"\nQuiz time: {quiz.topic}")
    answers = []
    for number, item in enumerate(quiz.questions, 1):
        print(f"\nQ{number}. {item.question}")
        answer = ask("Your answer: ") or "(no answer)"
        answers.append(f"A{number}: {answer}")
    return "\n".join(answers)


def quiz_rounds(agents, inputs):
    quiz_master, evaluator, explainer = agents["quiz_master"], agents["evaluator"], agents["explainer"]
    quiz_focus = ""
    correct, total, weak_points = 0, 0, []

    for round_number in range(1, MAX_ROUNDS + 1):
        handoff("Explainer", "Quiz Master", "the lesson")
        say("Quiz Master", "Writing your questions...")
        quiz_inputs = {**inputs, "num_questions": NUM_QUESTIONS, "quiz_focus": quiz_focus}
        result = run_crew([quiz_master], [quiz_task(quiz_master)], quiz_inputs)
        quiz = get_data(result, Quiz)
        if quiz is None or not quiz.questions:
            say("Coordinator", "The Quiz Master could not make a quiz this time. We will skip it.")
            break

        student_answers = take_quiz(quiz)

        handoff("Quiz Master", "Evaluator", "the questions and your answers")
        say("Evaluator", "Checking your answers...")
        eval_inputs = {**inputs, "quiz_text": quiz_to_text(quiz), "student_answers": student_answers}
        result = run_crew([evaluator], [evaluate_task(evaluator)], eval_inputs)
        evaluation = get_data(result, Evaluation)
        if evaluation is None:
            say("Coordinator", "The Evaluator could not mark the answers this time. We will skip it.")
            break

        correct = sum(1 for item in evaluation.feedback if item.correct)
        total = len(evaluation.feedback)
        weak_points = evaluation.weak_points
        for number, item in enumerate(evaluation.feedback, 1):
            mark = "Correct" if item.correct else "Needs work"
            print(f"  Q{number}: {mark} - {item.comment}")
        say("Evaluator", f"Score {correct}/{total}. {evaluation.summary}")

        passed = total > 0 and correct / total >= PASS_MARK
        if passed or not weak_points or round_number == MAX_ROUNDS:
            break

        handoff("Evaluator", "Explainer", "the weak points for re-teaching")
        say("Explainer", "Let me explain those parts again...")
        reteach_inputs = {**inputs, "weak_points": ", ".join(weak_points), "evaluator_notes": evaluation.summary}
        result = run_crew([explainer], [reteach_task(explainer)], reteach_inputs)
        if result is None:
            say("Coordinator", "The Explainer is stuck, so we will stop the quiz here.")
            break
        say("Explainer", "\n" + result.raw)
        inputs = {**inputs, "lesson": inputs["lesson"] + "\n\n" + result.raw}
        quiz_focus = "Focus only on these weak points: " + ", ".join(weak_points)
        ask("\nPress Enter for a short second quiz on those parts...")

    return correct, total, weak_points


def main():
    memory = load_memory()
    print("Hi, I'm Leo, your study assistant. Type 'quit' at any prompt to leave.")

    name = ask("What is your name? ") or "Student"
    student = get_student(memory, name)
    if student["sessions"]:
        print(f"Welcome back, {student['name']}! Last time you studied {student['sessions'][-1]['topic']}.")

    default_level = student["level"] or "beginner"
    level = ask(f"Your level (beginner/intermediate/advanced) [{default_level}]: ") or default_level
    student["level"] = level

    llm = get_llm()
    agents = {
        "coordinator": build_agent("coordinator", llm),
        "explainer": build_agent("explainer", llm),
        "quiz_master": build_agent("quiz_master", llm),
        "evaluator": build_agent("evaluator", llm),
    }
    base = {"student_name": student["name"], "level": level, "memory_notes": notes_for_prompt(student)}

    plan = get_plan(agents["coordinator"], base)
    if plan is None:
        say("Coordinator", "I still could not understand the topic. Please try again with a specific topic.")
        return

    handoff("Coordinator", "Explainer", "the study plan")
    inputs = {**base, "topic": plan.topic, "key_points": "; ".join(plan.key_points)}
    lesson = teach(agents["explainer"], inputs)
    if lesson is None:
        say("Coordinator", "The Explainer is stuck right now. Please try again in a minute.")
        return

    inputs["lesson"] = lesson
    correct, total, weak_points = quiz_rounds(agents, inputs)

    final_score = f"{correct}/{total}" if total else "quiz not taken"
    wrap_inputs = {**inputs, "final_score": final_score, "weak_points": ", ".join(weak_points) or "none"}
    result = run_crew([agents["coordinator"]], [wrapup_task(agents["coordinator"])], wrap_inputs)
    say("Coordinator", result.raw if result else "Good work today. See you next time!")

    remember_session(student, plan.topic, final_score, weak_points)
    save_memory(memory)


if __name__ == "__main__":
    main()
