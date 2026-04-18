$(document).ready(function () {
    let productOptions = [];

    $.getJSON('/options/', function (data) {
        productOptions = data;
        // data = [
        //   { id: 1, option_title: 'Цвет', option_value: ['Красный','Синий'] },
        //   { id: 2, option_title: 'Размер', option_value: ['M','L','XL'] },
        // ]
    });

    function addOptionGroup(containerId) {
        // containerId — это "#new-options-container" в нашем случае
        const uniqueId = Date.now(); // или любая другая генерация
        const optionGroupHtml = `
        <div class="option-group" id="option-group-${uniqueId}">
            <select class="option-select form-control">
                <option value="">Выберите опцию</option>
                ${
            productOptions.map(option => `
                        <option value="${option.id}">${option.option_title}</option>
                    `).join('')
        }
            </select>
            <select class="value-select form-control" disabled>
                <option value="">Выберите значение</option>
            </select>
            <button class="remove-new-option btn btn-sm btn-danger">×</button>
        </div>
    `;
        $(containerId).append(optionGroupHtml);
    }


// Добавляем новую опцию при клике
    $('#add-new-option-btn').click(function () {
        addOptionGroup('#new-options-container');
    });

// При выборе опции (option-select) подгружаем её значения
    $('#new-options-container').on('change', '.option-select', function () {
        const optionId = $(this).val();
        const valueSelect = $(this).siblings('.value-select');
        if (optionId) {
            const foundOption = productOptions.find(o => o.id == optionId);
            if (foundOption && foundOption.option_value) {
                valueSelect.html('<option value="">Выберите значение</option>');
                foundOption.option_value.forEach(val => {
                    valueSelect.append(`<option value="${val}">${val}</option>`);
                });
                valueSelect.prop('disabled', false);
            } else {
                valueSelect.prop('disabled', true).html('<option value="">Нет значений</option>');
            }
        } else {
            valueSelect.prop('disabled', true).html('<option value="">Выберите значение</option>');
        }
    });

// Удаляем добавленную (новую) опцию
    $('#new-options-container').on('click', '.remove-new-option', function () {
        $(this).closest('.option-group').remove();
    });

// Удаляем уже существующую опцию (слева)
    $('#existing-options-container').on('click', '.remove-existing-option', function () {
        // Просто удаляем div.option-group из DOM,
        // чтобы при сохранении эта опция не попала в запрос
        $(this).closest('.option-group').remove();
    });

    $('#save-adv-btn').click(function () {
        const advId = $('#adv-id').val();

        // 1. Собираем старые опции (остаток):
        const existingOptions = [];
        $('#existing-options-container .option-group').each(function () {
            const optionKey = $(this).find('.option-key').val();
            const optionValue = $(this).find('.value-select').val();
            // Если вы хотите сохранять "ключ" как строку (название опции):
            existingOptions.push({option_id: optionKey, value: optionValue});
        });

        // 2. Собираем новые опции:
        const newOptions = [];
        $('#new-options-container .option-group').each(function () {
            const optId = $(this).find('.option-select').val();
            const val = $(this).find('.value-select').val();
            // Ищем объект-опцию в массиве productOptions
            const selectedOption = productOptions.find(o => o.id == optId);

            if (selectedOption && val) {
                // Вместо {option_id: optId} записываем название опции
                newOptions.push({
                    option_id: selectedOption.option_title,
                    value: val
                });
            }
        });

        // 3. Объединяем
        const combinedOptions = existingOptions.concat(newOptions);

        // 4. Формируем остальные данные, если нужно (категория, цена и т.д.).
        // Для примера пусть будет только selectedOptions
        const data = {
            adv_id: advId,
            selected_options: combinedOptions
        };

        // 5. Делаем AJAX-запрос на сохранение
        $.ajax({
            url: `/products/edit/adv-edit/save/${advId}/`,  // свой эндпоинт
            method: 'POST',
            headers: {
                'X-CSRFToken': '{{ csrf_token }}'
            },
            data: JSON.stringify(data),
            contentType: 'application/json; charset=utf-8',
            success: function (response) {
                alert(response.message || 'Успешно сохранено!');
                // Можно редиректить или обновить страницу
            },
            error: function (err) {
                console.log(err);
                alert('Ошибка при сохранении опций');
            }
        });
    });


})

