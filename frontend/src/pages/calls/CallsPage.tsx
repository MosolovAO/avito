import {useEffect, useRef, useState} from "react";
import axios from "axios";
import {useQueries, useQuery, useQueryClient} from "@tanstack/react-query";
import {
    Alert,
    Button,
    DatePicker,
    Divider,
    Empty,
    Input,
    Result,
    Select,
    Slider,
    Spin,
    Space,
    Table,
    Tag,
    Typography,
    message,
} from "antd";
import type {TableProps} from "antd";
import dayjs from "dayjs";
import type {Dayjs} from "dayjs";
import "dayjs/locale/ru";
import isoWeek from "dayjs/plugin/isoWeek";
import utc from "dayjs/plugin/utc";
import timezone from "dayjs/plugin/timezone";
import ruDatePickerLocale from "antd/es/date-picker/locale/ru_RU";
import {CallReportEditor} from "../../features/call-report/ui/CallReportEditor.tsx";
import {
    AudioOutlined,
    CaretRightOutlined,
    CloseOutlined,
    CopyOutlined,
    EditOutlined,
    FileTextOutlined,
    PauseOutlined,
    SoundOutlined,
} from "@ant-design/icons";
import {useAvitoProjectsQuery} from "../../features/avito";
import {useCurrentWorkspace} from "../../features/workspace/model/useCurrentWorkspace";
import {
    getCallAudio,
    getCalls,
    getCallsSyncStatus,
    type CallRecord,
} from "../../shared/api/calls";

import {DailyCallReport} from "../../features/call-report/ui/DailyCallReport";

import styles from "./CallsPage.module.scss";

dayjs.extend(utc);
dayjs.extend(timezone);
dayjs.extend(isoWeek);

const {Title, Text} = Typography;

function formatSeconds(seconds: number): string {
    const safe = Math.max(0, Math.floor(seconds));
    return `${Math.floor(safe / 60)}:${String(safe % 60).padStart(2, "0")}`;
}

function formatPhone(value: string): string {
    const phone = value.trim();
    if (!phone) return "Неизвестно";
    if (!/^\+?[\d\s()-]+$/.test(phone)) return phone;

    let digits = phone.replace(/\D/g, "");

    if (!phone.startsWith("+")) {
        if (digits.length === 10) {
            digits = `7${digits}`;
        } else if (/^8\d{10}$/.test(digits)) {
            digits = `7${digits.slice(1)}`;
        }
    }

    const match = digits.match(/^7(\d{3})(\d{3})(\d{2})(\d{2})$/);
    return match
        ? `+7 (${match[1]}) ${match[2]}-${match[3]}-${match[4]}`
        : digits.length >= 10
            ? `+${digits}`
            : phone;
}

async function copyPhone(phone: string): Promise<void> {
    try {
        await navigator.clipboard.writeText(phone);
        message.success("Номер скопирован");
    } catch {
        message.error("Не удалось скопировать номер.");
    }
}

interface LoadedAudio {
    call: CallRecord;
    url: string;
}

const CALLS_PAGE_SIZE = 30;

interface WeekCallsProps {
    days: Dayjs[];
    workspaceId: number;
    accountId: number;
    search: string;
    columns: TableProps<CallRecord>["columns"];
    activeCallId: number | null;
    reportCallId: number | null;
    onCloseReport: () => void;
}

function WeekCalls({
                       days,
                       workspaceId,
                       accountId,
                       search,
                       columns,
                       activeCallId,
                       reportCallId,
                       onCloseReport,
                   }: WeekCallsProps) {
    const [pages, setPages] = useState<Record<string, number>>({});
    const dates = days.map((day) => day.format("YYYY-MM-DD"));
    const queries = useQueries({
        queries: dates.map((date) => ({
            queryKey: [
                "calls",
                workspaceId,
                accountId,
                date,
                search,
                pages[date] ?? 1,
            ],
            queryFn: ({signal}: { signal: AbortSignal }) =>
                getCalls({
                    workspaceId,
                    avitoAccountId: accountId,
                    date,
                    page: pages[date] ?? 1,
                    pageSize: CALLS_PAGE_SIZE,
                    search: search || undefined,
                    signal,
                }),
        })),
    });
    const visibleDays = days
        .map((day, index) => ({
            day,
            date: dates[index],
            query: queries[index],
        }))
        .filter(({query}) => !search || (query.data?.count ?? 0) > 0);

    return (
        <>
            {queries.some((query) => query.isError) && (
                <Alert
                    type="error"
                    showIcon
                    message="Не удалось загрузить звонки"
                    style={{marginBottom: 16}}
                />
            )}
            {queries.length > 0 && queries.every((query) => query.isPending) && (
                <Spin aria-label="Загрузка звонков"/>
            )}
            {search &&
                queries.every((query) => query.isSuccess) &&
                visibleDays.length === 0 && (
                    <Empty description="По выбранной неделе ничего не найдено"/>
                )}
            {visibleDays.map(({day, date, query}, index) => (
                <section key={date} className={styles.daySection}>
                    <DailyCallReport
                        workspaceId={workspaceId}
                        accountId={accountId}
                        date={date}
                        dateLabel={day.format("D MMMM")}
                        heading={
                            <Divider titlePlacement="left">
                                <Space size={8}>
                  <span>
                    {day.format("D MMMM YYYY [г.], ") +
                        day
                            .format("dddd")
                            .replace(/^./u, (letter) =>
                                letter.toLocaleUpperCase("ru-RU"),
                            )}
                  </span>

                                    {query.data && (
                                        <Tag
                                            color="blue"
                                            aria-label={`Количество звонков за ${day.format("D MMMM")}`}>
                                            Всего звонков: {query.data.count}
                                        </Tag>
                                    )}
                                </Space>
                            </Divider>
                        }
                    />
                    <Table<CallRecord>
                        bordered
                        rowKey="id"
                        rowClassName={(call) =>
                            call.id === activeCallId ? styles.activeRow : ""
                        }
                        size="medium"
                        columns={columns}
                        expandable={{
                            showExpandColumn: false,
                            expandedRowKeys: reportCallId === null ? [] : [reportCallId],
                            rowExpandable: (call) => call.id === reportCallId,
                            expandedRowRender: (call) => (
                                <CallReportEditor
                                    key={`${workspaceId}:${call.id}`}
                                    call={call}
                                    workspaceId={workspaceId}
                                    accountId={accountId}
                                    onClose={onCloseReport}
                                />
                            ),
                        }}
                        tableLayout="fixed"
                        dataSource={query.data?.results ?? []}
                        loading={query.isFetching}
                        showHeader={index === 0}
                        pagination={{
                            current: pages[date] ?? 1,
                            pageSize: CALLS_PAGE_SIZE,
                            total: query.data?.count ?? 0,
                            showSizeChanger: false,
                            hideOnSinglePage: true,
                            onChange: (page) =>
                                setPages((current) => ({
                                    ...current,
                                    [date]: page,
                                })),
                        }}
                        locale={{emptyText: "Нет доступных записей"}}
                    />
                </section>
            ))}
        </>
    );
}

function CallsAudioPlayer({
                              loadedAudio,
                              speed,
                              onSpeedChange,
                              onClose,
                          }: {
    loadedAudio: LoadedAudio;
    speed: number;
    onSpeedChange: (speed: number) => void;
    onClose: () => void;
}) {
    const [position, setPosition] = useState(0);
    const [duration, setDuration] = useState(0);
    const [volume, setVolume] = useState(1);
    const [playing, setPlaying] = useState(false);
    const audioRef = useRef<HTMLAudioElement>(null);

    async function togglePlayback() {
        const audio = audioRef.current;
        if (!audio) return;
        if (!audio.paused) {
            audio.pause();
            return;
        }
        try {
            await audio.play();
        } catch {
            message.error("Не удалось воспроизвести аудио.");
        }
    }

    return (
        <>
            <div className={styles.playerSpacer} aria-hidden="true"/>
            <div
                className={styles.player}
                role="region"
                aria-label="Плеер записи звонка">
                <audio
                    ref={audioRef}
                    src={loadedAudio.url}
                    hidden
                    onLoadedMetadata={async (event) => {
                        const audio = event.currentTarget;
                        setDuration(Number.isFinite(audio.duration) ? audio.duration : 0);
                        audio.playbackRate = speed;
                        audio.volume = volume;

                        try {
                            await audio.play();
                        } catch {
                            if (audioRef.current === audio) {
                                message.warning(
                                    "Не удалось автоматически запустить аудио. Нажмите «Воспроизвести».",
                                );
                            }
                        }
                    }}
                    onTimeUpdate={(event) => setPosition(event.currentTarget.currentTime)}
                    onPlay={() => setPlaying(true)}
                    onPause={() => setPlaying(false)}
                    onEnded={() => setPlaying(false)}
                />

                <div className={styles.playerIcon} aria-hidden="true">
                    <AudioOutlined/>
                </div>

                <div className={styles.playerInfo}>
                    <Text strong>
                        {loadedAudio.call.buyer_phone
                            ? `Разговор с ${formatPhone(loadedAudio.call.buyer_phone)}`
                            : "Запись звонка"}
                    </Text>
                    <Text type="secondary" className={styles.playerMeta}>
                        {dayjs(loadedAudio.call.occurred_at)
                            .tz("Europe/Moscow")
                            .format("DD.MM.YYYY, HH:mm")}
                        {" · "}
                        {loadedAudio.call.listing?.title ||
                            (loadedAudio.call.listing
                                ? `№ ${loadedAudio.call.listing.avito_id}`
                                : "Объявление неизвестно")}
                    </Text>
                </div>

                <Button
                    type="primary"
                    shape="circle"
                    size="large"
                    icon={playing ? <PauseOutlined/> : <CaretRightOutlined/>}
                    aria-label={playing ? "Пауза" : "Воспроизвести"}
                    onClick={() => void togglePlayback()}
                />

                <Text className={styles.playerTime}>{formatSeconds(position)}</Text>
                <Slider
                    className={styles.timeline}
                    ariaLabelForHandle="Перемотка"
                    min={0}
                    max={Math.max(duration, 1)}
                    value={position}
                    onChange={(value) => {
                        if (typeof value !== "number") return;
                        if (audioRef.current) audioRef.current.currentTime = value;
                        setPosition(value);
                    }}
                />
                <Text className={styles.playerTime}>{formatSeconds(duration)}</Text>

                <Select<number>
                    className={styles.speed}
                    aria-label="Скорость"
                    value={speed}
                    options={[0.75, 1, 1.25, 1.5, 2].map((value) => ({
                        label: `${value}×`,
                        value,
                    }))}
                    onChange={(value) => {
                        onSpeedChange(value);
                        if (audioRef.current) audioRef.current.playbackRate = value;
                    }}
                />

                <div className={styles.volume}>
                    <SoundOutlined aria-hidden="true"/>
                    <Slider
                        ariaLabelForHandle="Громкость"
                        min={0}
                        max={1}
                        step={0.05}
                        value={volume}
                        onChange={(value) => {
                            if (typeof value !== "number") return;
                            setVolume(value);
                            if (audioRef.current) audioRef.current.volume = value;
                        }}
                    />
                </div>

                <Button
                    type="text"
                    icon={<CloseOutlined/>}
                    aria-label="Закрыть плеер"
                    onClick={onClose}
                />
            </div>
        </>
    );
}

export function CallsPage() {
    const {currentWorkspaceId, canViewCalls} = useCurrentWorkspace();
    const queryClient = useQueryClient();
    const accountsQuery = useAvitoProjectsQuery();
    const [accountId, setAccountId] = useState<number | null>(null);
    const [week, setWeek] = useState(() =>
        dayjs().tz("Europe/Moscow").locale("ru"),
    );
    const [search, setSearch] = useState("");
    const [activeSearch, setActiveSearch] = useState("");
    const [playbackSpeed, setPlaybackSpeed] = useState(1);
    const [loadedAudio, setLoadedAudio] = useState<LoadedAudio | null>(null);
    const [loadingAudioId, setLoadingAudioId] = useState<number | null>(null);
    const [unavailableAudioId, setUnavailableAudioId] = useState<number | null>(
        null,
    );
    const audioRequestRef = useRef<AbortController | null>(null);
    const lastSyncVersion = useRef<{ scope: string; version: string } | null>(
        null,
    );
    const [reportTarget, setReportTarget] = useState<{
        call: CallRecord;
        workspaceId: number;
        accountId: number;
        weekStartKey: string;
    } | null>(null);
    const accounts = accountsQuery.data ?? [];
    const selectedAccountId = accounts.some((account) => account.id === accountId)
        ? accountId
        : (accounts[0]?.id ?? null);
    const todayKey = dayjs().tz("Europe/Moscow").format("YYYY-MM-DD");
    const weekStartKey = week.startOf("isoWeek").format("YYYY-MM-DD");
    const days = Array.from({length: 7}, (_, index) =>
        dayjs(weekStartKey)
            .add(6 - index, "day")
            .locale("ru"),
    ).filter((day) => day.format("YYYY-MM-DD") <= todayKey);

    useEffect(() => {
        const timeout = window.setTimeout(
            () => setActiveSearch(search.trim()),
            250,
        );
        return () => window.clearTimeout(timeout);
    }, [search]);

    const syncStatusQuery = useQuery({
        queryKey: ["calls-sync-status", currentWorkspaceId, selectedAccountId],
        queryFn: () => {
            if (currentWorkspaceId === null || selectedAccountId === null) {
                throw new Error("Кабинет или аккаунт не выбран.");
            }
            return getCallsSyncStatus(currentWorkspaceId, selectedAccountId);
        },
        enabled:
            canViewCalls && currentWorkspaceId !== null && selectedAccountId !== null,
        refetchInterval: 60_000,
    });

    const syncStatus = syncStatusQuery.data;
    useEffect(() => {
        if (
            !syncStatus ||
            currentWorkspaceId === null ||
            selectedAccountId === null
        )
            return;

        const scope = `${currentWorkspaceId}:${selectedAccountId}`;
        const version = `${syncStatus.last_synced_at}:${syncStatus.backfill_complete}:${syncStatus.classification_complete}`;
        const previous = lastSyncVersion.current;
        if (previous?.scope === scope && previous.version !== version) {
            void queryClient.invalidateQueries({
                queryKey: ["calls", currentWorkspaceId, selectedAccountId],
            });
        }
        lastSyncVersion.current = {scope, version};
    }, [currentWorkspaceId, selectedAccountId, queryClient, syncStatus]);
    const syncStatusTitle = syncStatus?.last_error
        ? "Ошибка синхронизации звонков"
        : syncStatus?.phase === "classifying"
            ? "Идёт классификация звонков"
            : syncStatus?.phase === "syncing" || syncStatus?.is_syncing
                ? "История звонков синхронизируется"
                : syncStatus?.backfill_complete && syncStatus.classification_complete
                    ? "История звонков загружена, типы определены"
                    : syncStatus?.backfill_complete
                        ? "История загружена, ожидается классификация"
                        : syncStatus?.last_synced_at
                            ? "История звонков загружена частично"
                            : "Синхронизация ещё не запускалась";

    useEffect(() => {
        setReportTarget(null);
        setLoadedAudio(null);
        setLoadingAudioId(null);
        setUnavailableAudioId(null);

        return () => {
            audioRequestRef.current?.abort();
            audioRequestRef.current = null;
        };
    }, [currentWorkspaceId, selectedAccountId, weekStartKey]);

    async function loadAudio(call: CallRecord) {
        if (currentWorkspaceId === null) return;

        audioRequestRef.current?.abort();
        const controller = new AbortController();
        audioRequestRef.current = controller;

        setLoadingAudioId(call.id);
        setUnavailableAudioId(null);
        setLoadedAudio(null);

        try {
            const blob = await getCallAudio(
                currentWorkspaceId,
                call.id,
                controller.signal,
            );
            if (controller.signal.aborted) return;

            const url = URL.createObjectURL(blob);
            controller.signal.addEventListener(
                "abort",
                () => URL.revokeObjectURL(url),
                {once: true},
            );

            setLoadedAudio({call, url});
        } catch (error) {
            if (controller.signal.aborted || axios.isCancel(error)) return;

            if (axios.isAxiosError(error) && error.response?.status === 404) {
                setUnavailableAudioId(call.id);
            } else {
                message.error("Не удалось загрузить аудио.");
            }
        } finally {
            if (audioRequestRef.current === controller) {
                setLoadingAudioId(null);
            }
        }
    }

    const columns: TableProps<CallRecord>["columns"] = [
        {
            title: "Время",
            dataIndex: "occurred_at",
            render: (value: string) =>
                dayjs(value).tz("Europe/Moscow").format("HH:mm"),
            width: 100,
        },
        {
            title: "Номер",
            dataIndex: "buyer_phone",
            width: 220,
            render: (value: string) => {
                const phone = formatPhone(value);

                return (
                    <Space size={4}>
                        <Text style={{fontWeight: "bold"}}>{phone}</Text>
                        {value.trim() && (
                            <Button
                                type="text"
                                size="small"
                                icon={<CopyOutlined/>}
                                aria-label="Скопировать номер"
                                title="Скопировать номер"
                                onClick={() => void copyPhone(phone)}
                            />
                        )}
                    </Space>
                );
            },
        },
        {
            title: "Тип",
            width: 150,
            dataIndex: "call_type",
            render: (value: CallRecord["call_type"]) =>
                value === "new"
                    ? "Новый"
                    : value === "repeat"
                        ? "Повторный"
                        : "Неизвестно",
        },
        {
            title: "Длительность",
            width: 150,
            dataIndex: "talk_duration",
            render: (seconds: number) => (
                <Tag
                    variant="outlined"
                    color={seconds < 40 ? "red" : seconds <= 90 ? "blue" : "green"}>
                    {formatSeconds(seconds)}
                </Tag>
            ),
        },
        {
            title: "Объявление",
            dataIndex: "listing",
            render: (listing: CallRecord["listing"]) =>
                listing ? (
                    <div>
                        <div>{listing.title || "Без названия"}</div>
                        <Text type="secondary">ID Авито: {listing.avito_id}</Text>
                    </div>
                ) : (
                    "Неизвестно"
                ),
        },
        {
            title: "Действия",
            key: "actions",
            width: 200,
            render: (_, call) => {
                const hasReport = Boolean(call.report_text);
                const reportLabel = hasReport
                    ? "Редактировать отчет"
                    : "Добавить отчет";

                return (
                    <Space size={8}>
                        {unavailableAudioId === call.id ? (
                            <Text type="secondary">Аудио пока недоступно</Text>
                        ) : (
                            <Button
                                color="blue"
                                variant="outlined"
                                icon={<CaretRightOutlined aria-hidden="true"/>}
                                loading={loadingAudioId === call.id}
                                onClick={() => void loadAudio(call)}>
                                Послушать
                            </Button>
                        )}

                        <Button
                            color={hasReport ? "green" : "blue"}
                            variant="solid"
                            aria-label={reportLabel}
                            title={reportLabel}
                            icon={
                                hasReport ? (
                                    <EditOutlined aria-hidden="true"/>
                                ) : (
                                    <FileTextOutlined aria-hidden="true"/>
                                )
                            }
                            onClick={() => {
                                if (currentWorkspaceId === null || selectedAccountId === null) {
                                    return;
                                }

                                setReportTarget({
                                    call,
                                    workspaceId: currentWorkspaceId,
                                    accountId: selectedAccountId,
                                    weekStartKey,
                                });
                            }}
                        />
                    </Space>
                );
            },
        },
    ];

    if (!canViewCalls) {
        return <Result status="403" title="Нет доступа к звонкам"/>;
    }

    return (
        <>
            <Title level={3}>Звонки</Title>
            <div className={styles.filters}>
                <Select
                    style={{width: 240}}
                    placeholder="Avito-аккаунт"
                    loading={accountsQuery.isLoading}
                    value={selectedAccountId ?? undefined}
                    options={accounts.map((account) => ({
                        label: account.name,
                        value: account.id,
                    }))}
                    onChange={(value) => {
                        setAccountId(value);
                    }}
                />
                <DatePicker
                    picker="week"
                    locale={ruDatePickerLocale}
                    value={week}
                    allowClear={false}
                    inputReadOnly
                    format={(value) => {
                        const start = value.startOf("isoWeek");
                        return `${start.format("DD.MM.YYYY")} – ${start.add(6, "day").format("DD.MM.YYYY")}`;
                    }}
                    onChange={(value) => {
                        if (value) {
                            setWeek(value.locale("ru"));
                        }
                    }}
                />

                <Input.Search
                    className={styles.search}
                    aria-label="Поиск по номеру или объявлению"
                    placeholder="Поиск по номеру или объявлению"
                    allowClear
                    maxLength={100}
                    value={search}
                    onChange={(event) => setSearch(event.target.value)}
                />
            </div>

            {syncStatusQuery.isError && (
                <Alert
                    type="warning"
                    showIcon
                    message="Не удалось получить статус синхронизации"
                    style={{marginBottom: 16}}
                />
            )}

            {syncStatus && (
                <Alert
                    type={
                        syncStatus.last_error
                            ? "error"
                            : syncStatus.backfill_complete &&
                            syncStatus.classification_complete &&
                            !syncStatus.phase
                                ? "success"
                                : "info"
                    }
                    showIcon
                    title={
                        <Space size={8} wrap>
                            <span>{syncStatusTitle}</span>
                            {syncStatus.last_error && (
                                <Text className={styles.syncMeta}>{syncStatus.last_error}</Text>
                            )}
                            {syncStatus.last_synced_at && (
                                <Text type="secondary" className={styles.syncMeta}>
                                    Проверено{" "}
                                    {dayjs(syncStatus.last_synced_at)
                                        .tz("Europe/Moscow")
                                        .format("DD.MM.YYYY HH:mm")}
                                </Text>
                            )}
                        </Space>
                    }
                    className={styles.compactAlert}
                    action={
                        <Button size="small" onClick={() => void syncStatusQuery.refetch()}>
                            Обновить
                        </Button>
                    }
                    style={{marginBottom: 16}}
                />
            )}

            {currentWorkspaceId !== null && selectedAccountId !== null && (
                <WeekCalls
                    key={`${currentWorkspaceId}:${selectedAccountId}:${weekStartKey}:${activeSearch}`}
                    days={days}
                    workspaceId={currentWorkspaceId}
                    accountId={selectedAccountId}
                    search={activeSearch}
                    columns={columns}
                    activeCallId={loadedAudio?.call.id ?? null}
                    reportCallId={
                        reportTarget &&
                        reportTarget.workspaceId === currentWorkspaceId &&
                        reportTarget.accountId === selectedAccountId &&
                        reportTarget.weekStartKey === weekStartKey
                            ? reportTarget.call.id
                            : null
                    }
                    onCloseReport={() =>
                        setReportTarget((current) =>
                            current === reportTarget ? null : current,
                        )
                    }
                />
            )}

            {loadedAudio && (
                <CallsAudioPlayer
                    loadedAudio={loadedAudio}
                    speed={playbackSpeed}
                    onSpeedChange={setPlaybackSpeed}
                    onClose={() => {
                        audioRequestRef.current?.abort();
                        setLoadedAudio(null);
                    }}
                />
            )}
        </>
    );
}
