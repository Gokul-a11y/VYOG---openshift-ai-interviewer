/* =========================================================
   OpenShift AI Interviewer - Frontend Controller
   ========================================================= */

document.addEventListener("DOMContentLoaded", function () {

    /* -----------------------------------------------------
       Mobile navigation
    ----------------------------------------------------- */

    const menuButton = document.querySelector("[data-menu-toggle]");
    const mobileMenu = document.querySelector("[data-mobile-menu]");

    if (menuButton && mobileMenu) {
        menuButton.addEventListener("click", function () {
            mobileMenu.classList.toggle("open");
        });
    }


    /* -----------------------------------------------------
       Answer word counter
    ----------------------------------------------------- */

    const answerBox = document.querySelector("#answerBox");
    const wordCounter = document.querySelector("#wordCounter");

    if (answerBox && wordCounter) {

        function updateWordCount() {

            const text = answerBox.value.trim();

            const words = text
                ? text.split(/\s+/).length
                : 0;

            wordCounter.textContent =
                words + " words";
        }

        answerBox.addEventListener(
            "input",
            updateWordCount
        );

        updateWordCount();
    }


    /* -----------------------------------------------------
       Prevent empty interview answers
    ----------------------------------------------------- */

    const answerForm =
        document.querySelector("#answerForm");

    if (answerForm && answerBox) {

        answerForm.addEventListener(
            "submit",
            function (event) {

                const answer =
                    answerBox.value.trim();

                if (answer.length < 10) {

                    event.preventDefault();

                    alert(
                        "Please provide a detailed answer before submitting."
                    );

                    answerBox.focus();

                    return;
                }

                const submitButton =
                    answerForm.querySelector(
                        "button[type='submit']"
                    );

                if (submitButton) {

                    submitButton.disabled = true;

                    submitButton.innerHTML =
                        "Evaluating...";
                }
            }
        );
    }


    /* -----------------------------------------------------
       Start interview form
    ----------------------------------------------------- */

    const startForm =
        document.querySelector("#startInterviewForm");

    if (startForm) {

        startForm.addEventListener(
            "submit",
            function () {

                const button =
                    startForm.querySelector(
                        "button[type='submit']"
                    );

                if (button) {

                    button.disabled = true;

                    button.innerHTML =
                        "Starting Interview...";
                }
            }
        );
    }


    /* -----------------------------------------------------
       Difficulty cards
    ----------------------------------------------------- */

    document
        .querySelectorAll("[data-difficulty]")
        .forEach(function (card) {

            card.addEventListener(
                "click",
                function () {

                    const difficulty =
                        card.dataset.difficulty;

                    const select =
                        document.querySelector(
                            "#difficulty"
                        );

                    if (select) {

                        select.value =
                            difficulty;

                        document
                            .querySelectorAll(
                                "[data-difficulty]"
                            )
                            .forEach(function (item) {

                                item.classList.remove(
                                    "selected"
                                );

                            });

                        card.classList.add(
                            "selected"
                        );
                    }
                }
            );
        });


    /* -----------------------------------------------------
       Category cards
    ----------------------------------------------------- */

    document
        .querySelectorAll("[data-category]")
        .forEach(function (card) {

            card.addEventListener(
                "click",
                function () {

                    const category =
                        card.dataset.category;

                    const select =
                        document.querySelector(
                            "#category"
                        );

                    if (select) {

                        select.value =
                            category;

                        document
                            .querySelectorAll(
                                "[data-category]"
                            )
                            .forEach(function (item) {

                                item.classList.remove(
                                    "selected"
                                );

                            });

                        card.classList.add(
                            "selected"
                        );
                    }
                }
            );
        });


    /* -----------------------------------------------------
       Auto focus answer
    ----------------------------------------------------- */

    if (answerBox) {

        setTimeout(function () {

            answerBox.focus();

        }, 300);
    }


    /* -----------------------------------------------------
       Confirm logout
    ----------------------------------------------------- */

    document
        .querySelectorAll("[data-logout]")
        .forEach(function (button) {

            button.addEventListener(
                "click",
                function (event) {

                    const confirmed =
                        confirm(
                            "Are you sure you want to logout?"
                        );

                    if (!confirmed) {

                        event.preventDefault();
                    }
                }
            );
        });


    /* -----------------------------------------------------
       Keyboard shortcut
       Ctrl + Enter = submit answer
    ----------------------------------------------------- */

    if (answerBox && answerForm) {

        answerBox.addEventListener(
            "keydown",
            function (event) {

                if (
                    event.ctrlKey &&
                    event.key === "Enter"
                ) {

                    event.preventDefault();

                    answerForm.requestSubmit();
                }
            }
        );
    }

});