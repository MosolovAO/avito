import {render, screen, waitFor} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import {describe, expect, it, vi} from "vitest";

import type {
    Automation,
    AutomationCatalogResponse,
} from "../../../entities/automation";
import {AutomationWizard} from "../index";

const catalog: AutomationCatalogResponse = {
    modules: [
        {
            module_type: "avito_listings",
            label: "Объявления Avito",
            metrics: [
                {
                    code: "views",
                    label: "Просмотры",
                    description: "Количество просмотров",
                    value_type: "integer",
                    allowed_aggregations: ["sum"],
                },
            ],
            aggregations: [
                {
                    code: "sum",
                    label: "Сумма",
                },
            ],
            comparators: [
                {
                    code: "lt",
                    symbol: "<",
                    label: "Меньше",
                },
            ],
            actions: [
                {
                    code: "pause",
                    label: "Приостановить",
                    description: "Временно скрыть объявление",
                    config_schema: {
                        type: "object",
                        properties: {},
                        additionalProperties: false,
                    },
                },
                {
                    code: "archive",
                    label: "Архивировать",
                    description: "Окончательно снять объявление",
                    config_schema: {
                        type: "object",
                        properties: {},
                        additionalProperties: false,
                    },
                },
            ],
            condition_limits: {
                min_window_days: 1,
                max_window_days: 365,
                max_conditions: 50,
            },
        },
    ],
};

const createAutomation = (
    actionType = "pause",
): Automation => ({
    id: 41,
    name: "Мало просмотров",
    module_type: "avito_listings",
    state: "draft",
    execution_mode: "manual",
    version: 1,
    config: {
        avito_account_id: 17,
        condition_tree: {
            type: "group",
            operators: [],
            children: [
                {
                    type: "group",
                    operators: [],
                    children: [{
                        type: "condition",
                        metric: "views",
                        aggregation: "sum",
                        window_days: 10,
                        comparator: "lt",
                        value: 10,
                    }],
                },
            ],
        },
        action: {
            type: actionType,
            config: {},
        },
        max_actions_per_run: 10,
        approval_ttl_minutes: 1440,
    },
    created_by: 1,
    updated_by: 1,
    created_at: "2026-09-01T06:00:00Z",
    updated_at: "2026-09-01T06:00:00Z",
});

interface RenderWizardOptions {
    initialAutomation?: Automation;
    accountLocked?: boolean;
    moduleCatalog?: AutomationCatalogResponse;
}

const renderWizard = ({
    initialAutomation,
    accountLocked = false,
    moduleCatalog = catalog,
}: RenderWizardOptions = {}) => {
    const onSubmit = vi.fn(async () => undefined);

    render(
        <AutomationWizard
            mode={
                initialAutomation === undefined
                    ? "create"
                    : "edit"
            }
            catalog={moduleCatalog}
            accounts={[
                {
                    id: 17,
                    name: "Основной аккаунт",
                },
            ]}
            initialAutomation={initialAutomation}
            accountLocked={accountLocked}
            submitting={false}
            onCancel={vi.fn()}
            onManageAccounts={vi.fn()}
            onSubmit={onSubmit}
        />,
    );

    return {
        onSubmit,
        user: userEvent.setup(),
    };
};

describe("AutomationWizard", () => {
    it("показывает действие, ведущее к следующему шагу", () => {
        renderWizard();

        expect(
            screen.getByRole("heading", {
                name: "Настройка автоматизации",
            }),
        ).toBeInTheDocument();
        expect(
            screen.getByRole("button", {name: "К условиям"}),
        ).toBeInTheDocument();
    });

    it("показывает компактную навигацию по шагам", () => {
        renderWizard();

        expect(
            screen
                .getByRole("navigation", {
                    name: "Шаги создания автоматизации",
                })
                .querySelector(".ant-steps-small"),
        ).toBeInTheDocument();
    });

    it("объясняет область применения правила на шаге объекта", () => {
        renderWizard();

        expect(
            screen.getByRole("heading", {
                name: "Объект автоматизации",
            }),
        ).toBeInTheDocument();
        expect(
            screen.getByText(
                "Название видно только вашей команде",
            ),
        ).toBeInTheDocument();
        expect(
            screen.getByText(
                "Правило будет применяться только " +
                "к объявлениям этого аккаунта",
            ),
        ).toBeInTheDocument();
        expect(
            screen.getByText(
                /Проверьте аккаунт: правило будет работать только в выбранном кабинете/,
            ),
        ).toBeInTheDocument();
    });

    it("не переходит дальше при ошибках обязательных полей", async () => {
        const {user} = renderWizard();

        await user.click(
            screen.getByRole("button", {name: "К условиям"}),
        );

        expect(
            await screen.findByText(
                "Введите название автоматизации",
            ),
        ).toBeInTheDocument();
        expect(
            await screen.findByText(
                "Выберите Avito-аккаунт",
            ),
        ).toBeInTheDocument();
        expect(
            screen.getByRole("heading", {
                name: "Объект автоматизации",
            }),
        ).toBeInTheDocument();
    });

    it("выбирает действие на шаге настроек и отправляет его в payload", async () => {
        const {onSubmit, user} = renderWizard();

        await user.type(
            screen.getByRole("textbox", {
                name: "Название автоматизации",
            }),
            "Smoke test",
        );
        await user.click(
            screen.getByRole("combobox", {
                name: "Avito-аккаунт",
            }),
        );
        await user.click(
            await screen.findByText("Основной аккаунт"),
        );
        await user.click(
            screen.getByRole("button", {name: "К условиям"}),
        );

        await user.click(
            screen.getByRole("button", {
                name: "Добавить условие",
            }),
        );
        await user.click(
            screen.getByRole("button", {name: "К настройкам"}),
        );

        expect(
            screen.getByRole("heading", {name: "Настройки"}),
        ).toBeInTheDocument();
        expect(
            screen.getByText("Название")
                .closest(".ant-descriptions-item"),
        ).toHaveTextContent("Smoke test");
        expect(
            screen.getByText("Avito-аккаунт")
                .closest(".ant-descriptions-item"),
        ).toHaveTextContent("Основной аккаунт");

        await user.click(
            screen.getByRole("radio", {
                name: /Архивировать/,
            }),
        );

        await user.click(
            screen.getByRole("button", {
                name: "Создать автоматизацию",
            }),
        );

        await waitFor(() => {
            expect(onSubmit).toHaveBeenCalledWith(
                expect.objectContaining({
                    config: expect.objectContaining({
                        action: {
                            type: "archive",
                            config: {},
                        },
                    }),
                }),
            );
        });
    });

    it("проводит через три шага и отправляет итоговый payload", async () => {
        const {onSubmit, user} = renderWizard({
            initialAutomation: createAutomation(),
        });

        expect(
            screen.getByRole("heading", {
                name: "Объект автоматизации",
            }),
        ).toBeInTheDocument();

        await user.click(
            screen.getByRole("button", {name: "К условиям"}),
        );
        expect(
            screen.getByRole("heading", {
                name: "Условия срабатывания",
            }),
        ).toBeInTheDocument();

        await user.click(
            screen.getByRole("button", {name: "К настройкам"}),
        );
        expect(
            screen.getByRole("heading", {name: "Настройки"}),
        ).toBeInTheDocument();
        expect(
            screen.getByText("Основной аккаунт"),
        ).toBeInTheDocument();
        expect(
            screen.getByRole("radio", {
                name: /Приостановить/,
            }),
        ).toBeChecked();

        await user.click(
            screen.getByRole("button", {
                name: "Сохранить изменения",
            }),
        );

        await waitFor(() => {
            expect(onSubmit).toHaveBeenCalledWith({
                name: "Мало просмотров",
                module_type: "avito_listings",
                config: {
                    avito_account_id: 17,
                    condition_tree: {
                        type: "group",
                        operators: [],
                        children: [
                            {
                                type: "group",
                                operators: [],
                                children: [{
                                    type: "condition",
                                    metric: "views",
                                    aggregation: "sum",
                                    window_days: 10,
                                    comparator: "lt",
                                    value: 10,
                                }],
                            },
                        ],
                    },
                    action: {
                        type: "pause",
                        config: {},
                    },
                    max_actions_per_run: 10,
                    approval_ttl_minutes: 1440,
                },
            });
        });
    });

    it("показывает читаемую логику правила на шаге условий", async () => {
        const {user} = renderWizard({
            initialAutomation: createAutomation(),
        });

        await user.click(
            screen.getByRole("button", {name: "К условиям"}),
        );

        expect(
            screen.getByRole("heading", {
                name: "Условия срабатывания",
            }),
        ).toBeInTheDocument();
        expect(
            screen.getByText("Сработает, когда"),
        ).toBeInTheDocument();
        expect(
            screen.getByText("Просмотры за 10 дней < 10"),
        ).toBeInTheDocument();
        expect(
            screen.getByText(
                /Группа — скобки в логическом выражении/,
            ),
        ).toBeInTheDocument();
    });

    it("сворачивает и раскрывает детали условий", async () => {
        const {user} = renderWizard({
            initialAutomation: createAutomation(),
        });

        await user.click(
            screen.getByRole("button", {name: "К условиям"}),
        );
        await user.click(
            screen.getByRole("button", {name: "Скрыть детали"}),
        );

        expect(
            screen.queryByRole("group", {name: "Группа 1"}),
        ).not.toBeInTheDocument();
        expect(
            screen.getByRole("button", {
                name: "Показать детали",
            }),
        ).toBeInTheDocument();

        await user.click(
            screen.getByRole("button", {
                name: "Показать детали",
            }),
        );

        expect(
            screen.getByRole("group", {name: "Группа 1"}),
        ).toBeInTheDocument();
    });

    it("разделяет настройки на действие, ограничения и итоговую проверку", async () => {
        const {user} = renderWizard({
            initialAutomation: createAutomation(),
        });

        await user.click(
            screen.getByRole("button", {name: "К условиям"}),
        );
        await user.click(
            screen.getByRole("button", {name: "К настройкам"}),
        );

        expect(
            screen.getByRole("heading", {
                name: "Действие после срабатывания",
            }),
        ).toBeInTheDocument();
        expect(
            screen.getByRole("heading", {
                name: "Ограничения запуска",
            }),
        ).toBeInTheDocument();
        expect(
            screen.getByRole("heading", {
                name: "Проверьте перед запуском",
            }),
        ).toBeInTheDocument();
    });

    it("предупреждает о необратимости архивирования", async () => {
        const {user} = renderWizard({
            initialAutomation: createAutomation("archive"),
        });

        await user.click(
            screen.getByRole("button", {name: "К условиям"}),
        );
        await user.click(
            screen.getByRole("button", {name: "К настройкам"}),
        );

        expect(
            screen.getByRole("heading", {name: "Настройки"}),
        ).toBeInTheDocument();

        expect(
            screen.getByText(/правило не сможет вернуть объявление/i),
        ).toBeInTheDocument();
    });

    it("предупреждает об отключении enabled automation после изменения конфигурации", async () => {
        const automation = createAutomation();
        automation.state = "enabled";

        const {user} = renderWizard({
            initialAutomation: automation,
        });

        await user.click(
            screen.getByRole("button", {name: "К условиям"}),
        );
        await user.click(
            screen.getByRole("button", {name: "К настройкам"}),
        );

        expect(
            screen.queryByText(
                /после сохранения автоматизация будет выключена/i,
            ),
        ).not.toBeInTheDocument();

        const maxActionsInput = screen.getByRole(
            "spinbutton",
            {name: "Максимум действий за запуск"},
        );
        await user.clear(maxActionsInput);
        await user.type(maxActionsInput, "20");

        expect(
            await screen.findByText(
                /после сохранения автоматизация будет выключена/i,
            ),
        ).toBeInTheDocument();
    });

    it("блокирует изменение аккаунта после первого запуска", () => {
        renderWizard({
            initialAutomation: createAutomation(),
            accountLocked: true,
        });

        expect(
            screen.getByLabelText("Avito-аккаунт"),
        ).toBeDisabled();
    });
});
