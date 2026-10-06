import api from "./axios";
import type { PaginatedResponse } from "./pagination";
import { getWorkspaceHeaders } from "./workspaceHeaders";

export interface CallRecord {
  id: number;
  external_id: string;
  occurred_at: string;
  buyer_phone: string;
  talk_duration: number;
  waiting_duration: number;
  report_text: string;
  is_missed: boolean | null;
  call_type: "new" | "repeat" | null;
  listing: {
    id: number | null;
    avito_id: string;
    title: string | null;
    url: string | null;
  } | null;
}

interface GetCallsRequest {
  workspaceId: number;
  avitoAccountId: number;
  date: string;
  page: number;
  pageSize?: number;
  search?: string;
  signal?: AbortSignal;
}

export interface CallDailyReport {
  avito_account_id: number;
  account_name: string;
  date: string;
  report_count: number;
  report_text: string;
}

interface GetCallDailyReportRequest {
  workspaceId: number;
  avitoAccountId: number;
  date: string;
  signal?: AbortSignal;
}

export async function getCalls({
  workspaceId,
  avitoAccountId,
  date,
  page,
  pageSize,
  search,
  signal,
}: GetCallsRequest): Promise<PaginatedResponse<CallRecord>> {
  const response = await api.get<PaginatedResponse<CallRecord>>("/api/calls/", {
    headers: getWorkspaceHeaders(workspaceId),
    signal,
    params: {
      avito_account_id: avitoAccountId,
      date,
      page,
      page_size: pageSize,
      search,
    },
  });
  return response.data;
}

export async function getCallAudio(
  workspaceId: number,
  callId: number,
  signal?: AbortSignal,
): Promise<Blob> {
  const response = await api.get<Blob>(`/api/calls/${callId}/audio/`, {
    headers: getWorkspaceHeaders(workspaceId),
    responseType: "blob",
    signal,
  });
  return response.data;
}

export interface CallSyncStatus {
  last_synced_at: string | null;
  backfill_complete: boolean;
  classification_complete: boolean;
  is_syncing: boolean;
  phase: "syncing" | "classifying" | null;
  last_error: string;
}

export async function getCallsSyncStatus(
  workspaceId: number,
  avitoAccountId: number,
): Promise<CallSyncStatus> {
  const response = await api.get<CallSyncStatus>("/api/calls/sync-status/", {
    headers: getWorkspaceHeaders(workspaceId),
    params: { avito_account_id: avitoAccountId },
  });
  return response.data;
}

export async function saveCallReport(
  workspaceId: number,
  callId: number,
  reportText: string,
): Promise<{ report_text: string }> {
  const response = await api.put<{ report_text: string }>(
    `/api/calls/${callId}/report/`,
    { report_text: reportText },
    { headers: getWorkspaceHeaders(workspaceId) },
  );
  return response.data;
}

export async function getCallDailyReport({
  workspaceId,
  avitoAccountId,
  date,
  signal,
}: GetCallDailyReportRequest): Promise<CallDailyReport> {
  const response = await api.get<CallDailyReport>("/api/calls/reports/daily/", {
    headers: getWorkspaceHeaders(workspaceId),
    params: { avito_account_id: avitoAccountId, date },
    signal,
  });
  return response.data;
}
