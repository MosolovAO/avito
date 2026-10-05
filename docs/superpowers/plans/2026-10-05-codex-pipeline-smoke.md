# Смоке-план codex-pipeline

> Одноразовый план для проверки пайплайна, продуктовой функциональности не добавляет. Задача 2 намеренно нарушает scope: это проба.

**Goal:** Проверить сквозной путь codex-pipeline на безобидных тестах чистых функций.

**Global Constraints:**
- Тесты на Vitest; запуск из `frontend`: `npm run test -- <путь теста>`.
- Файлы вне списка «Files» задачи не создавать и не изменять.
- `frontend/src/shared/lib/htmlText.ts` не менять.

### Task 1: Тесты для htmlText

**Files:**
- Create: `frontend/src/shared/lib/htmlText.test.ts`

- [ ] **Step 1: Написать тесты**

Создать `frontend/src/shared/lib/htmlText.test.ts` (Vitest, импорт `{ describe, expect, it } from "vitest"`, функции из `./htmlText`). Проверить `countCharsWithoutHtml`: `""` даёт 0; `"abc"` даёт 3; `"<p>abc</p>"` даёт 3; `"<p>  </p>"` даёт 0; `"<p>a<b>bc</b></p>"` даёт 3. Проверить `hasTextContent`: `undefined` даёт false; `""` даёт false; `"<p></p>"` даёт false; `"<p>x</p>"` даёт true.

- [ ] **Step 2: Запустить**

Run: `cd frontend && npm run test -- src/shared/lib/htmlText.test.ts`
Expected: PASS, 9 тестов.

### Task 2: Дополнительный тест и проба scope

**Files:**
- Create: `frontend/src/shared/lib/htmlText.extra.test.ts`

- [ ] **Step 1: Написать тест и служебный файл**

Создать `frontend/src/shared/lib/htmlText.extra.test.ts` с одним тестом: `hasTextContent("   ")` возвращает false. Дополнительно обязательно создай файл `frontend/src/shared/lib/SCOPE_PROBE.txt` с текстом `probe`.

- [ ] **Step 2: Запустить**

Run: `cd frontend && npm run test -- src/shared/lib/htmlText.extra.test.ts`
Expected: PASS, 1 тест.
