import {afterEach, expect, it, vi} from "vitest";
import type {AxiosAdapter} from "axios";

import api from "./axios";
import {getCallAudio, getCalls, getCallDailyReport, saveCallReport} from "./calls";

const originalAdapter = api.defaults.adapter;
afterEach(() => {
    api.defaults.adapter = originalAdapter;
});

it("requests the daily report for the selected account and forwards cancellation", async () => {
    const data = {
        avito_account_id: 8, account_name: "Основной", date: "2026-09-28",
        report_count: 1, report_text: "Понедельник, 28 сентября\nОсновной\n\n+7 (000) 000-00-01\nВиктория",
    };
    const adapter = vi.fn<AxiosAdapter>(async (config) => ({
        config, data, headers: {}, status: 200, statusText: "OK",
    }));
    api.defaults.adapter = adapter;
    const controller = new AbortController();

    const result = await getCallDailyReport({
        workspaceId: 2, avitoAccountId: 8, date: "2026-09-28", signal: controller.signal,
    });

    expect(result).toEqual(data);
    expect(adapter).toHaveBeenCalledOnce();
    const config = adapter.mock.calls[0][0];
    expect(config.method).toBe("get");
    expect(config.url).toBe("/api/calls/reports/daily/");
    expect(config.params).toEqual({avito_account_id: 8, date: "2026-09-28"});
    expect(config.headers["X-Workspace-Id"]).toBe("2");
    expect(config.signal).toBe(controller.signal);
});

it("does not send an audio request when its signal has already been aborted", async () => {
    const adapter = vi.fn<AxiosAdapter>(async (config) => ({
        config, data: new Blob(["audio"]), headers: {}, status: 200, statusText: "OK",
    }));
    api.defaults.adapter = adapter;
    const controller = new AbortController();
    controller.abort();

    await expect(getCallAudio(2, 1, controller.signal)).rejects.toMatchObject({
        code: "ERR_CANCELED",
    });
    expect(adapter).not.toHaveBeenCalled();
});

it("sends the search and page to the calls endpoint in the current workspace", async () => {
    const adapter = vi.fn<AxiosAdapter>(async (config) => ({
        config,
        data: {count: 0, next: null, previous: null, results: []},
        headers: {}, status: 200, statusText: "OK",
    }));
    api.defaults.adapter = adapter;

    await getCalls({
        workspaceId: 2,
        avitoAccountId: 8,
        date: "2026-09-28",
        page: 2,
        pageSize: 30,
        search: "велосипед",
    });

    expect(adapter).toHaveBeenCalledOnce();
    const config = adapter.mock.calls[0][0];
    expect(config.url).toBe("/api/calls/");
    expect(config.params).toEqual({
        avito_account_id: 8,
        date: "2026-09-28",
        page: 2,
        page_size: 30,
        search: "велосипед",
    });
    expect(config.headers["X-Workspace-Id"]).toBe("2");
});

it("saves the plain-text report for the requested call in its workspace", async () => {
    const report = "Виктория\nГСБ 40 кубов / Москва / Перезвонит клиенту";
    const adapter = vi.fn<AxiosAdapter>(async (config) => ({
        config,
        data: {report_text: report},
        headers: {}, status: 200, statusText: "OK",
    }));
    api.defaults.adapter = adapter;

    const result = await saveCallReport(2, 17, report);

    expect(result).toEqual({report_text: report});
    expect(adapter).toHaveBeenCalledOnce();
    const config = adapter.mock.calls[0][0];
    expect(config.method).toBe("put");
    expect(config.url).toBe("/api/calls/17/report/");
    expect(config.headers["X-Workspace-Id"]).toBe("2");
    expect(JSON.parse(config.data)).toEqual({report_text: report});
});
