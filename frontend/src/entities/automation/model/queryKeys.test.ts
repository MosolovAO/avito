import {describe, expect, it} from "vitest";

import {automationKeys} from "./queryKeys";

describe("automationKeys", () => {
    it("включает workspace во все ключи", () => {
        expect(automationKeys.catalog(7)).toEqual([
            "automations",
            7,
            "catalog",
        ]);

        expect(automationKeys.list(7, 2)).toEqual([
            "automations",
            7,
            "list",
            2,
        ]);

        expect(automationKeys.detail(7, 12)).toEqual([
            "automations",
            7,
            "detail",
            12,
        ]);

        expect(automationKeys.runs(7, 12, 3)).toEqual([
            "automations",
            7,
            "runs",
            12,
            3,
        ]);

        expect(automationKeys.run(7, 25)).toEqual([
            "automations",
            7,
            "run",
            25,
        ]);

        expect(automationKeys.decisions(7, 25, 4)).toEqual([
            "automations",
            7,
            "run",
            25,
            "decisions",
            4,
        ]);

        expect(automationKeys.inboxSummary(7)).toEqual([
            "automations",
            7,
            "inbox-summary",
        ]);
    });

    it("не смешивает данные разных workspace", () => {
        expect(automationKeys.detail(7, 12)).not.toEqual(
            automationKeys.detail(8, 12),
        );

        expect(automationKeys.list(7, 1)).not.toEqual(
            automationKeys.list(8, 1),
        );
    });

    it("создаёт стабильные корневые ключи для инвалидации списков", () => {
        expect(automationKeys.listRoot(7)).toEqual([
            "automations",
            7,
            "list",
        ]);

        expect(automationKeys.runsRoot(7, 12)).toEqual([
            "automations",
            7,
            "runs",
            12,
        ]);

        expect(automationKeys.decisionsRoot(7, 25)).toEqual([
            "automations",
            7,
            "run",
            25,
            "decisions",
        ]);
    });

    it("допускает null до выбора workspace", () => {
        expect(automationKeys.list(null, 1)).toEqual([
            "automations",
            null,
            "list",
            1,
        ]);
    });
});