document.addEventListener('DOMContentLoaded', () => {
    const steps = document.querySelectorAll('.step');
    const stepNavButtons = document.querySelectorAll('.step-nav-btn');
    const nextButtons = document.querySelectorAll('.next-btn');
    const prevButtons = document.querySelectorAll('.prev-btn');

    // Переключение этапов через панель навигации
    stepNavButtons.forEach(button => {
        button.addEventListener('click', () => {
            const targetStep = button.dataset.step;
            changeStep(targetStep);
            updateNav(targetStep);
        });
    });

    // Переход к следующему этапу
    nextButtons.forEach(button => {
        button.addEventListener('click', () => {
            const nextStep = button.dataset.next;
            changeStep(nextStep);
            updateNav(nextStep);
        });
    });

    // Переход к предыдущему этапу
    prevButtons.forEach(button => {
        button.addEventListener('click', () => {
            const prevStep = button.dataset.prev;
            changeStep(prevStep);
            updateNav(prevStep);
        });
    });

    // Функция для переключения этапов
    function changeStep(stepNumber) {
        steps.forEach(step => step.classList.remove('active'));
        document.querySelector(`.step-${stepNumber}`).classList.add('active');
    }

    // Обновление состояния панели навигации
    function updateNav(activeStep) {
        stepNavButtons.forEach(button => button.classList.remove('active'));
        document.querySelector(`.step-nav-btn[data-step="${activeStep}"]`).classList.add('active');
    }
});
