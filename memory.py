import json
import os
from datetime import date

MEMORY_FILE = "student_memory.json"


def load_memory():
    if not os.path.exists(MEMORY_FILE):
        return {}
    try:
        with open(MEMORY_FILE, "r", encoding="utf-8") as file:
            return json.load(file)
    except (json.JSONDecodeError, OSError):
        return {}


def save_memory(memory):
    with open(MEMORY_FILE, "w", encoding="utf-8") as file:
        json.dump(memory, file, indent=2)


def get_student(memory, name):
    return memory.setdefault(name.lower(), {"name": name, "level": "", "sessions": []})


def notes_for_prompt(student):
    if not student["sessions"]:
        return "This is a new student with no history."
    parts = []
    for session in student["sessions"][-3:]:
        weak = ", ".join(session["weak_points"]) or "none"
        parts.append(f"{session['topic']} (score {session['score']}, weak points: {weak})")
    return "Recent sessions: " + "; ".join(parts)


def remember_session(student, topic, score, weak_points):
    student["sessions"].append({
        "date": str(date.today()),
        "topic": topic,
        "score": score,
        "weak_points": weak_points,
    })
