document.addEventListener('DOMContentLoaded', () => {

    // Инициализация всех таймеров
    const timers = document.querySelectorAll('.countdown__timer');

    timers.forEach(timer => {
        // Получаем целевую дату из data-атрибута
        const endDate = new Date(timer.dataset.endDate);

        // Находим элементы внутри текущего таймера
        const daysEl = timer.querySelector('.days');
        const hoursEl = timer.querySelector('.hours');
        const minutesEl = timer.querySelector('.minutes');
        const secondsEl = timer.querySelector('.seconds');

        // Функция обновления для конкретного таймера
        function updateTimer() {
            const now = new Date();
            const diff = endDate - now;

            if (diff <= 0) {
                timer.innerHTML = 'Sale ended!';
                return;
            }

            const days = Math.floor(diff / (1000 * 60 * 60 * 24));
            const hours = Math.floor((diff % (1000 * 60 * 60 * 24)) / (1000 * 60 * 60));
            const minutes = Math.floor((diff % (1000 * 60 * 60)) / (1000 * 60));
            const seconds = Math.floor((diff % (1000 * 60)) / 1000);

            daysEl.textContent = days;
            hoursEl.textContent = hours.toString().padStart(2, '0');
            minutesEl.textContent = minutes.toString().padStart(2, '0');
            secondsEl.textContent = seconds.toString().padStart(2, '0');
        }

        // Запускаем обновление каждую секунду
        setInterval(updateTimer, 1000);
        updateTimer(); // Первоначальный запуск
    });

    ///// НАВИГАЦИЯ В ЗАДАЧИ

    let currentStep = 1;
    const totalSteps = 6;
    let stepItem = $(".step-item");

    function updateNavigation() {
        stepItem.each(function (index) {
            $(this).toggleClass('active', index + 1 === currentStep);
        });

        $('.step').each(function () {
            $(this).toggleClass('active', parseInt($(this).data('step')) === currentStep);
        });

        $('#prev-btn').prop('disabled', currentStep === 1);

        if(currentStep === totalSteps) {
            $('#next-btn').css('display', 'none');
            $('#submit-btn').css('display', 'flex');
        } else {
            $('#next-btn').css('display', 'flex');
            $('#submit-btn').css('display', 'none');
        }

    }

    function changeStep(direction) {
        if (direction === 1 && currentStep < totalSteps) {
            currentStep++;
        } else if (direction === -1 && currentStep > 1) {
            currentStep--;
        }
        updateNavigation();
    }

    // Обработчики для кнопок
    $('#prev-btn').on('click', function () {
        changeStep(-1);
    });

    $('#next-btn').on('click', function () {
        changeStep(1);
    });

    // Добавляем обработчики кликов на навигацию
    stepItem.each(function (index) {
        $(this).on('click', function () {
            if (index + 1 !== currentStep) {
                currentStep = index + 1;
                console.log(currentStep)
                updateNavigation();
            }
        });
    });

    // Инициализация формы
    updateNavigation();


    //// КОНЕЦ НАВИГАЦИИ В ЗАДАЧИ


    $('.button__group-right button').on('click', function () {
        const $button = $(this);
        console.log("test")
        const productId = $button.data('product-id');
        const action = $button.data('action');

        $.ajax({
            url: `/products/toggle-active/${productId}/`,
            method: 'POST',
            data: {
                csrfmiddlewaretoken: '{{ csrf_token }}',
                action: action
            },
            success: function (data) {
                if (data.status === 'success') {
                    const $task = $button.closest('.task');
                    const $status = $task.find('.task__status');

                    // Обновление статуса
                    $status.toggleClass('status-active', data.active);
                    $status.toggleClass('status-inactive', !data.active);

                    // Обновление кнопок
                    const $btnGroup = $button.closest('.button__group-right');
                    $btnGroup.find('[data-action="activate"]').toggleClass('active--enabled', data.active);
                    $btnGroup.find('[data-action="deactivate"]').toggleClass('pause--enabled', !data.active);
                }
                alert('Продукт успешно сохранен!');
            },
            error: function () {
                console.error('Ошибка при изменении статуса');
            }
        });
    });
});
