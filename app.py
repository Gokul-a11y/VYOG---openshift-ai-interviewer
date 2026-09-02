import os
import json
import random
from functools import wraps

from flask import (
    Flask,
    render_template,
    redirect,
    url_for,
    session,
    request,
    jsonify,
    flash,
)

from dotenv import load_dotenv
from werkzeug.middleware.proxy_fix import ProxyFix

# Google OAuth
from authlib.integrations.flask_client import OAuth


# ============================================================
# CONFIGURATION
# ============================================================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

load_dotenv(os.path.join(BASE_DIR, ".env"))

app = Flask(__name__)

# Render runs Flask behind an HTTPS reverse proxy. Trust the forwarded
# host/scheme so url_for(..., _external=True) generates the public URL.
app.wsgi_app = ProxyFix(
    app.wsgi_app,
    x_for=1,
    x_proto=1,
    x_host=1,
)

app.config["SECRET_KEY"] = os.getenv(
    "SECRET_KEY",
    "dev-secret-change-this"
)

app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

# Local development is HTTP, so this must be False.
app.config["SESSION_COOKIE_SECURE"] = (
    os.getenv("SESSION_COOKIE_SECURE", "false").lower() == "true"
)


# ============================================================
# GOOGLE OAUTH CONFIGURATION
# ============================================================

GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "").strip()
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "").strip()

# IMPORTANT:
# This must EXACTLY match Google Cloud Console.
GOOGLE_REDIRECT_URI = os.getenv(
    "GOOGLE_REDIRECT_URI",
    "http://127.0.0.1:5000/google/callback"
).strip()


oauth = OAuth(app)

google = None

if GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET:

    google = oauth.register(
        name="google",

        client_id=GOOGLE_CLIENT_ID,

        client_secret=GOOGLE_CLIENT_SECRET,

        server_metadata_url=(
            "https://accounts.google.com/"
            ".well-known/openid-configuration"
        ),

        client_kwargs={
            "scope": "openid email profile"
        },
    )


# ============================================================
# QUESTIONS
# ============================================================

QUESTIONS_FILE = os.path.join(
    BASE_DIR,
    "questions.json"
)


def load_questions():

    if not os.path.exists(QUESTIONS_FILE):

        print("WARNING: questions.json not found.")

        return []

    try:

        with open(
            QUESTIONS_FILE,
            "r",
            encoding="utf-8"
        ) as file:

            data = json.load(file)

        # Support either:
        # [
        #   {...}
        # ]
        #
        # or:
        # {
        #   "questions": [...]
        # }

        if isinstance(data, dict):

            questions = data.get(
                "questions",
                data.get("data", [])
            )

        else:

            questions = data

        if not isinstance(questions, list):

            return []

        return questions

    except Exception as exc:

        print(
            "Could not load questions.json:",
            repr(exc)
        )

        return []


QUESTIONS = load_questions()

print("=" * 60)
print(f"Questions loaded : {len(QUESTIONS)}")
print(
    "Google OAuth     :",
    "CONFIGURED" if google else "NOT CONFIGURED"
)
print(
    "Redirect URI     :",
    GOOGLE_REDIRECT_URI
)
print("=" * 60)


# ============================================================
# HELPER FUNCTIONS
# ============================================================

def current_user():

    return session.get("user")


def login_required(function):

    @wraps(function)
    def decorated(*args, **kwargs):

        if not session.get("user"):

            return redirect(
                url_for("index")
            )

        return function(*args, **kwargs)

    return decorated


def get_question(index):

    if not QUESTIONS:

        return None

    if index < 0 or index >= len(QUESTIONS):

        return None

    return QUESTIONS[index]


def normalize_question(question, index=0):

    """
    Makes different question.json structures easier
    for the templates to consume.
    """

    if not isinstance(question, dict):

        return {
            "id": index + 1,
            "question": str(question),
            "text": str(question),
            "category": "OpenShift",
            "options": [],
            "answer": "",
            "explanation": "",
        }

    text = (
        question.get("question")
        or question.get("text")
        or question.get("title")
        or question.get("prompt")
        or ""
    )

    options = (
        question.get("options")
        or question.get("choices")
        or question.get("answers")
        or []
    )

    correct = (
        question.get("answer")
        or question.get("correct_answer")
        or question.get("correct")
        or question.get("expected_answer")
        or ""
    )

    category = (
        question.get("category")
        or question.get("topic")
        or question.get("domain")
        or "OpenShift"
    )

    explanation = (
        question.get("explanation")
        or question.get("model_answer")
        or question.get("ideal_answer")
        or ""
    )

    return {
        **question,
        "id": question.get(
            "id",
            index + 1
        ),
        "question": text,
        "text": text,
        "category": category,
        "options": options,
        "answer": correct,
        "explanation": explanation,
    }


def calculate_score():
    answers = session.get("answers", {})
    active_indices = get_active_indices()

    total = len(active_indices)

    if total == 0:
        return 0

    correct = 0

    for original_index in active_indices:
        user_answer = answers.get(
            str(original_index),
            "",
        )

        question = get_question(original_index)

        if not question:
            continue

        question = normalize_question(
            question,
            original_index,
        )

        expected = str(
            question.get("answer", "")
        ).strip().lower()

        actual = str(
            user_answer
        ).strip().lower()

        if expected and actual == expected:
            correct += 1

    return round(
        (correct / total) * 100
    )


# ============================================================
# HOME
# ============================================================

@app.route("/")
def index():
    if session.get("user"):
        return redirect(url_for("dashboard"))

    return render_template(
        "login.html",
        user=None,
        google_configured=bool(google),
        google_login_url=url_for("google_login")
    )


# ============================================================
# GOOGLE LOGIN
# ============================================================

@app.route("/login/google")
def google_login():

    # Prevent confusing OAuth errors.
    if google is None:

        return (
            """
            <h2>Google authentication is not configured.</h2>
            <p>
                Check GOOGLE_CLIENT_ID and
                GOOGLE_CLIENT_SECRET in your .env file.
            </p>
            """,
            500
        )

    # Generate the callback from the current request.
    # Local development -> http://127.0.0.1:5000/google/callback
    # Render production -> https://<your-app>.onrender.com/google/callback
    # ProxyFix above makes Flask respect Render's forwarded HTTPS/host.
    redirect_uri = url_for(
        "google_callback",
        _external=True,
    )

    print(
        "Google login redirect:",
        redirect_uri,
    )

    return google.authorize_redirect(
        redirect_uri,
    )


# ============================================================
# GOOGLE CALLBACK
# ============================================================

@app.route("/google/callback")
def google_callback():

    if google is None:

        return (
            "Google OAuth is not configured.",
            500
        )

    try:

        token = google.authorize_access_token()

        userinfo = token.get("userinfo")

        if not userinfo:

            userinfo = google.userinfo()

        if not userinfo:

            raise RuntimeError(
                "Google did not return user information."
            )

        session["user"] = {
            "id": userinfo.get("sub", ""),
            "name": (
                userinfo.get("name")
                or userinfo.get("given_name")
                or "Candidate"
            ),
            "email": userinfo.get(
                "email",
                ""
            ),
            "picture": userinfo.get(
                "picture",
                ""
            ),
        }

        # After login, show the interview setup screen.
        session.pop("interview_questions", None)
        session.pop("question_count", None)
        session["current_question"] = 0
        session["answers"] = {}
        session["score"] = 0

        session.modified = True

        print(
            "Google login successful:",
            session["user"].get("email")
        )

        return redirect(
            url_for("dashboard")
        )

    except Exception as exc:

        print(
            "=" * 60
        )
        print(
            "GOOGLE OAUTH ERROR"
        )
        print(
            repr(exc)
        )
        print(
            "=" * 60
        )

        return render_template(
            "login.html",
            user=None,
            error=(
                "Google authentication failed. "
                "Check your Client ID, Client Secret "
                "and Redirect URI."
            )
        ), 500


# ============================================================
# LOGOUT
# ============================================================

@app.route("/logout")
def logout():

    session.clear()

    return redirect(
        url_for("index")
    )


# ============================================================
# DASHBOARD
# ============================================================

@app.route("/dashboard")
@login_required
def dashboard():

    total = len(QUESTIONS)

    answered = len(
        session.get(
            "answers",
            {}
        )
    )

    score = calculate_score()

    return render_template(
        "dashboard.html",

        user=current_user(),

        total_questions=total,

        answered_questions=answered,

        score=score,

        progress=(
            round(
                (answered / total) * 100
            )
            if total
            else 0
        ),

        questions=[
            normalize_question(
                question,
                i
            )
            for i, question in enumerate(QUESTIONS)
        ],
    )


# ============================================================
# START INTERVIEW
# ============================================================

def get_domains():
    """Return unique question categories/domains for the setup screen."""
    domains = []
    for q in QUESTIONS:
        normalized = normalize_question(q)
        value = str(normalized.get("category", "OpenShift")).strip()
        if value and value not in domains:
            domains.append(value)
    return domains or ["OpenShift"]


def get_difficulties():
    """Return unique difficulty levels for the setup screen."""
    difficulties = []
    for q in QUESTIONS:
        if isinstance(q, dict):
            value = str(q.get("difficulty", "")).strip()
            if value and value not in difficulties:
                difficulties.append(value)
    return difficulties or ["Intermediate"]


def get_question_count_options():
    """Question-count choices that are valid for the loaded question bank."""
    total = len(QUESTIONS)
    if total <= 0:
        return [1]
    return [n for n in (5, 10, 15, 20) if n <= total] or [total]


# ============================================================
# INTERVIEW SETUP HELPERS
# ============================================================

def get_domains():
    """Return unique domains/categories in the question bank."""
    values = []

    for q in QUESTIONS:
        normalized = normalize_question(q)
        value = str(
            normalized.get("domain")
            or normalized.get("category")
            or "OpenShift"
        ).strip()

        if value and value not in values:
            values.append(value)

    return values or ["OpenShift"]


def get_difficulties():
    """Return unique difficulty levels in the question bank."""
    values = []

    for q in QUESTIONS:
        if isinstance(q, dict):
            value = str(
                q.get("difficulty")
                or q.get("level")
                or q.get("difficulty_level")
                or ""
            ).strip()

            if value and value not in values:
                values.append(value)

    # If the JSON has no difficulty field, still provide useful
    # setup choices. Existing questions remain available under All Levels.
    return values or ["Easy", "Intermediate", "Hard"]


def get_question_count_options(available=None):
    """Return sensible question-count choices for the setup screen."""
    if available is None:
        available = len(QUESTIONS)

    available = max(0, int(available))

    if available == 0:
        return [1]

    standard = [5, 10, 15, 20]
    options = [n for n in standard if n <= available]

    # For small filtered result sets, expose every possible count.
    if available < 5:
        return list(range(1, available + 1))

    return options or [available]


def question_matches(question, domain="all", difficulty="all"):
    """Check whether one question matches the selected filters."""
    normalized = normalize_question(question)

    selected_domain = str(domain or "all").strip().lower()
    selected_difficulty = str(difficulty or "all").strip().lower()

    actual_domain = str(
        normalized.get("domain")
        or normalized.get("category")
        or "OpenShift"
    ).strip().lower()

    if isinstance(question, dict):
        actual_difficulty = str(
            question.get("difficulty")
            or question.get("level")
            or question.get("difficulty_level")
            or ""
        ).strip().lower()
    else:
        actual_difficulty = ""

    domain_ok = (
        selected_domain in ("", "all")
        or actual_domain == selected_domain
    )

    # If a question has no difficulty metadata, only "All Levels"
    # should include it. This prevents an Easy/Hard selection from
    # silently returning unrelated questions.
    difficulty_ok = (
        selected_difficulty in ("", "all")
        or actual_difficulty == selected_difficulty
    )

    return domain_ok and difficulty_ok


def get_filtered_indices(domain="all", difficulty="all"):
    """Return original question indices matching the setup filters."""
    return [
        index
        for index, question in enumerate(QUESTIONS)
        if question_matches(question, domain, difficulty)
    ]


def get_active_indices():
    """Return the selected interview's question indices."""
    indices = session.get("interview_questions")

    if isinstance(indices, list) and indices:
        valid = []

        for value in indices:
            try:
                index = int(value)
            except (TypeError, ValueError):
                continue

            if 0 <= index < len(QUESTIONS):
                valid.append(index)

        if valid:
            return valid

    # Backward-compatible fallback.
    return list(range(len(QUESTIONS)))


def render_interview_page(
    question_index,
    evaluation=None,
):
    """Render the active interview question."""
    active_indices = get_active_indices()

    if not active_indices:
        return redirect(url_for("interview"))

    try:
        position = int(question_index)
    except (TypeError, ValueError):
        position = 0

    position = max(
        0,
        min(position, len(active_indices) - 1),
    )

    original_index = active_indices[position]
    question = normalize_question(
        QUESTIONS[original_index],
        original_index,
    )

    answers = session.get("answers", {})

    return render_template(
        "interview.html",
        user=current_user(),
        question=question,
        questions=[
            normalize_question(QUESTIONS[i], i)
            for i in active_indices
        ],
        question_index=position,
        current_question=position,
        original_question_index=original_index,
        question_number=position + 1,
        total_questions=len(active_indices),
        progress=round(
            (len(answers) / len(active_indices)) * 100
        ) if active_indices else 0,
        answered_questions=len(answers),
        saved_answer=answers.get(str(original_index), ""),
        evaluation=evaluation,
        interview_mode=session.get(
            "interview_mode",
            "mock",
        ),
        interview_domain=session.get(
            "interview_domain",
            "All Domains",
        ),
        interview_difficulty=session.get(
            "interview_difficulty",
            "All Levels",
        ),
        domains=get_domains(),
        difficulties=get_difficulties(),
        question_count_options=get_question_count_options(
            len(active_indices)
        ),
    )


# ============================================================
# START A NEW INTERVIEW
# ============================================================

@app.route("/start-interview", methods=["POST"])
@login_required
def start_interview():
    if not QUESTIONS:
        return (
            "No interview questions were found. Check questions.json.",
            500,
        )

    domain = (
        request.form.get("domain", "all").strip()
        or "all"
    )

    difficulty = (
        request.form.get("difficulty", "all").strip()
        or "all"
    )

    try:
        requested_count = int(
            request.form.get(
                "question_count",
                len(QUESTIONS),
            )
        )
    except (TypeError, ValueError):
        requested_count = len(QUESTIONS)

    filtered_indices = get_filtered_indices(
        domain,
        difficulty,
    )

    # If a specific difficulty was selected but the dataset has no
    # matching difficulty metadata, tell the user instead of giving
    # unexpected questions.
    if not filtered_indices:
        flash(
            f"No questions found for Domain '{domain}' "
            f"and Difficulty '{difficulty}'. "
            "Please choose another combination.",
            "error",
        )
        return redirect(url_for("interview"))

    # Randomize the selected pool so repeated interviews do not
    # always start with the same question.
    random.shuffle(filtered_indices)

    selected_count = max(
        1,
        min(
            requested_count,
            len(filtered_indices),
        ),
    )

    selected_indices = filtered_indices[:selected_count]

    session["interview_mode"] = (
        request.form.get(
            "interview_mode",
            "mock",
        ).strip().lower()
        or "mock"
    )

    session["interview_domain"] = domain
    session["interview_difficulty"] = difficulty
    session["question_count"] = selected_count

    # Store original question indices. The visible question number
    # is the position inside this selected interview.
    session["interview_questions"] = selected_indices
    session["current_question"] = 0
    session["answers"] = {}
    session["score"] = 0
    session.modified = True

    return redirect(url_for("interview"))


# ============================================================
# INTERVIEW
# ============================================================

@app.route("/interview")
@login_required
def interview():
    if not QUESTIONS:
        return (
            "No interview questions were found. Check questions.json.",
            500,
        )

    # No active interview = show the setup screen.
    # This is what allows Domain, Difficulty and Question Count
    # to actually be selected before starting.
    active_indices = session.get("interview_questions")

    if not isinstance(active_indices, list) or not active_indices:
        setup_error = session.pop(
            "interview_setup_error",
            None,
        )

        return render_template(
            "interview.html",
            user=current_user(),
            question=None,
            questions=[],
            question_index=0,
            current_question=0,
            question_number=0,
            total_questions=0,
            progress=0,
            answered_questions=0,
            saved_answer="",
            evaluation=None,
            interview_mode="mock",
            interview_domain="all",
            interview_difficulty="all",
            domains=get_domains(),
            difficulties=get_difficulties(),
            question_count_options=get_question_count_options(
                len(QUESTIONS)
            ),
            setup_error=setup_error,
        )

    return render_interview_page(
        session.get("current_question", 0)
    )


# ============================================================
# EVALUATE ANSWER
# ============================================================

@app.route("/interview/evaluate", methods=["POST"])
@login_required
def evaluate_answer():
    active_indices = get_active_indices()

    if not active_indices:
        return redirect(url_for("interview"))

    try:
        position = int(
            request.form.get(
                "question_index",
                session.get("current_question", 0),
            )
        )
    except (TypeError, ValueError):
        position = session.get(
            "current_question",
            0,
        )

    position = max(
        0,
        min(position, len(active_indices) - 1),
    )

    original_index = active_indices[position]

    answer = (
        request.form.get("answer")
        or request.form.get("response")
        or ""
    ).strip()

    answers = session.get("answers", {})
    answers[str(original_index)] = answer
    session["answers"] = answers
    session["current_question"] = position
    session.modified = True

    question = normalize_question(
        QUESTIONS[original_index],
        original_index,
    )

    expected = str(
        question.get("answer", "")
    ).strip()

    explanation = str(
        question.get("explanation", "")
    ).strip()

    # Local evaluation — no external AI API required.
    if not answer:
        score = 0
        verdict = "No Answer"
        feedback = (
            "Please enter an answer before evaluating."
        )

    elif not expected:
        score = 0
        verdict = "Review Required"
        feedback = (
            "This question has no configured expected answer. "
            "Review the response manually."
        )

    else:
        answer_words = set(
            answer.lower().split()
        )

        expected_words = set(
            expected.lower().split()
        )

        overlap = (
            len(
                answer_words & expected_words
            )
            / len(expected_words)
        ) if expected_words else 0

        length_factor = min(
            len(answer.split()) / 80,
            1.0,
        )

        score = round(
            min(
                100,
                (overlap * 70)
                + (length_factor * 30),
            )
        )

        if score >= 80:
            verdict = "Excellent Answer"
            feedback = (
                "Strong coverage of the expected concepts. "
                "Keep the explanation structured and mention "
                "security, scalability, reliability, and trade-offs."
            )

        elif score >= 60:
            verdict = "Good Answer"
            feedback = (
                "Good technical direction. Add more implementation "
                "details and explain your design trade-offs."
            )

        elif score >= 35:
            verdict = "Needs Improvement"
            feedback = (
                "Some relevant concepts are present. Add concrete "
                "OpenShift/Kubernetes components, implementation steps, "
                "security controls, and operational considerations."
            )

        else:
            verdict = "Keep Practicing"
            feedback = (
                "Expand the response with architecture, implementation, "
                "security, scalability, reliability, and trade-offs."
            )

    return render_interview_page(
        position,
        evaluation={
            "score": score,
            "verdict": verdict,
            "feedback": feedback,
            "model_answer": explanation or expected,
            "explanation": (
                "The response is evaluated locally against the "
                "configured expected answer; no external AI API is required."
            ),
        },
    )


# ============================================================
# SUBMIT INTERVIEW ANSWER / NEXT
# ============================================================

@app.route(
    "/interview/answer",
    methods=["POST"]
)
@login_required
def submit_answer():
    active_indices = get_active_indices()

    if not active_indices:
        return redirect(url_for("interview"))

    data = request.get_json(silent=True)

    if data:
        position = data.get(
            "question_index",
            session.get("current_question", 0),
        )
        answer = (
            data.get("answer")
            or data.get("response")
            or ""
        )
    else:
        position = request.form.get(
            "question_index",
            session.get("current_question", 0),
        )
        answer = (
            request.form.get("answer")
            or request.form.get("response")
            or ""
        )

    try:
        position = int(position)
    except (TypeError, ValueError):
        position = session.get(
            "current_question",
            0,
        )

    position = max(
        0,
        min(position, len(active_indices) - 1),
    )

    original_index = active_indices[position]

    answers = session.get("answers", {})
    answers[str(original_index)] = str(
        answer
    ).strip()

    session["answers"] = answers

    next_position = position + 1

    if next_position >= len(active_indices):
        session["current_question"] = (
            len(active_indices) - 1
        )

        score = calculate_score()
        session["score"] = score

        if data:
            return jsonify({
                "success": True,
                "completed": True,
                "score": score,
                "redirect": url_for("result"),
            })

        return redirect(
            url_for("result")
        )

    session["current_question"] = next_position
    session.modified = True

    question = normalize_question(
        QUESTIONS[
            active_indices[next_position]
        ],
        active_indices[next_position],
    )

    score = calculate_score()

    if data:
        return jsonify({
            "success": True,
            "completed": False,
            "next_question": question,
            "question_index": next_position,
            "current_question": next_position,
            "total_questions": len(active_indices),
            "progress": round(
                (
                    len(answers)
                    / len(active_indices)
                ) * 100
            ),
            "score": score,
        })

    return redirect(
        url_for(
            "interview_question",
            question_index=next_position,
        )
    )


# ============================================================
# INDIVIDUAL INTERVIEW QUESTION
# ============================================================

@app.route(
    "/interview/<int:question_index>"
)
@login_required
def interview_question(question_index):
    active_indices = get_active_indices()

    if not active_indices:
        return redirect(url_for("interview"))

    if (
        question_index < 0
        or question_index >= len(active_indices)
    ):
        return redirect(url_for("result"))

    session["current_question"] = question_index
    return render_interview_page(question_index)


# ============================================================
# NEXT QUESTION
# ============================================================

@app.route(
    "/api/next-question",
    methods=["GET"]
)
@login_required
def next_question():
    active_indices = get_active_indices()

    if not active_indices:
        return jsonify({
            "completed": True,
            "redirect": url_for("interview"),
        })

    current = session.get(
        "current_question",
        0,
    )

    try:
        current = int(current)
    except (TypeError, ValueError):
        current = 0

    next_position = current + 1

    if next_position >= len(active_indices):
        return jsonify({
            "completed": True,
            "redirect": url_for("result"),
        })

    session["current_question"] = next_position
    session.modified = True

    original_index = active_indices[next_position]

    question = normalize_question(
        QUESTIONS[original_index],
        original_index,
    )

    return jsonify({
        "completed": False,
        "question": question,
        "question_index": next_position,
        "total_questions": len(active_indices),
    })


# ============================================================
# RESULT
# ============================================================

@app.route("/result")
@login_required
def result():
    active_indices = get_active_indices()

    if not active_indices:
        return redirect(url_for("interview"))

    score = calculate_score()
    session["score"] = score

    answers = session.get(
        "answers",
        {},
    )

    results = []

    for position, original_index in enumerate(
        active_indices
    ):
        question = normalize_question(
            QUESTIONS[original_index],
            original_index,
        )

        user_answer = answers.get(
            str(original_index),
            "",
        )

        expected = str(
            question.get(
                "answer",
                "",
            )
        ).strip()

        is_correct = (
            bool(expected)
            and user_answer.strip().lower()
            == expected.lower()
        )

        results.append({
            "index": position + 1,
            "question": question.get(
                "question",
                "",
            ),
            "category": (
                question.get("domain")
                or question.get(
                    "category",
                    "OpenShift",
                )
            ),
            "user_answer": user_answer,
            "correct_answer": expected,
            "explanation": question.get(
                "explanation",
                "",
            ),
            "correct": is_correct,
        })

    correct_count = sum(
        1
        for item in results
        if item["correct"]
    )

    incorrect_count = (
        len(results)
        - correct_count
    )

    if score >= 85:
        performance = "Excellent"
    elif score >= 70:
        performance = "Strong"
    elif score >= 50:
        performance = "Needs Improvement"
    else:
        performance = "Keep Practicing"

    return render_template(
        "result.html",
        user=current_user(),
        score=score,
        total_questions=len(active_indices),
        correct_count=correct_count,
        incorrect_count=incorrect_count,
        performance=performance,
        results=results,
        answers=answers,
    )


# ============================================================
# RESET INTERVIEW
# ============================================================

@app.route("/reset")
@login_required
def reset_interview():
    session.pop("interview_questions", None)
    session.pop("question_count", None)
    session["current_question"] = 0
    session["answers"] = {}
    session["score"] = 0
    session.modified = True

    return redirect(
        url_for("interview")
    )


# ============================================================
# HEALTH CHECK
# ============================================================

@app.route("/health")
def health():

    return jsonify({
        "status": "healthy",
        "application": "OpenShift AI Interviewer",
        "questions": len(QUESTIONS),
        "google_oauth": bool(google),
    })


# ============================================================
# API: CURRENT USER
# ============================================================

@app.route("/api/me")
def api_me():

    user = current_user()

    if not user:

        return jsonify({
            "authenticated": False
        })

    return jsonify({
        "authenticated": True,
        "user": user
    })


# ============================================================
# API: CURRENT INTERVIEW STATUS
# ============================================================

@app.route(
    "/api/interview/status"
)
@login_required
def interview_status():
    answers = session.get(
        "answers",
        {},
    )

    active_indices = get_active_indices()

    current = session.get(
        "current_question",
        0,
    )

    return jsonify({
        "current_question": current,
        "total_questions": len(active_indices),
        "answered_questions": len(answers),
        "score": calculate_score(),
        "progress": (
            round(
                (
                    len(answers)
                    / len(active_indices)
                ) * 100
            )
            if active_indices
            else 0
        ),
        "domain": session.get(
            "interview_domain",
            "all",
        ),
        "difficulty": session.get(
            "interview_difficulty",
            "all",
        ),
    })


# ============================================================
# ERROR HANDLERS
# ============================================================

@app.errorhandler(404)
def not_found(error):

    return render_template(
        "base.html",
        user=current_user(),
    ), 404


@app.errorhandler(500)
def server_error(error):

    print(
        "Internal server error:",
        repr(error)
    )

    return (
        """
        <h1>Application Error</h1>
        <p>
        Please check the Flask terminal for details.
        </p>
        """,
        500
    )


# ============================================================
# START APPLICATION
# ============================================================

if __name__ == "__main__":

    port = int(
        os.getenv(
            "PORT",
            "5000"
        )
    )

    debug = (
        os.getenv(
            "FLASK_DEBUG",
            "false"
        ).lower()
        == "true"
    )

    print()
    print("=" * 60)
    print(" OpenShift AI Interviewer")
    print("=" * 60)
    print(
        f" Questions loaded : {len(QUESTIONS)}"
    )
    print(
        " Google OAuth     : "
        + (
            "CONFIGURED"
            if google
            else "NOT CONFIGURED"
        )
    )
    print(
        f" Redirect URI     : {GOOGLE_REDIRECT_URI}"
    )
    print(
        f" Server           : http://127.0.0.1:{port}"
    )
    print(
        f" Health           : http://127.0.0.1:{port}/health"
    )
    print("=" * 60)
    print()

    app.run(
        host="0.0.0.0",
        port=port,
        debug=debug
    )