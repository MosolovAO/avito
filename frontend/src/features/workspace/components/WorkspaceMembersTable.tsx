import React from "react";
import { Button, Popconfirm, Select, Space, Table, Tag, message } from "antd";
import type { TableProps } from "antd";
import { StopOutlined } from "@ant-design/icons";
import { useAuth } from "../../auth/model/AuthProvider";
import {
  useDisableWorkspaceMemberMutation,
  useUpdateWorkspaceMemberRoleMutation,
  useWorkspaceMembersQuery,
} from "../model/useWorkspaceUsersQueries";
import {
  manageableWorkspaceRoles,
  type ManageableWorkspaceRole,
  type WorkspaceMember,
  type WorkspaceMemberStatus,
  type WorkspaceRole,
} from "../../../shared/api/workspaceUsers";

interface WorkspaceMembersTableProps {
  workspaceId: number;
}

const roleLabels: Record<WorkspaceRole, string> = {
  owner: "Владелец",
  admin: "Администратор",
  manager: "Менеджер",
  analyst: "Аналитик",
  viewer: "Наблюдатель",
};

const statusLabels: Record<WorkspaceMemberStatus, string> = {
  active: "Активен",
  invited: "Приглашён",
  disabled: "Отключён",
};

const statusColors: Record<WorkspaceMemberStatus, string> = {
  active: "success",
  invited: "processing",
  disabled: "default",
};

export const WorkspaceMembersTable: React.FC<WorkspaceMembersTableProps> = ({
  workspaceId,
}) => {
  const { user } = useAuth();
  const { data: members = [], isLoading } =
    useWorkspaceMembersQuery(workspaceId);
  const updateRoleMutation = useUpdateWorkspaceMemberRoleMutation(workspaceId);
  const disableMemberMutation = useDisableWorkspaceMemberMutation(workspaceId);

  const handleRoleChange = async (
    membershipId: number,
    role: ManageableWorkspaceRole,
  ) => {
    try {
      await updateRoleMutation.mutateAsync({
        membershipId,
        data: { role },
      });
      message.success("Роль обновлена");
    } catch {
      message.error("Не удалось обновить роль");
    }
  };

  const handleDesable = async (membershipId: number) => {
    try {
      await disableMemberMutation.mutateAsync({ membershipId });
      message.success("Пользователь отключен");
    } catch {
      message.error("Не удалось отключить пользователя");
    }
  };

  const columns: TableProps<WorkspaceMember>["columns"] = [
    {
      title: "Пользователь",
      key: "user",
      render: (_, member) => (
        <Space direction="vertical" size={0}>
          <span>{member.user.email}</span>
          {(member.user.first_name || member.user.last_name) && (
            <span style={{ color: "rgba(0, 0, 0, 0.45)" }}>
              {[member.user.first_name, member.user.last_name]
                .filter(Boolean)
                .join("")}
            </span>
          )}
        </Space>
      ),
    },
    {
      title: "Роль",
      key: "role",
      width: 220,
      render: (_, member) => {
        
        const isDisabled = member.status !== "active";
        const role = member.role;

        if (role === "owner") {
          return <Tag color="gold"> {roleLabels.owner}</Tag>;
        }

        return (
          <Select<ManageableWorkspaceRole>
            value={role}
            style={{ width: 180 }}
            disabled={isDisabled}
            options={manageableWorkspaceRoles.map((role) => ({
              value: role,
              label: roleLabels[role],
            }))}
            loading={updateRoleMutation.isPending}
            onChange={(role) => {
              void handleRoleChange(member.id, role);
            }}
          />
        );
      },
    },
    {
      title: "Статус",
      dataIndex: "status",
      key: "status",
      width: 130,
      render: (status: WorkspaceMemberStatus) => (
        <Tag color={statusColors[status]}>{statusLabels[status]}</Tag>
      ),
    },
    {
      title: "Действия",
      key: "actions",
      width: 120,
      render: (_, member) => {
        const isOwner = member.role === "owner";
        const isCurrentUser = member.user.id === user?.id;
        const isDisabled = member.status !== "active";
        const disabled = isOwner || isCurrentUser || isDisabled;

        return (
          <Popconfirm
            title="Отключить пользователя?"
            okText="Отключить"
            cancelText="Отмена"
            disabled={disabled}
            onConfirm={() => {
              void handleDesable(member.id);
            }}>
            <Button
              danger
              icon={<StopOutlined />}
              disabled={disabled}
              loading={disableMemberMutation.isPending}
            />
          </Popconfirm>
        );
      },
    },
  ];

  return (
    <Table
      rowKey="id"
      columns={columns}
      dataSource={members}
      loading={isLoading}
      pagination={{ pageSize: 8 }}
    />
  );
};
