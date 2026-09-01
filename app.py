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
)

from dotenv import load_dotenv
from authlib.integrations.flask_client import OAuth


# ============================================================
# CONFIGURATION
# ============================================================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

load_dotenv(
    os.path.join(BASE_DIR, ".env")
)

app = Flask(__name__)

app.config["SECRET_KEY"] = os.getenv(
    "SECRET_KEY",
    "dev-secret-change-this"
)

app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = (
    os.getenv(
        "SESSION_COOKIE_SECURE",
        "false"
    ).lower() == "true"
)


# ============================================================
# GOOGLE OAUTH
# ============================================================

GOOGLE_CLIENT_ID = os.getenv(
    "GOOGLE_CLIENT_ID",
    ""
).strip()

GOOGLE_CLIENT_SECRET = os.getenv(
    "GOOGLE_CLIENT_SECRET",
    ""
).strip()

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

        print(
            "WARNING: questions.json not found."
        )

        return []

    try:

        with open(
            QUESTIONS_FILE,
            "r",
            encoding="utf-8"
        ) as file:

            data = json.load(file)

        if isinstance(data, dict):

            questions = data.get(
                "questions",
                data.get("data", [])
            )

        else:

            questions = data

        if not isinstance(
            questions,
            list
        ):

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
print(
    f"Questions loaded : {len(QUESTIONS)}"
)
print(
    "Google OAuth     :",
    "CONFIGURED"
    if google
    else "NOT CONFIGURED"
)
print(
    "Redirect URI     :",
    GOOGLE_REDIRECT_URI
)
print("=" * 60)


# ============================================================
# INTERVIEW OPTIONS
# ============================================================

QUESTION_COUNT_OPTIONS = [
    5,
    10,
    15,
    20
]


# ============================================================
# HELPERS
# ============================================================

def current_user():

    return session.get(
        "user"
    )


def login_required(function):

    @wraps(function)
    def decorated(*args, **kwargs):

        if not session.get("user"):

            return redirect(
                url_for("index")
            )

        return function(
            *args,
            **kwargs
        )

    return decorated


def normalize_question(
    question,
    index=0
):
    """
    Convert different JSON question formats
    into one consistent format.
    """

    if not isinstance(
        question,
        dict
    ):

        return {
            "id": index + 1,
            "question": str(question),
            "text": str(question),
            "category": "OpenShift",
            "domain": "OpenShift",
            "difficulty": "Intermediate",
            "options": [],
            "answer": "",
            "explanation": "",
            "model_answer": "",
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

    domain = (
        question.get("domain")
        or question.get("category")
        or question.get("topic")
        or "OpenShift"
    )

    difficulty = (
        question.get("difficulty")
        or question.get("level")
        or "Intermediate"
    )

    explanation = (
        question.get("explanation")
        or ""
    )

    model_answer = (
        question.get("model_answer")
        or question.get("ideal_answer")
        or question.get("expected_answer")
        or correct
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

        "domain": domain,

        "difficulty": difficulty,

        "options": options,

        "answer": correct,

        "explanation": explanation,

        "model_answer": model_answer,
    }


def all_normalized_questions():

    return [
        normalize_question(
            question,
            index
        )

        for index, question
        in enumerate(QUESTIONS)
    ]


def get_active_indexes():

    indexes = session.get(
        "interview_indexes"
    )

    if not isinstance(
        indexes,
        list
    ):

        return list(
            range(len(QUESTIONS))
        )

    valid = []

    for index in indexes:

        try:

            index = int(index)

            if (
                0 <= index < len(QUESTIONS)
            ):

                valid.append(index)

        except (
            TypeError,
            ValueError
        ):

            continue

    return valid


def get_active_questions():

    indexes = get_active_indexes()

    return [
        normalize_question(
            QUESTIONS[index],
            index
        )

        for index in indexes
    ]


def get_current_question():

    active_indexes = get_active_indexes()

    if not active_indexes:

        return None, 0, None

    current = session.get(
        "current_question",
        0
    )

    try:

        current = int(current)

    except (
        TypeError,
        ValueError
    ):

        current = 0

    if current < 0:

        current = 0

    if current >= len(active_indexes):

        current = len(active_indexes) - 1

    original_index = active_indexes[
        current
    ]

    question = normalize_question(
        QUESTIONS[original_index],
        original_index
    )

    return (
        question,
        current,
        original_index
    )


# ============================================================
# ANSWER EVALUATION
# ============================================================

def evaluate_local_answer(
    question,
    user_answer
):
    """
    Local evaluator.
    No external API required.

    Works for:
    - multiple choice
    - short answers
    - architecture answers
    """

    user_answer = (
        str(user_answer or "")
        .strip()
    )

    expected = (
        str(
            question.get(
                "answer",
                ""
            )
        ).strip()
    )

    model_answer = (
        str(
            question.get(
                "model_answer",
                ""
            )
        ).strip()
    )

    explanation = (
        str(
            question.get(
                "explanation",
                ""
            )
        ).strip()
    )

    if not user_answer:

        return {
            "score": 0,
            "verdict": "No Answer",
            "feedback": (
                "No answer was provided. "
                "Provide a clear explanation "
                "before evaluating."
            ),
            "model_answer": model_answer,
            "explanation": explanation,
        }

    # --------------------------------------------------------
    # Exact match
    # --------------------------------------------------------

    if expected:

        if (
            user_answer.lower()
            == expected.lower()
        ):

            return {
                "score": 100,
                "verdict": "Excellent",
                "feedback": (
                    "Your answer matches "
                    "the expected answer."
                ),
                "model_answer": model_answer,
                "explanation": explanation,
            }

    # --------------------------------------------------------
    # Keyword / concept evaluation
    # --------------------------------------------------------

    reference = (
        model_answer
        or expected
        or explanation
    )

    user_words = set(
        word.strip(
            ".,!?;:()[]{}"
        ).lower()

        for word in user_answer.split()
    )

    reference_words = set(
        word.strip(
            ".,!?;:()[]{}"
        ).lower()

        for word in reference.split()
    )

    stop_words = {
        "the",
        "a",
        "an",
        "and",
        "or",
        "to",
        "of",
        "in",
        "on",
        "for",
        "with",
        "is",
        "are",
        "be",
        "as",
        "this",
        "that",
        "it",
        "by",
        "from",
        "use",
        "using",
    }

    reference_words -= stop_words
    user_words -= stop_words

    matched = (
        user_words
        & reference_words
    )

    if reference_words:

        coverage = (
            len(matched)
            / len(reference_words)
        )

    else:

        coverage = 0

    # --------------------------------------------------------
    # Architecture keywords
    # --------------------------------------------------------

    architecture_keywords = {
        "openshift",
        "kubernetes",
        "pod",
        "deployment",
        "service",
        "route",
        "namespace",
        "rbac",
        "security",
        "secret",
        "gitops",
        "argocd",
        "scaling",
        "autoscaling",
        "ha",
        "availability",
        "monitoring",
        "logging",
        "backup",
        "disaster",
        "network",
        "policy",
        "container",
        "image",
        "operator",
        "cluster",
        "node",
        "replica",
    }

    architecture_matches = (
        user_words
        & architecture_keywords
    )

    # --------------------------------------------------------
    # Calculate score
    # --------------------------------------------------------

    score = int(
        min(
            100,
            (
                coverage * 70
                + min(
                    len(
                        architecture_matches
                    ) * 5,
                    30
                )
            )
        )
    )

    # Give reasonable minimum score
    # to meaningful long answers.
    if len(user_answer.split()) >= 40:

        score = max(
            score,
            45
        )

    elif len(user_answer.split()) >= 20:

        score = max(
            score,
            35
        )

    # --------------------------------------------------------
    # Verdict
    # --------------------------------------------------------

    if score >= 85:

        verdict = "Excellent"

        feedback = (
            "Strong answer. You covered "
            "important technical concepts "
            "and demonstrated good "
            "architectural understanding."
        )

    elif score >= 70:

        verdict = "Strong"

        feedback = (
            "Good answer. The main concepts "
            "are covered, but you could add "
            "more implementation details, "
            "security considerations and "
            "trade-offs."
        )

    elif score >= 50:

        verdict = "Needs Improvement"

        feedback = (
            "Your answer shows some relevant "
            "understanding, but it needs more "
            "technical depth. Explain the "
            "architecture, implementation, "
            "security, scalability and "
            "operational considerations."
        )

    else:

        verdict = "Keep Practicing"

        feedback = (
            "The answer needs more technical "
            "detail. Structure your response "
            "around requirements, architecture, "
            "implementation, security, "
            "scalability, observability and "
            "trade-offs."
        )

    return {
        "score": score,

        "verdict": verdict,

        "feedback": feedback,

        "model_answer": model_answer,

        "explanation": explanation,
    }


def calculate_score():

    evaluations = session.get(
        "evaluations",
        {}
    )

    if not evaluations:

        return 0

    scores = []

    for value in evaluations.values():

        if isinstance(
            value,
            dict
        ):

            try:

                scores.append(
                    int(
                        value.get(
                            "score",
                            0
                        )
                    )
                )

            except (
                TypeError,
                ValueError
            ):

                pass

    if not scores:

        return 0

    return round(
        sum(scores)
        / len(scores)
    )


# ============================================================
# HOME
# ============================================================

@app.route("/")
def index():

    if session.get("user"):

        return redirect(
            url_for("dashboard")
        )

    return render_template(
        "login.html",

        user=None,

        google_configured=bool(
            google
        ),

        google_login_url=url_for(
            "google_login"
        ),
    )


# ============================================================
# GOOGLE LOGIN
# ============================================================

@app.route("/login/google")
def google_login():

    if google is None:

        return render_template(
            "login.html",

            user=None,

            google_configured=False,

            google_login_url=url_for(
                "google_login"
            ),

            error=(
                "Google authentication "
                "is not configured. "
                "Check your .env file."
            ),
        ), 500

    redirect_uri = (
        GOOGLE_REDIRECT_URI
    )

    print(
        "Google login redirect:",
        redirect_uri
    )

    return google.authorize_redirect(
        redirect_uri
    )


# ============================================================
# GOOGLE CALLBACK
# ============================================================

@app.route("/google/callback")
def google_callback():

    if request.args.get(
        "error"
    ) == "access_denied":

        return render_template(
            "login.html",

            user=None,

            google_configured=bool(
                google
            ),

            google_login_url=url_for(
                "google_login"
            ),

            error=(
                "Google sign-in was "
                "cancelled. Click "
                "Continue with Google "
                "again and choose Allow."
            ),
        )

    if google is None:

        return (
            "Google OAuth is not configured.",
            500
        )

    try:

        token = (
            google.authorize_access_token()
        )

        userinfo = token.get(
            "userinfo"
        )

        if not userinfo:

            userinfo = google.userinfo()

        if not userinfo:

            raise RuntimeError(
                "Google did not return "
                "user information."
            )

        session["user"] = {

            "id": userinfo.get(
                "sub",
                ""
            ),

            "name": (
                userinfo.get("name")
                or userinfo.get(
                    "given_name"
                )
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

        # Fresh interview state
        session["current_question"] = 0
        session["answers"] = {}
        session["evaluations"] = {}
        session["score"] = 0
        session["interview_started"] = False

        session.modified = True

        print(
            "Google login successful:",
            session["user"].get(
                "email"
            )
        )

        return redirect(
            url_for("dashboard")
        )

    except Exception as exc:

        print("=" * 60)
        print("GOOGLE OAUTH ERROR")
        print(repr(exc))
        print("=" * 60)

        return render_template(
            "login.html",

            user=None,

            google_configured=bool(
                google
            ),

            google_login_url=url_for(
                "google_login"
            ),

            error=(
                "Google authentication "
                "failed. Check your "
                "Client ID, Client Secret "
                "and Redirect URI."
            ),
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

    total = len(
        get_active_indexes()
    )

    answered = len(
        session.get(
            "answers",
            {}
        )
    )

    score = calculate_score()

    progress = (
        round(
            (
                answered
                / total
            ) * 100
        )

        if total

        else 0
    )

    return render_template(
        "dashboard.html",

        user=current_user(),

        total_questions=total,

        answered_questions=answered,

        score=score,

        progress=progress,

        questions=all_normalized_questions(),
    )


# ============================================================
# INTERVIEW SETUP + CURRENT INTERVIEW
# ============================================================

@app.route(
    "/interview",
    methods=["GET"]
)
@login_required
def interview():

    if not QUESTIONS:

        return (
            "No interview questions "
            "were found. Check "
            "questions.json.",
            500
        )

    # --------------------------------------------------------
    # IMPORTANT:
    # DO NOT RESET THE SESSION HERE.
    # --------------------------------------------------------

    if not session.get(
        "interview_started",
        False
    ):

        return render_template(
            "interview.html",

            user=current_user(),

            question=None,

            domains=sorted(
                {
                    str(
                        normalize_question(
                            q,
                            i
                        ).get(
                            "domain",
                            "OpenShift"
                        )
                    )

                    for i, q
                    in enumerate(QUESTIONS)
                }
            ),

            difficulties=[
                "Beginner",
                "Intermediate",
                "Advanced",
            ],

            question_count_options=[
                count

                for count
                in QUESTION_COUNT_OPTIONS

                if count <= len(
                    QUESTIONS
                )
            ]
            or [len(QUESTIONS)],

            interview_mode="Mock Interview",

            interview_domain="All Domains",

            interview_difficulty="All Levels",

            answered_questions=0,

            total_questions=0,
        )

    question, current, original_index = (
        get_current_question()
    )

    if question is None:

        return redirect(
            url_for("interview")
        )

    answers = session.get(
        "answers",
        {}
    )

    evaluations = session.get(
        "evaluations",
        {}
    )

    saved_answer = answers.get(
        str(original_index),
        ""
    )

    evaluation = evaluations.get(
        str(original_index)
    )

    active_indexes = (
        get_active_indexes()
    )

    total_questions = len(
        active_indexes
    )

    answered_questions = len(
        answers
    )

    progress = round(
        (
            answered_questions
            / total_questions
        ) * 100
    ) if total_questions else 0

    return render_template(
        "interview.html",

        user=current_user(),

        question=question,

        question_index=current,

        current_question=current,

        original_question_index=original_index,

        question_number=current + 1,

        total_questions=total_questions,

        progress=progress,

        answered_questions=answered_questions,

        saved_answer=saved_answer,

        evaluation=evaluation,

        interview_mode=session.get(
            "interview_mode",
            "Mock Interview"
        ),

        interview_domain=session.get(
            "interview_domain",
            "All Domains"
        ),

        interview_difficulty=session.get(
            "interview_difficulty",
            "All Levels"
        ),

        questions=get_active_questions(),
    )


# ============================================================
# START INTERVIEW
# ============================================================

@app.route(
    "/start_interview",
    methods=["GET", "POST"]
)
@login_required
def start_interview():

    if not QUESTIONS:

        return (
            "No interview questions "
            "are available.",
            500
        )

    if request.method == "GET":

        return redirect(
            url_for("interview")
        )

    interview_mode = (
        request.form.get(
            "interview_mode",
            "mock"
        )
    )

    domain = (
        request.form.get(
            "domain",
            "all"
        )
    )

    difficulty = (
        request.form.get(
            "difficulty",
            "all"
        )
    )

    try:

        question_count = int(
            request.form.get(
                "question_count",
                len(QUESTIONS)
            )
        )

    except (
        TypeError,
        ValueError
    ):

        question_count = len(
            QUESTIONS
        )

    # --------------------------------------------------------
    # FILTER QUESTIONS
    # --------------------------------------------------------

    filtered = []

    for index, original in enumerate(
        QUESTIONS
    ):

        question = normalize_question(
            original,
            index
        )

        question_domain = str(
            question.get(
                "domain",
                ""
            )
        ).strip().lower()

        question_difficulty = str(
            question.get(
                "difficulty",
                ""
            )
        ).strip().lower()

        domain_match = (
            domain.lower() == "all"
            or question_domain
            == domain.lower()
        )

        difficulty_match = (
            difficulty.lower() == "all"
            or question_difficulty
            == difficulty.lower()
        )

        if (
            domain_match
            and difficulty_match
        ):

            filtered.append(
                index
            )

    # If filters produce nothing,
    # use all questions.
    if not filtered:

        filtered = list(
            range(len(QUESTIONS))
        )

    # --------------------------------------------------------
    # SELECT QUESTION COUNT
    # --------------------------------------------------------

    question_count = max(
        1,
        min(
            question_count,
            len(filtered)
        )
    )

    # Random selection
    selected = random.sample(
        filtered,
        question_count
    )

    # Keep selected order stable
    # for the whole interview.
    session["interview_indexes"] = (
        selected
    )

    session["current_question"] = 0

    session["answers"] = {}

    session["evaluations"] = {}

    session["score"] = 0

    session["interview_started"] = True

    session["interview_mode"] = (
        "Practice"
        if interview_mode == "practice"
        else "Mock Interview"
    )

    session["interview_domain"] = (
        domain
        if domain.lower() != "all"
        else "All Domains"
    )

    session["interview_difficulty"] = (
        difficulty
        if difficulty.lower() != "all"
        else "All Levels"
    )

    session.modified = True

    return redirect(
        url_for("interview")
    )


# ============================================================
# EVALUATE ANSWER
# ============================================================

@app.route(
    "/evaluate_answer",
    methods=["POST"]
)
@login_required
def evaluate_answer():

    if not session.get(
        "interview_started",
        False
    ):

        return redirect(
            url_for("interview")
        )

    try:

        question_index = int(
            request.form.get(
                "question_index",
                session.get(
                    "current_question",
                    0
                )
            )
        )

    except (
        TypeError,
        ValueError
    ):

        question_index = session.get(
            "current_question",
            0
        )

    answer = (
        request.form.get(
            "answer",
            ""
        )
        .strip()
    )

    active_indexes = (
        get_active_indexes()
    )

    if not active_indexes:

        return redirect(
            url_for("interview")
        )

    if question_index < 0:

        question_index = 0

    if question_index >= len(
        active_indexes
    ):

        question_index = (
            len(active_indexes) - 1
        )

    original_index = (
        active_indexes[
            question_index
        ]
    )

    question = normalize_question(
        QUESTIONS[original_index],
        original_index
    )

    # Save answer immediately
    answers = session.get(
        "answers",
        {}
    )

    answers[
        str(original_index)
    ] = answer

    session["answers"] = answers

    # Evaluate
    evaluation = evaluate_local_answer(
        question,
        answer
    )

    evaluations = session.get(
        "evaluations",
        {}
    )

    evaluations[
        str(original_index)
    ] = evaluation

    session["evaluations"] = (
        evaluations
    )

    session["current_question"] = (
        question_index
    )

    session["score"] = (
        calculate_score()
    )

    session.modified = True

    # --------------------------------------------------------
    # IMPORTANT:
    # Render SAME page.
    # Do NOT redirect to /interview.
    # --------------------------------------------------------

    return render_template(
        "interview.html",

        user=current_user(),

        question=question,

        question_index=question_index,

        current_question=question_index,

        original_question_index=original_index,

        question_number=question_index + 1,

        total_questions=len(
            active_indexes
        ),

        progress=round(
            (
                len(answers)
                / len(active_indexes)
            ) * 100
        ),

        answered_questions=len(
            answers
        ),

        saved_answer=answer,

        evaluation=evaluation,

        interview_mode=session.get(
            "interview_mode",
            "Mock Interview"
        ),

        interview_domain=session.get(
            "interview_domain",
            "All Domains"
        ),

        interview_difficulty=session.get(
            "interview_difficulty",
            "All Levels"
        ),

        questions=get_active_questions(),
    )


# ============================================================
# COMPATIBILITY ROUTE
# ============================================================

@app.route(
    "/evaluate-answer",
    methods=["POST"]
)
@login_required
def evaluate_answer_compat():

    return evaluate_answer()


# ============================================================
# NEXT QUESTION
# ============================================================

@app.route(
    "/interview/answer",
    methods=["POST"]
)
@login_required
def submit_answer():

    if not session.get(
        "interview_started",
        False
    ):

        return redirect(
            url_for("interview")
        )

    active_indexes = (
        get_active_indexes()
    )

    if not active_indexes:

        return redirect(
            url_for("interview")
        )

    try:

        question_index = int(
            request.form.get(
                "question_index",
                session.get(
                    "current_question",
                    0
                )
            )
        )

    except (
        TypeError,
        ValueError
    ):

        question_index = session.get(
            "current_question",
            0
        )

    if question_index < 0:

        question_index = 0

    if question_index >= len(
        active_indexes
    ):

        question_index = (
            len(active_indexes) - 1
        )

    original_index = (
        active_indexes[
            question_index
        ]
    )

    answer = (
        request.form.get(
            "answer",
            ""
        )
        .strip()
    )

    # Save answer
    answers = session.get(
        "answers",
        {}
    )

    answers[
        str(original_index)
    ] = answer

    session["answers"] = answers

    # If it was not evaluated,
    # evaluate it before moving on.
    evaluations = session.get(
        "evaluations",
        {}
    )

    if str(original_index) not in evaluations:

        question = normalize_question(
            QUESTIONS[original_index],
            original_index
        )

        evaluations[
            str(original_index)
        ] = evaluate_local_answer(
            question,
            answer
        )

        session["evaluations"] = (
            evaluations
        )

    next_index = (
        question_index + 1
    )

    # --------------------------------------------------------
    # FINISHED
    # --------------------------------------------------------

    if next_index >= len(
        active_indexes
    ):

        session["score"] = (
            calculate_score()
        )

        session["current_question"] = (
            question_index
        )

        session.modified = True

        return redirect(
            url_for("result")
        )

    # --------------------------------------------------------
    # NEXT QUESTION
    # --------------------------------------------------------

    session["current_question"] = (
        next_index
    )

    session.modified = True

    return redirect(
        url_for("interview")
    )


# ============================================================
# INDIVIDUAL QUESTION
# ============================================================

@app.route(
    "/interview/<int:question_index>"
)
@login_required
def interview_question(
    question_index
):

    if not session.get(
        "interview_started",
        False
    ):

        return redirect(
            url_for("interview")
        )

    active_indexes = (
        get_active_indexes()
    )

    if not active_indexes:

        return redirect(
            url_for("interview")
        )

    if question_index < 0:

        question_index = 0

    if question_index >= len(
        active_indexes
    ):

        return redirect(
            url_for("result")
        )

    session["current_question"] = (
        question_index
    )

    session.modified = True

    return redirect(
        url_for("interview")
    )


# ============================================================
# API: NEXT QUESTION
# ============================================================

@app.route(
    "/api/next-question",
    methods=["GET"]
)
@login_required
def next_question():

    active_indexes = (
        get_active_indexes()
    )

    current = session.get(
        "current_question",
        0
    )

    next_index = current + 1

    if next_index >= len(
        active_indexes
    ):

        return jsonify({
            "completed": True,
            "redirect": url_for(
                "result"
            )
        })

    session["current_question"] = (
        next_index
    )

    original_index = (
        active_indexes[
            next_index
        ]
    )

    question = normalize_question(
        QUESTIONS[original_index],
        original_index
    )

    session.modified = True

    return jsonify({

        "completed": False,

        "question": question,

        "question_index": next_index,

        "total_questions": len(
            active_indexes
        ),

        "progress": round(
            (
                next_index
                / len(active_indexes)
            ) * 100
        ),
    })


# ============================================================
# RESULT
# ============================================================

# ============================================================
# RESULT
# ============================================================

@app.route("/result")
@login_required
def result():

    # --------------------------------------------------------
    # Get interview data from session
    # --------------------------------------------------------

    answers = session.get(
        "answers",
        {}
    )

    evaluations = session.get(
        "evaluations",
        {}
    )

    # --------------------------------------------------------
    # Get selected questions
    # --------------------------------------------------------

    active_indexes = session.get(
        "interview_indexes"
    )

    if not isinstance(
        active_indexes,
        list
    ) or not active_indexes:

        active_indexes = list(
            range(len(QUESTIONS))
        )

    # Make sure indexes are valid
    active_indexes = [
        int(index)

        for index in active_indexes

        if str(index).isdigit()
        and 0 <= int(index) < len(QUESTIONS)
    ]

    # --------------------------------------------------------
    # Build result list
    # --------------------------------------------------------

    results = []

    for display_index, original_index in enumerate(
        active_indexes
    ):

        question = normalize_question(
            QUESTIONS[original_index],
            original_index
        )

        user_answer = answers.get(
            str(original_index),
            ""
        )

        evaluation = evaluations.get(
            str(original_index)
        )

        # If an answer somehow wasn't evaluated,
        # evaluate it now.
        if evaluation is None:

            evaluation = evaluate_local_answer(
                question,
                user_answer
            )

        try:

            question_score = int(
                evaluation.get(
                    "score",
                    0
                )
            )

        except (
            TypeError,
            ValueError
        ):

            question_score = 0

        results.append({

            "index": display_index + 1,

            "question": question.get(
                "question",
                ""
            ),

            "category": question.get(
                "category",
                "OpenShift"
            ),

            "domain": question.get(
                "domain",
                "OpenShift"
            ),

            "difficulty": question.get(
                "difficulty",
                "Intermediate"
            ),

            "user_answer": user_answer,

            "correct_answer": question.get(
                "answer",
                ""
            ),

            "model_answer": question.get(
                "model_answer",
                ""
            ),

            "explanation": question.get(
                "explanation",
                ""
            ),

            "evaluation": evaluation,

            "score": question_score,

            "correct": (
                question_score >= 70
            ),
        })

    # --------------------------------------------------------
    # Overall score
    # --------------------------------------------------------

    if results:

        score = round(
            sum(
                item["score"]
                for item in results
            )
            / len(results)
        )

    else:

        score = 0

    session["score"] = score

    # --------------------------------------------------------
    # Statistics
    # --------------------------------------------------------

    total_questions = len(
        results
    )

    answered_count = sum(
        1
        for item in results
        if item["user_answer"].strip()
    )

    correct_count = sum(
        1
        for item in results
        if item["correct"]
    )

    incorrect_count = (
        total_questions
        - correct_count
    )

    # --------------------------------------------------------
    # Performance
    # --------------------------------------------------------

    if score >= 85:

        performance = "Excellent"

    elif score >= 70:

        performance = "Strong"

    elif score >= 50:

        performance = "Needs Improvement"

    else:

        performance = "Keep Practicing"

    # --------------------------------------------------------
    # IMPORTANT FIX
    #
    # base.html expects `question`.
    # Result page does not have a current question,
    # so explicitly provide None.
    # --------------------------------------------------------

    return render_template(

        "result.html",

        user=current_user(),

        question=None,

        question_number=None,

        current_question=None,

        question_index=None,

        total_questions=total_questions,

        progress=100,

        answered_questions=answered_count,

        score=score,

        correct_count=correct_count,

        incorrect_count=incorrect_count,

        performance=performance,

        results=results,

        answers=answers,

        evaluation=evaluations,

        interview_mode=session.get(
            "interview_mode",
            "Mock Interview"
        ),

        interview_domain=session.get(
            "interview_domain",
            "All Domains"
        ),

        interview_difficulty=session.get(
            "interview_difficulty",
            "All Levels"
        ),
    )

# ============================================================
# RESET INTERVIEW
# ============================================================

@app.route("/reset")
@login_required
def reset_interview():

    session["current_question"] = 0

    session["answers"] = {}

    session["evaluations"] = {}

    session["score"] = 0

    session["interview_indexes"] = []

    session["interview_started"] = False

    session.modified = True

    return redirect(
        url_for("interview")
    )


# ============================================================
# HEALTH
# ============================================================

@app.route("/health")
def health():

    return jsonify({

        "status": "healthy",

        "application": (
            "OpenShift AI Interviewer"
        ),

        "questions": len(
            QUESTIONS
        ),

        "google_oauth": bool(
            google
        ),
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
# API: INTERVIEW STATUS
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

    active_indexes = (
        get_active_indexes()
    )

    current = session.get(
        "current_question",
        0
    )

    return jsonify({

        "current_question": current,

        "total_questions": len(
            active_indexes
        ),

        "answered_questions": len(
            answers
        ),

        "score": calculate_score(),

        "progress": (
            round(
                (
                    len(answers)
                    / len(active_indexes)
                ) * 100
            )

            if active_indexes

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
        user=current_user()
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
            Please check the Flask terminal
            for details.
        </p>
        """,
        500
    )


# ============================================================
# RUN
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
            "true"
        ).lower()
        == "true"
    )

    print()
    print("=" * 60)
    print(
        " OpenShift AI Interviewer"
    )
    print("=" * 60)

    print(
        f" Questions loaded : "
        f"{len(QUESTIONS)}"
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
        f" Redirect URI     : "
        f"{GOOGLE_REDIRECT_URI}"
    )

    print(
        f" Server           : "
        f"http://127.0.0.1:{port}"
    )

    print(
        f" Health           : "
        f"http://127.0.0.1:{port}/health"
    )

    print("=" * 60)
    print()

    app.run(
        host="0.0.0.0",
        port=port,
        debug=debug
    )