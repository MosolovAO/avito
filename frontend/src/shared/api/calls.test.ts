import {afterEach, expect, it, vi} from "vitest";
import type {AxiosAdapter} from "axios";

import api from "./axios";
import {getCallAudio, getCalls} from "./calls";

const originalAdapter = api.defaults.adapter;
afterEach(() => {
    api.defaults.adapter = originalAdapter;
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
