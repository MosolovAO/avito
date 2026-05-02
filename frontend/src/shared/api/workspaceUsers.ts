import api from "./axios";
import type { AuthUser } from "./auth";
import { setAccessToken } from "./authToken";

export type WorkspaceRole =
  | "owner"
  | "admin"
  | "manager"
  | "analyst"
  | "viewer";

export type ManageableWorkspaceRole = Exclude<WorkspaceRole, "owner">;

export type WorkspaceMemberStatus = "active" | "invited" | "disabled";

export type WorkspaceInvitationStatus =
  | "pending"
  | "accepted"
  | "revoked"
  | "expired";

export interface WorkspaceSummary {
  id: number;
  name: string;
  slug: string;
}

export interface WorkspaceMember {
  id: number;
  user: AuthUser;
  role: WorkspaceRole;
  status: WorkspaceMemberStatus;
  permissions: string[];
  joined_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface WorkspaceInvitation {
  id: number;
  workspace: WorkspaceSummary;
  email: string;
  role: ManageableWorkspaceRole;
  status: WorkspaceInvitationStatus;
  invited_by: AuthUser;
  expires_at: string;
  accepted_at: string | null;
  is_expired: boolean;
  created_at: string;
  updated_at: string;
}

export interface WorkspaceInvitationWithAcceptUrl extends WorkspaceInvitation {
  accept_url: string;
}

export interface PublicWorkspaceInvitation {
  workspace: WorkspaceSummary;
  email: string;
  role: ManageableWorkspaceRole;
  status: WorkspaceInvitationStatus;
  expires_at: string;
}

export interface CreateWorkspaceInvitationRequest {
  email: string;
  role: ManageableWorkspaceRole;
}

export interface UpdateWorkspaceMemberRoleRequest {
  role: ManageableWorkspaceRole;
}

export interface RegisterByInvitationRequest {
  password: string;
  first_name?: string;
  last_name?: string;
}

export interface AcceptWorkspaceInvitationResponse {
  user: AuthUser;
  workspace: WorkspaceSummary;
  membership: WorkspaceMember;
}

export interface RegisterByInvitationResponse extends AcceptWorkspaceInvitationResponse {
  access: string;
}

export const manageableWorkspaceRoles: ManageableWorkspaceRole[] = [
  "admin",
  "manager",
  "analyst",
  "viewer",
];

export const workspaceMembersKeys = {
  all: ["workspace-members"] as const,
  list: (workspaceId: number) =>
    [...workspaceMembersKeys.all, workspaceId] as const,
};

export const workspaceInvitationsKeys = {
  all: ["workspace-invitations"] as const,
  list: (workspaceId: number) =>
    [...workspaceInvitationsKeys.all, workspaceId] as const,
  detail: (token: string) =>
    [...workspaceMembersKeys.all, "public", token] as const,
};

export const getWorkspaceMembers = async (
  workspaceId: number,
): Promise<WorkspaceMember[]> => {
  const response = await api.get<WorkspaceMember[]>(
    `/api/workspaces/${workspaceId}/members/`,
  );

  return response.data;
};

export const updateWorkspaceMemberRole = async (
  workspaceId: number,
  membershipId: number,
  data: UpdateWorkspaceMemberRoleRequest,
): Promise<WorkspaceMember> => {
  const response = await api.patch<WorkspaceMember>(
    `/api/workspaces/${workspaceId}/members/${membershipId}/`,
    data,
  );

  return response.data;
};

export const disableWorkspaceMember = async (
  workspaceId: number,
  membershipId: number,
): Promise<WorkspaceMember> => {
  const response = await api.post<WorkspaceMember>(
    `/api/workspaces/${workspaceId}/members/${membershipId}/disable/`,
  );

  return response.data;
};

export const getWorkspaceInvitations = async (
  workspaceId: number,
): Promise<WorkspaceInvitation[]> => {
  const response = await api.get<WorkspaceInvitation[]>(
    `/api/workspaces/${workspaceId}/invites/`,
  );

  return response.data;
};

export const createWorkspaceInvitation = async (
  workspaceId: number,
  data: CreateWorkspaceInvitationRequest,
): Promise<WorkspaceInvitationWithAcceptUrl> => {
  const response = await api.post<WorkspaceInvitationWithAcceptUrl>(
    `/api/workspaces/${workspaceId}/invites/`,
    data,
  );

  return response.data;
};

export const revokeWorkspaceInvitation = async (
  workspaceId: number,
  invitationId: number,
): Promise<WorkspaceInvitation> => {
  const response = await api.post<WorkspaceInvitation>(
    `/api/workspaces/${workspaceId}/invites/${invitationId}/`,
  );

  return response.data;
};

export const getPublicWorkspaceInvitation = async (
  token: string,
): Promise<PublicWorkspaceInvitation> => {
  const response = await api.get<PublicWorkspaceInvitation>(
    `/api/workspace-invites/${token}/`,
  );

  return response.data;
};

export const acceptWorkspaceInvitation = async (
  token: string,
): Promise<AcceptWorkspaceInvitationResponse> => {
  const response = await api.post<AcceptWorkspaceInvitationResponse>(
    `/api/workspace-invites/${token}/accept/`,
  );

  return response.data;
};

export const registerByWorkspaceInvitation = async (
  token: string,
  data: RegisterByInvitationRequest,
): Promise<RegisterByInvitationResponse> => {
  const response = await api.post<RegisterByInvitationResponse>(
    `/api/workspace-invites/${token}/register/`,
    data,
  );

  setAccessToken(response.data.access);

  return response.data;
};
