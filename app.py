import streamlit as st
from crewai import Crew, Process

from agents import build_agent, get_llm
from main import MAX_ROUNDS, NUM_QUESTIONS, PASS_MARK, get_data, quiz_to_text
from memory import get_student, load_memory, notes_for_prompt, remember_session, save_memory
from models import Evaluation, Plan, Quiz
from tasks import (evaluate_task, explain_task, followup_task, plan_task,
                   quiz_task, reteach_task, wrapup_task)

ICONS = {"Coordinator": "🟣", "Explainer": "🔵", "Quiz Master": "🟡", "Evaluator": "🟢"}
JOBS = {
    "Coordinator": "reads your request and plans",
    "Explainer": "teaches the topic",
    "Quiz Master": "writes practice questions",
    "Evaluator": "checks your answers",
}

st.set_page_config(page_title="Leo - AI Tutor", page_icon="🎓")
state = st.session_state


def init_state():
    defaults = {
        "stage": "setup", "log": [], "error": "", "chat": [], "attempts": 0,
        "request": "", "clarify": "", "round": 1, "quiz_focus": "", "reteach_text": "",
        "correct": 0, "total": 0, "weak_points": [], "goodbye": "",
    }
    for key, value in defaults.items():
        state.setdefault(key, value)


def note(text):
    state.log.append(text)


def show_error():
    if state.error:
        st.error(state.error)


def run_crew(agent, task, inputs, tries=2):
    error = ""
    for _ in range(tries):
        try:
            crew = Crew(agents=[agent], tasks=[task], process=Process.sequential, verbose=False)
            return crew.kickoff(inputs=inputs), ""
        except Exception as problem:
            error = str(problem)
    return None, error


def ask_agent(role_key, name, message, make_task, inputs):
    agent = state.agents[role_key]
    with st.spinner(f"{ICONS[name]} {name} {message}"):
        result, error = run_crew(agent, make_task(agent), inputs)
    if result is not None:
        note(f"{ICONS[name]} {name} finished")
    return result, error


def agent_message(name, text):
    with st.chat_message("assistant", avatar=ICONS[name]):
        st.markdown(f"**{name}**\n\n{text}")


def sidebar():
    st.sidebar.header("Leo's agents")
    for name, job in JOBS.items():
        st.sidebar.markdown(f"{ICONS[name]} **{name}**: {job}")
    st.sidebar.header("Activity")
    for line in reversed(state.log[-15:]):
        st.sidebar.write(line)


def setup_stage():
    with st.form("setup"):
        name = st.text_input("Your name")
        level = st.selectbox("Your level", ["beginner", "intermediate", "advanced"])
        start = st.form_submit_button("Start")
    if not start:
        return
    if not name.strip():
        st.warning("Please enter your name.")
        return
    memory = load_memory()
    student = get_student(memory, name.strip())
    student["level"] = level
    try:
        llm = get_llm()
        state.agents = {key: build_agent(key, llm) for key in ("coordinator", "explainer", "quiz_master", "evaluator")}
    except Exception as problem:
        st.error(f"Could not start the agents. Check your .env file. Details: {problem}")
        return
    state.memory = memory
    state.student = student
    state.base = {"student_name": student["name"], "level": level, "memory_notes": notes_for_prompt(student)}
    state.welcome = ""
    if student["sessions"]:
        state.welcome = f"Welcome back, {student['name']}! Last time you studied {student['sessions'][-1]['topic']}."
    state.stage = "topic"
    st.rerun()


def topic_stage():
    show_error()
    if state.welcome:
        st.info(state.welcome)
    if state.clarify:
        agent_message("Coordinator", state.clarify)
    label = "Your answer" if state.clarify else "What do you want to learn today?"
    with st.form("topic"):
        text = st.text_area(label, height=100)
        go = st.form_submit_button("Send to Leo")
    if not go or not text.strip():
        return

    state.error = ""
    state.request = (state.request + ". " + text.strip()) if state.request else text.strip()
    result, error = ask_agent("coordinator", "Coordinator", "is reading your request...", plan_task,
                              {**state.base, "request": state.request})
    if result is None:
        state.error = f"The Coordinator ran into a problem: {error}"
        st.rerun()

    plan = get_data(result, Plan)
    state.attempts += 1
    if plan is None or not plan.clear:
        if state.attempts >= 3:
            state.error = "The Coordinator still could not understand the topic. Please try a specific topic."
            state.request, state.clarify, state.attempts = "", "", 0
        else:
            state.clarify = plan.question_for_student if plan else "Sorry, I did not get that. Which topic do you want to study?"
        st.rerun()

    state.plan = plan
    state.request, state.clarify, state.attempts = "", "", 0
    state.inputs = {**state.base, "topic": plan.topic, "key_points": "; ".join(plan.key_points)}
    note("➡️ Coordinator hands the study plan to Explainer")
    result, error = ask_agent("explainer", "Explainer", "is preparing your lesson...", explain_task, state.inputs)
    if result is None:
        state.error = f"The Explainer is stuck right now: {error}. Please try again."
        st.rerun()
    state.lesson = result.raw
    state.inputs["lesson"] = result.raw
    state.stage = "lesson"
    st.rerun()


def make_quiz():
    note("➡️ Explainer hands the lesson to Quiz Master")
    inputs = {**state.inputs, "num_questions": NUM_QUESTIONS, "quiz_focus": state.quiz_focus}
    result, error = ask_agent("quiz_master", "Quiz Master", "is writing your questions...", quiz_task, inputs)
    quiz = get_data(result, Quiz)
    if quiz is None or not quiz.questions:
        state.error = f"The Quiz Master could not make a quiz this time. {error}"
        return False
    state.quiz = quiz
    state.stage = "quiz"
    return True


def finish():
    final_score = f"{state.correct}/{state.total}" if state.total else "quiz not taken"
    inputs = {**state.inputs, "final_score": final_score, "weak_points": ", ".join(state.weak_points) or "none"}
    result, error = ask_agent("coordinator", "Coordinator", "is wrapping up...", wrapup_task, inputs)
    state.goodbye = result.raw if result else "Good work today. See you next time!"
    state.final_score = final_score
    remember_session(state.student, state.plan.topic, final_score, state.weak_points)
    save_memory(state.memory)
    state.stage = "done"
    st.rerun()


def lesson_stage():
    show_error()
    st.subheader(f"Topic: {state.plan.topic}")
    agent_message("Explainer", state.lesson)
    for who, text in state.chat:
        if who == "student":
            with st.chat_message("user"):
                st.markdown(text)
        else:
            agent_message("Explainer", text)

    with st.form("followup", clear_on_submit=True):
        question = st.text_area("Ask the Explainer a question about the lesson (optional)", height=80)
        ask_button = st.form_submit_button("Ask")
    if ask_button and question.strip():
        state.error = ""
        result, error = ask_agent("explainer", "Explainer", "is thinking about your question...", followup_task,
                                  {**state.inputs, "student_question": question.strip()})
        if result is None:
            state.error = f"The Explainer is stuck on that question: {error}. You can start the quiz instead."
        else:
            state.chat.append(("student", question.strip()))
            state.chat.append(("Explainer", result.raw))
        st.rerun()

    left, right = st.columns(2)
    if left.button("Start the quiz"):
        state.error = ""
        make_quiz()
        st.rerun()
    if right.button("Finish without a quiz"):
        finish()


def quiz_stage():
    show_error()
    if state.reteach_text:
        agent_message("Explainer", state.reteach_text)
    st.subheader(f"Quiz (round {state.round}): {state.quiz.topic}")
    with st.form(f"quiz_{state.round}"):
        answers = []
        for number, item in enumerate(state.quiz.questions, 1):
            answers.append(st.text_area(f"Q{number}. {item.question}", key=f"answer_{state.round}_{number}", height=120))
        submit = st.form_submit_button("Submit answers")
    if not submit:
        return

    state.error = ""
    student_answers = "\n\n".join(f"A{number}: {text.strip() or '(no answer)'}" for number, text in enumerate(answers, 1))
    note("➡️ Quiz Master hands the questions and your answers to Evaluator")
    result, error = ask_agent("evaluator", "Evaluator", "is checking your answers...", evaluate_task,
                              {**state.inputs, "quiz_text": quiz_to_text(state.quiz), "student_answers": student_answers})
    evaluation = get_data(result, Evaluation)
    if evaluation is None:
        state.error = f"The Evaluator could not mark the answers this time. {error} Press Submit to try again."
        st.rerun()
    state.evaluation = evaluation
    state.correct = sum(1 for item in evaluation.feedback if item.correct)
    state.total = len(evaluation.feedback)
    state.weak_points = evaluation.weak_points
    state.stage = "result"
    st.rerun()


def result_stage():
    show_error()
    evaluation = state.evaluation
    st.subheader(f"Score: {state.correct}/{state.total}")
    for number, item in enumerate(evaluation.feedback, 1):
        message = f"**Q{number}.** {item.comment}"
        if item.correct:
            st.success(message)
        else:
            st.warning(message)
    agent_message("Evaluator", evaluation.summary)

    passed = state.total > 0 and state.correct / state.total >= PASS_MARK
    if passed or not state.weak_points or state.round >= MAX_ROUNDS:
        if st.button("Finish session"):
            finish()
        return

    st.info("Weak points: " + ", ".join(state.weak_points))
    if st.button("Re-teach these parts and try a second quiz"):
        state.error = ""
        note("➡️ Evaluator hands the weak points to Explainer for re-teaching")
        inputs = {**state.inputs, "weak_points": ", ".join(state.weak_points), "evaluator_notes": evaluation.summary}
        result, error = ask_agent("explainer", "Explainer", "is explaining those parts again...", reteach_task, inputs)
        if result is None:
            state.error = f"The Explainer is stuck right now: {error}. You can finish the session instead."
            st.rerun()
        state.reteach_text = result.raw
        state.inputs["lesson"] = state.inputs["lesson"] + "\n\n" + result.raw
        state.quiz_focus = "Focus only on these weak points: " + ", ".join(state.weak_points)
        state.round += 1
        if not make_quiz():
            state.round -= 1
        st.rerun()
    if st.button("Finish session"):
        finish()


def done_stage():
    agent_message("Coordinator", state.goodbye)
    st.success(f"Final score: {state.final_score}")
    if st.button("Start a new session"):
        state.clear()
        st.rerun()


init_state()
st.title("🎓 Leo - Multi-Agent AI Tutor")
sidebar()
{"setup": setup_stage, "topic": topic_stage, "lesson": lesson_stage,
 "quiz": quiz_stage, "result": result_stage, "done": done_stage}[state.stage]()
