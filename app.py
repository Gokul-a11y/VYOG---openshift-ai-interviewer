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

    answers = session.get(
        "answers",
        {}
    )

    total = len(QUESTIONS)

    if total == 0:

        return 0

    correct = 0

    for key, user_answer in answers.items():

        try:

            index = int(key)

        except (TypeError, ValueError):

            continue

        question = get_question(index)

        if not question:

            continue

        question = normalize_question(
            question,
            index
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

        # Start a fresh interview.
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

@app.route("/interview")
@login_required
def interview():

    if not QUESTIONS:

        return (
            "No interview questions were found. "
            "Check questions.json.",
            500
        )

    # Start / restart interview.
    session["current_question"] = 0
    session["answers"] = {}
    session["score"] = 0

    session.modified = True

    question = normalize_question(
        QUESTIONS[0],
        0
    )

    return render_template(
        "interview.html",

        user=current_user(),

        question=question,

        questions=[
            normalize_question(
                q,
                i
            )
            for i, q in enumerate(QUESTIONS)
        ],

        question_index=0,

        current_question=0,

        total_questions=len(QUESTIONS),

        progress=0,

        answered_questions=0,
    )


# ============================================================
# SUBMIT INTERVIEW ANSWER
# ============================================================

@app.route(
    "/interview/answer",
    methods=["POST"]
)
@login_required
def submit_answer():

    data = request.get_json(
        silent=True
    )

    if data:

        question_index = data.get(
            "question_index",
            session.get(
                "current_question",
                0
            )
        )

        answer = (
            data.get("answer")
            or data.get("response")
            or ""
        )

    else:

        question_index = request.form.get(
            "question_index",
            session.get(
                "current_question",
                0
            )
        )

        answer = (
            request.form.get("answer")
            or request.form.get("response")
            or ""
        )

    try:

        question_index = int(
            question_index
        )

    except (TypeError, ValueError):

        question_index = session.get(
            "current_question",
            0
        )

    if question_index < 0:

        question_index = 0

    if question_index >= len(QUESTIONS):

        question_index = len(QUESTIONS) - 1

    answers = session.get(
        "answers",
        {}
    )

    answers[str(question_index)] = str(
        answer
    ).strip()

    session["answers"] = answers

    session.modified = True

    next_index = question_index + 1

    # Interview finished.
    if next_index >= len(QUESTIONS):

        session["current_question"] = (
            len(QUESTIONS) - 1
        )

        score = calculate_score()

        session["score"] = score

        if data:

            return jsonify({
                "success": True,
                "completed": True,
                "score": score,
                "redirect": url_for(
                    "result"
                )
            })

        return redirect(
            url_for("result")
        )

    # Continue.
    session["current_question"] = (
        next_index
    )

    question = normalize_question(
        QUESTIONS[next_index],
        next_index
    )

    score = calculate_score()

    if data:

        return jsonify({
            "success": True,
            "completed": False,
            "next_question": question,
            "question_index": next_index,
            "current_question": next_index,
            "total_questions": len(QUESTIONS),
            "progress": round(
                (
                    (next_index)
                    / len(QUESTIONS)
                ) * 100
            ),
            "score": score
        })

    return redirect(
        url_for(
            "interview_question",
            question_index=next_index
        )
    )


# ============================================================
# INDIVIDUAL INTERVIEW QUESTION
# ============================================================

@app.route(
    "/interview/<int:question_index>"
)
@login_required
def interview_question(
    question_index
):

    if not QUESTIONS:

        return (
            "No questions available.",
            500
        )

    if question_index < 0:

        question_index = 0

    if question_index >= len(QUESTIONS):

        return redirect(
            url_for("result")
        )

    session["current_question"] = (
        question_index
    )

    question = normalize_question(
        QUESTIONS[question_index],
        question_index
    )

    answered = len(
        session.get(
            "answers",
            {}
        )
    )

    progress = round(
        (
            question_index
            / len(QUESTIONS)
        ) * 100
    )

    return render_template(
        "interview.html",

        user=current_user(),

        question=question,

        question_index=question_index,

        current_question=question_index,

        total_questions=len(QUESTIONS),

        progress=progress,

        answered_questions=answered,

        questions=[
            normalize_question(
                q,
                i
            )
            for i, q in enumerate(QUESTIONS)
        ],
    )


# ============================================================
# NEXT QUESTION
# ============================================================

@app.route(
    "/api/next-question",
    methods=["GET"]
)
@login_required
def next_question():

    current = session.get(
        "current_question",
        0
    )

    next_index = current + 1

    if next_index >= len(QUESTIONS):

        return jsonify({
            "completed": True,
            "redirect": url_for(
                "result"
            )
        })

    session["current_question"] = (
        next_index
    )

    question = normalize_question(
        QUESTIONS[next_index],
        next_index
    )

    return jsonify({
        "completed": False,
        "question": question,
        "question_index": next_index,
        "total_questions": len(QUESTIONS)
    })


# ============================================================
# RESULT
# ============================================================

@app.route("/result")
@login_required
def result():

    score = calculate_score()

    session["score"] = score

    answers = session.get(
        "answers",
        {}
    )

    results = []

    for index, original in enumerate(
        QUESTIONS
    ):

        question = normalize_question(
            original,
            index
        )

        user_answer = answers.get(
            str(index),
            ""
        )

        expected = str(
            question.get(
                "answer",
                ""
            )
        ).strip()

        is_correct = (
            bool(expected)
            and user_answer.strip().lower()
            == expected.lower()
        )

        results.append({
            "index": index + 1,
            "question": question.get(
                "question",
                ""
            ),
            "category": question.get(
                "category",
                "OpenShift"
            ),
            "user_answer": user_answer,
            "correct_answer": expected,
            "explanation": question.get(
                "explanation",
                ""
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

        total_questions=len(
            QUESTIONS
        ),

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
        {}
    )

    current = session.get(
        "current_question",
        0
    )

    return jsonify({
        "current_question": current,
        "total_questions": len(
            QUESTIONS
        ),
        "answered_questions": len(
            answers
        ),
        "score": calculate_score(),
        "progress": (
            round(
                (
                    len(answers)
                    / len(QUESTIONS)
                ) * 100
            )
            if QUESTIONS
            else 0
        )
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