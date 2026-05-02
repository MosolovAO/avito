import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  createWorkspaceInvitation,
  disableWorkspaceMember,
  getWorkspaceInvitations,
  getWorkspaceMembers,
  revokeWorkspaceInvitation,
  updateWorkspaceMemberRole,
  workspaceInvitationsKeys,
  workspaceMembersKeys,
  type CreateWorkspaceInvitationRequest,
  type UpdateWorkspaceMemberRoleRequest,
} from "../../../shared/api/workspaceUsers";

interface WorkspaceMemberRoleMutationVariables {
  membershipId: number;
  data: UpdateWorkspaceMemberRoleRequest;
}

interface WorkspaceMemberIdMutationVariables {
  membershipId: number;
}

interface WorkspaceInvitationIdMutationVariables {
  invitationId: number;
}

const requireWorkspaceId = (workspaceId: number | null): number => {
  if (workspaceId === null) {
    throw new Error("Workspace is not selected");
  }

  return workspaceId;
};

export const useWorkspaceMembersQuery = (workspaceId: number | null) => {
  return useQuery({
    queryKey:
      workspaceId === null
        ? workspaceMembersKeys.all
        : workspaceMembersKeys.list(workspaceId),
    queryFn: () => getWorkspaceMembers(requireWorkspaceId(workspaceId)),
    enabled: workspaceId !== null,
  });
};

export const useWorkspaceInvitationsQuery = (workspaceId: number | null) => {
  return useQuery({
    queryKey:
      workspaceId === null
        ? workspaceInvitationsKeys.all
        : workspaceInvitationsKeys.list(workspaceId),
    queryFn: () => getWorkspaceInvitations(requireWorkspaceId(workspaceId)),
    enabled: workspaceId !== null,
  });
};

export const useUpdateWorkspaceMemberRoleMutation = (
  workspaceId: number | null,
) => {
  const QueryClient = useQueryClient();

  return useMutation({
    mutationFn: ({
      membershipId,
      data,
    }: WorkspaceMemberRoleMutationVariables) =>
      updateWorkspaceMemberRole(
        requireWorkspaceId(workspaceId),
        membershipId,
        data,
      ),
    onSuccess: () => {
      const resolvedWorkspaceId = requireWorkspaceId(workspaceId);

      void QueryClient.invalidateQueries({
        queryKey: workspaceMembersKeys.list(resolvedWorkspaceId),
      });
    },
  });
};

export const useDisableWorkspaceMemberMutation = (
  workspaceId: number | null,
) => {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ membershipId }: WorkspaceMemberIdMutationVariables) =>
      disableWorkspaceMember(requireWorkspaceId(workspaceId), membershipId),
    onSuccess: () => {
      const resolvedWorkspaceId = requireWorkspaceId(workspaceId);

      void queryClient.invalidateQueries({
        queryKey: workspaceMembersKeys.list(resolvedWorkspaceId),
      });
    },
  });
};

export const useCreateWorkspaceInvitationMutation = (
  workspaceId: number | null,
) => {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (data: CreateWorkspaceInvitationRequest) =>
      createWorkspaceInvitation(requireWorkspaceId(workspaceId), data),
    onSuccess: () => {
      const resolvedWorkspaceId = requireWorkspaceId(workspaceId);

      void queryClient.invalidateQueries({
        queryKey: workspaceInvitationsKeys.list(resolvedWorkspaceId),
      });
    },
  });
};

export const useRevokeWorkspaceInvitationMutation = (
    workspaceId: number | null,
) => {
    const queryClient = useQueryClient();

    return useMutation({
        mutationFn: ({invitationId}: WorkspaceInvitationIdMutationVariables) =>
            revokeWorkspaceInvitation(requireWorkspaceId(workspaceId), invitationId),
        onSuccess: () => {
            const resolvedWorkspaceId = requireWorkspaceId(workspaceId)

            void queryClient.invalidateQueries({
                queryKey: workspaceInvitationsKeys.list(resolvedWorkspaceId)
            })
        }
    })
}
