$(document).ready(function () {

    $("#price-type").on("change", function () {
        const staticPrice = document.getElementById("price-static");
        const dynamicPrice = document.getElementById("price-dynamic");
        console.log("Test")
        if (this.value === "static") {
            staticPrice.style.display = "flex";
            dynamicPrice.style.display = "none";
        } else if (this.value === "dynamic") {
            staticPrice.style.display = "none";
            dynamicPrice.style.display = "flex";
        }
    });

    const tagContainer = $('#tag-container');
    const tagInput = $('#tag-input');

    // Функция для добавления тега
    function addTag(value) {
        const tag = value.trim();

        if (tag && !isTagDuplicate(tag)) { // Проверяем, что тег не пустой и уникальный
            const tagHtml = `<span class="tag">${tag}<span class="remove">×</span></span>`;
            tagContainer.append(tagHtml);
        }

        tagInput.val(''); // Очищаем поле ввода
    }

    // Проверка на дублирование тега
    function isTagDuplicate(tag) {
        let isDuplicate = false;
        tagContainer.find('.tag').each(function () {
            if ($(this).text().trim() === tag) {
                isDuplicate = true;
                return false; // Прерываем each
            }
        });
        return isDuplicate;
    }

    // Обработка нажатия Enter
    tagInput.on('keypress', function (e) {
        if (e.which === 13) { // Нажата клавиша Enter
            e.preventDefault();
            addTag(tagInput.val());
        }
    });

    // Удаление тега
    tagContainer.on('click', '.remove', function () {
        $(this).closest('.tag').remove();
    });

    let descriptionCounter = 0;

    // Функция для добавления новой вкладки с HTML-редактором
    function addDescriptionTab() {
        descriptionCounter++;

        const newTab = `
                <div class="accordion-item" id="description-${descriptionCounter}">
                    <div class="accordion-header" data-bs-toggle="collapse" data-bs-target="#description-body-${descriptionCounter}">
                        Описание ${descriptionCounter} <button type="button" class="btn btn-danger btn-sm remove-description float-end">Удалить</button>
                    </div>
                    <div class="accordion-body" id="description-body-${descriptionCounter}">
                        <textarea id="editor-${descriptionCounter}" class="description-editor"></textarea>
                    </div>
                </div>
            `;
        $('#description-accordion').append(newTab);

        // Инициализация редактора для нового текстового поля
        tinymce.init({
            selector: `#editor-${descriptionCounter}`,
            height: 200,
            menubar: false,
            plugins: 'lists link image charmap preview',
            toolbar: 'undo redo | formatselect | bold italic backcolor | alignleft aligncenter alignright alignjustify | bullist numlist outdent indent | removeformat',
        });
    }

    function initializeTinyMCEForExistingDescriptions() {
        $('#description-accordion .description-editor').each(function () {
            const editorId = $(this).attr('id'); // Получаем ID текстового поля
            tinymce.init({
                selector: `#${editorId}`, // Привязываемся к конкретному ID
                height: 200,
                menubar: false,
                plugins: 'lists link image charmap preview',
                toolbar: 'undo redo | formatselect | bold italic backcolor | alignleft aligncenter alignright alignjustify | bullist numlist outdent indent | removeformat',
            });
        });
    }

    // Инициализируем TinyMCE для всех текстовых полей при загрузке страницы
    initializeTinyMCEForExistingDescriptions();

    console.log('Инициализация TinyMCE', {
        selector: `#editor-${descriptionCounter}`,
        readonly: false, // Убедитесь, что это false
    });

    // Обработчик кнопки "Добавить описание"
    $('#add-description-btn').click(function () {
        addDescriptionTab();
    });

    // Удаление вкладки описания
    $('#description-accordion').on('click', '.remove-description', function () {
        const tab = $(this).closest('.accordion-item');
        tinymce.get(tab.find('textarea').attr('id')).remove(); // Удаляем редактор
        tab.remove(); // Удаляем вкладку
    });

    const optionsContainer = $('#options-container');

    // Загружаем опции из API
    let productOptions = [];
    $.getJSON('/options/', function (data) {
        productOptions = data;
    });

    // Функция для добавления новой группы выбора опций
    function addOptionGroup() {
        const optionGroupId = `option-group-${Date.now()}`;

        const optionGroupHtml = `
            <div class="option-group" id="${optionGroupId}">
                <select class="option-select form-control">
                    <option value="">Выберите опцию</option>
                    ${productOptions.map(option => `<option value="${option.id}">${option.option_title}</option>`).join('')}
                </select>
                <select class="value-select form-control" disabled>
                    <option value="">Выберите значение</option>
                </select>
                <span class="remove-option">×</span>
            </div>
        `;
        optionsContainer.append(optionGroupHtml);
    }

    // Обработчик кнопки "Добавить опцию"
    $('#add-option-btn').click(function () {
        addOptionGroup();
    });

    // Обработчик выбора опции
    optionsContainer.on('change', '.option-select', function () {
        const optionId = $(this).val();
        console.log('Выбранный optionId:', optionId);

        const valueSelect = $(this).siblings('.value-select');

        if (optionId) {
            const selectedOption = productOptions.find(option => option.id == optionId);
            console.log('Найдена опция:', selectedOption);

            if (selectedOption && selectedOption.option_value) {
                valueSelect.html('<option value="">Выберите значение</option>'); // Очищаем старые значения
                selectedOption.option_value.forEach(value => {
                    valueSelect.append(`<option value="${value}">${value}</option>`);
                });
                valueSelect.prop('disabled', false); // Активируем выбор значений
            } else {
                alert('Опция не найдена или не имеет значений.');
                valueSelect.prop('disabled', true).html('<option value="">Выберите значение</option>');
            }
        } else {
            valueSelect.prop('disabled', true).html('<option value="">Выберите значение</option>');
        }
    });

    // Обработчик удаления группы опции
    optionsContainer.on('click', '.remove-option', function () {
        $(this).closest('.option-group').remove();
    });

    // Сбор данных для отправки
    $('#submit-btn').click(function () {

        const projects = $('#projects').val()

        const category = $('#category').val();
        const listingfee = $('#listingfee').val();
        const email = $('#email').val();
        const contactphone = $('#contactphone').val();
        const managername = $('#managername').val();
        const avitostatus = $('#avitostatus').val();
        const companyname = $('#companyname').val();
        const contactmethod = $('#contactmethod').val();
        const availability = $('#availability').val();
        const adtype = $('#adtype').val();
        const price__fix = $('#price__fix').val();
        const price__min = $('#price__min').val();
        const price__max = $('#price__max').val();
        const price__step = $('#price__step').val();
        const possible__combinations = $('#possible__combinations').val();

        const productId = $('#product-id').val(); // Берем ID продукта из скрытого поля

        const tags = [];
        tagContainer.find('.tag').each(function () {
            tags.push($(this).text().trim().replace('×', '').trim());
        });

        const mainImages = [];
        $('#main-images-thumbnails .thumbnail img').each(function () {
            mainImages.push($(this).attr('src'));
        });

        const additionalImages = [];
        $('#additional-images-thumbnails .thumbnail img').each(function () {
            additionalImages.push($(this).attr('src'));
        });

        const descriptions = {};
        $('#description-accordion .accordion-item').each(function (index, item) {
            const editorId = $(item).find('textarea').attr('id');
            const editor = tinymce.get(editorId);
            if (editor) {
                descriptions[`description_${index + 1}`] = editor.getContent();
            }
        });

        const addresses = $('#addresses')
            .val()
            .split('\n')
            .map(addr => addr.trim())
            .filter(addr => addr.length > 0);

        const selectedOptions = [];
        optionsContainer.find('.option-group').each(function () {
            const optionId = $(this).find('.option-select').val();
            const value = $(this).find('.value-select').val();

            if (optionId && value) {
                selectedOptions.push({option_id: optionId, value: value});
            }
        });

        const data = {
            product_id: productId, // Передаем ID продукта для обновления
            titles: tags,
            main_images: mainImages,
            additional_images: additionalImages,
            descriptions: descriptions,
            addresses: addresses,
            options: selectedOptions,
            listingfee: listingfee,
            email: email,
            contactphone: contactphone,
            managername: managername,
            avitostatus: avitostatus,
            companyname: companyname,
            contactmethod: contactmethod,
            adtype: adtype,
            availability: availability,
            price: price__fix,
            price_min: price__min,
            price_max: price__max,
            price_step: price__step,
            category: category,
            possible_combinations: possible__combinations,
            projects: projects

        };

        console.log(projects)
        $.ajax({
            url: '/products/finish/', // URL для обработки
            method: 'POST',
            data: {
                csrfmiddlewaretoken: '{{ csrf_token }}',
                product_data: JSON.stringify(data),
            },
            success: function (response) {
                alert('Продукт успешно сохранен!');
                window.location.href = '/products/';
            },
            error: function (error) {
                alert('Ошибка при сохранении продукта');
                console.log(error);
            },
        });
    });

    let currentStep = 1;
    const totalSteps = 5;

    function showStep(step) {
        $('.step').removeClass('active');
        $(`#step-${step}`).addClass('active');

        $('#prev-btn').prop('disabled', step === 1);
        $('#next-btn').toggle(step < totalSteps);
        $('#submit-btn').toggle(step === totalSteps);
    }

    // Переход между шагами
    $('#next-btn').click(function () {
        if (currentStep < totalSteps) {
            currentStep++;
            showStep(currentStep);
        }
    });

    $('#prev-btn').click(function () {
        if (currentStep > 1) {
            currentStep--;
            showStep(currentStep);
        }
    });

    showStep(currentStep);

    ///////////////////


    function handleFileSelect(event, dropzone, thumbnailsContainer, uploadUrl) {
        const files = event.originalEvent.dataTransfer ? event.originalEvent.dataTransfer.files : event.target.files;

        Array.from(files).forEach(file => {
            if (!file.type.startsWith('image/')) {
                alert('Можно загружать только изображения.');
                return;
            }

            if (file.size > 5242880) { // Ограничение на 5 MB
                alert(`Файл ${file.name} превышает максимальный размер 5 MB.`);
                return;
            }

            const formData = new FormData();
            formData.append('image', file);

            // Отправляем файл на сервер
            $.ajax({
                url: uploadUrl,
                type: 'POST',
                data: formData,
                processData: false,
                contentType: false,
                success: function (response) {
                    response.uploaded_files.forEach((url) => {
                        const thumbnailHtml = `
                        <div class="thumbnail">
                            <img src="/media/${url}" alt="Изображение">
                            <button class="remove">×</button>
                        </div>
                    `;
                        thumbnailsContainer.append(thumbnailHtml);
                    });
                },
                error: function (error) {
                    alert(`Ошибка загрузки файла: ${error.responseJSON.error}`);
                }
            });
        });
    }


    function setupDropzone(dropzoneId, thumbnailsContainerId, uploadUrl) {
        const dropzone = $(dropzoneId);
        const thumbnailsContainer = $(thumbnailsContainerId);

        dropzone.on('dragover', function (e) {
            e.preventDefault();
            e.stopPropagation();
            dropzone.addClass('dragover');
        });

        dropzone.on('dragleave', function (e) {
            e.preventDefault();
            e.stopPropagation();
            dropzone.removeClass('dragover');
        });

        dropzone.on('drop', function (e) {
            e.preventDefault();
            e.stopPropagation();
            dropzone.removeClass('dragover');
            handleFileSelect(e, dropzone, thumbnailsContainer, uploadUrl);
        });

        dropzone.on('click', function () {
            const fileInput = $('<input type="file" multiple accept="image/*">');
            fileInput.on('change', function (e) {
                handleFileSelect(e, dropzone, thumbnailsContainer, uploadUrl);
            });
            fileInput.click();
        });

        thumbnailsContainer.on('click', '.remove', function () {
            $(this).closest('.thumbnail').remove();
        });
    }

    // Настраиваем загрузку для главных изображений
    setupDropzone('#main-images-dropzone', '#main-images-thumbnails', `/products/${$('#product-id').val()}/upload-images/`);

    // Настраиваем загрузку для дополнительных изображений
    setupDropzone('#additional-images-dropzone', '#additional-images-thumbnails', `/products/${$('#product-id').val()}/upload-images/`);

});
