# Планы доработок

## 1. Расширить результат синхронизации отчета автозагрузки Avito

### Контекст

Сейчас кнопка обновления связей с Avito запускает Celery-задачу, которая получает `last_completed_report` из Avito, забирает строки отчета и передает их в `sync_avito_autoload_report`.

Задача уже работает: отчет обрабатывается, импортированные `AvitoListing` обновляются, а публикации связываются с реальными `avito_id`, если `row_id` из отчета совпадает с `AdPublication.row_id`.

Проблема в том, что frontend сейчас видит только общие поля `AvitoAccount`:

- `sync_status`
- `sync_requested_at`
- `sync_started_at`
- `last_synced_at`
- `sync_error`
- `last_sync_total_received`
- `last_sync_created_listings`
- `last_sync_updated_listings`

Этого недостаточно, чтобы пользователь понял, что конкретно произошло после обработки отчета. Например, задача может успешно завершиться, обновить 2949 импортированных объявлений, но не связать ни одной новой публикации, потому что последний отчет Avito относится не к новым `AdPublication`, а к старой автозагрузке.

### Цель

Сделать результат последней синхронизации понятным в UI:

- какой отчет Avito был обработан;
- сколько строк было в отчете;
- сколько строк принято;
- сколько строк отклонено;
- сколько публикаций сервиса связано с реальными Avito объявлениями;
- сколько существующих объявлений обновлено;
- сколько строк отчета не нашли соответствующую `AdPublication`;
- сколько строк отчета пришли без `avito_id`.

### Backend: модель `AvitoAccount`

Добавить поля в `avitotask/models.py` в модель `AvitoAccount`:

```python
last_sync_report_id = models.CharField(max_length=255, blank=True, null=True)
last_sync_report_status = models.CharField(max_length=100, blank=True, null=True)
last_sync_accepted_rows = models.PositiveIntegerField(default=0)
last_sync_rejected_rows = models.PositiveIntegerField(default=0)
last_sync_linked_publications = models.PositiveIntegerField(default=0)
last_sync_missing_publications = models.PositiveIntegerField(default=0)
last_sync_missing_avito_id = models.PositiveIntegerField(default=0)
```

После изменения модели выполнить миграцию:

```bash
python manage.py makemigrations avitotask
python manage.py migrate
```

### Backend: подсчет `missing_avito_id`

В результате `sync_avito_autoload_report` уже есть `errors`, где строки без `avito_id` имеют вид:

```python
{"reason": "missing_avito_id", ...}
```

В Celery-задаче `sync_last_completed_avito_autoload_report_task` нужно посчитать:

```python
missing_avito_id = sum(
    1
    for error in sync_result.errors
    if error.get("reason") == "missing_avito_id"
)
```

### Backend: сохранить расширенный результат в task

В `avitotask/tasks.py` в `sync_last_completed_avito_autoload_report_task` при успешном завершении добавить обновление новых полей:

```python
AvitoAccount.objects.filter(id=avito_account_id).update(
    sync_status=AvitoAccount.SyncStatus.IDLE,
    sync_error=None,
    last_synced_at=timezone.now(),
    last_sync_total_received=sync_result.total_rows,
    last_sync_created_listings=sync_result.created_listings,
    last_sync_updated_listings=sync_result.updated_listings,
    last_sync_report_id=result.report_id,
    last_sync_report_status=result.report_status,
    last_sync_accepted_rows=sync_result.accepted_rows,
    last_sync_rejected_rows=sync_result.rejected_rows,
    last_sync_linked_publications=sync_result.linked_publications,
    last_sync_missing_publications=sync_result.missing_publications,
    last_sync_missing_avito_id=missing_avito_id,
    updated_at=timezone.now(),
)
```

Также добавить эти поля в return payload задачи, чтобы по логам Celery было видно итог:

```python
"report_id": result.report_id,
"report_status": result.report_status,
"accepted_rows": sync_result.accepted_rows,
"rejected_rows": sync_result.rejected_rows,
"linked_publications": sync_result.linked_publications,
"missing_publications": sync_result.missing_publications,
"missing_avito_id": missing_avito_id,
```

### Backend: serializer

В `avitotask/serializers.py` в `AvitoAccountSerializer` добавить новые поля в `fields` и `read_only_fields`:

```python
"last_sync_report_id",
"last_sync_report_status",
"last_sync_accepted_rows",
"last_sync_rejected_rows",
"last_sync_linked_publications",
"last_sync_missing_publications",
"last_sync_missing_avito_id",
```

### Frontend: типы

В `frontend/src/entities/avito/types.ts` в интерфейс `AvitoAccount` добавить:

```ts
last_sync_report_id: string | null;
last_sync_report_status: string | null;
last_sync_accepted_rows: number;
last_sync_rejected_rows: number;
last_sync_linked_publications: number;
last_sync_missing_publications: number;
last_sync_missing_avito_id: number;
```

### Frontend: UI в `ProjectsPage`

На странице проектов в блоке Avito-аккаунта показывать расширенный результат последней синхронизации:

```text
Последний отчет Avito: 541644937 · success_warning
Строк отчета: 14 936
Принято: 7 328
Отклонено: 0
Связано публикаций: 0
Создано объявлений: 0
Обновлено объявлений: 2 949
Не найдены публикации: 4 379
Строк без Avito ID: ...
```

Важно разделить смыслы:

- `last_sync_linked_publications` — сколько `AdPublication` связались с `AvitoListing`;
- `last_sync_created_listings` — сколько новых `AvitoListing` создано;
- `last_sync_updated_listings` — сколько существующих `AvitoListing` обновлено;
- `last_sync_missing_publications` — сколько строк отчета не нашли публикацию по `row_id`;
- `last_sync_missing_avito_id` — сколько строк отчета не имели `avito_id`.

### UX-логика

Если `last_sync_linked_publications = 0`, но `last_sync_updated_listings > 0`, нужно показывать нейтральный результат, а не ошибку:

```text
Отчет обработан. Новые публикации не связаны, но существующие объявления обновлены.
```

Если `last_sync_missing_publications > 0`, можно добавить пояснение:

```text
Часть строк отчета не относится к текущим публикациям сервиса. Это нормально, если последний отчет Avito был сформирован по старой автозагрузке или импортированным объявлениям.
```

### Проверка

Backend:

```bash
python manage.py makemigrations --check --dry-run
python manage.py test avitotask.tests.AvitoExcelImportFlowTests
```

После изменения Celery-кода:

```bash
docker compose restart celery
```

Manual check:

```python
from avitotask.models import AvitoAccount

account = AvitoAccount.objects.get(id=8)
print(account.last_sync_report_id)
print(account.last_sync_report_status)
print(account.last_sync_total_received)
print(account.last_sync_accepted_rows)
print(account.last_sync_linked_publications)
print(account.last_sync_missing_publications)
print(account.last_sync_missing_avito_id)
```

Frontend:

```bash
npm run build
```

### Риски и ограничения

- `last_completed_report` показывает только последний завершенный отчет. Если Avito обработает несколько автозагрузок между нашими проверками, промежуточные отчеты могут быть пропущены.
- Production-версия должна перейти на список отчетов `/autoload/v3/reports` и хранение обработанных `report_id`.
- Расширенные поля в `AvitoAccount` показывают только итог последней синхронизации, а не историю всех синхронизаций.
