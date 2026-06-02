import React from "react";
import {
    Button,
    Popconfirm,
    Space,
    Table,
    Tag,
    Typography,
    message,
} from "antd";
import type {TableProps} from "antd";
import {StopOutlined} from "@ant-design/icons";
import {
    useRevokeWorkspaceInvitationMutation,
    useWorkspaceInvitationsQuery,
} from "../model/useWorkspaceUsersQueries";
import type {
    WorkspaceInvitation,
    WorkspaceInvitationStatus,
    WorkspaceRole,
} from "../../../shared/api/workspaceUsers";

interface WorkspaceInvitationsTableProps {
    workspaceId: number;
}

const {Text} = Typography;

const roleLabels: Record<WorkspaceRole, string> = {
    owner: "Владелец",
    admin: "Администратор",
    manager: "Менеджер",
    analyst: "Аналитик",
    viewer: "Наблюдатель",
};

const statusLabels: Record<WorkspaceInvitationStatus, string> = {
    pending: "Активно",
    accepted: "Принято",
    revoked: "Отозвано",
    expired: "Истекло",
};

const statusColors: Record<WorkspaceInvitationStatus, string> = {
    pending: "processing",
    accepted: "success",
    revoked: "default",
    expired: "warning",
};

const formatDate = (value: string): string => {
    return new Intl.DateTimeFormat("ru-RU", {
        day: "2-digit",
        month: "2-digit",
        year: "numeric",
    }).format(new Date(value));
};

export const WorkspaceInvitationsTable: React.FC<
    WorkspaceInvitationsTableProps
> = ({workspaceId}) => {
    const {data: invitations = [], isLoading} =
        useWorkspaceInvitationsQuery(workspaceId);
    const revokeInvitationMutation =
        useRevokeWorkspaceInvitationMutation(workspaceId);

    const handleRevoke = async (invitationId: number) => {
        try {
            await revokeInvitationMutation.mutateAsync({invitationId});
            message.success("Приглашение отозвано");
        } catch {
            message.error("Не удалось отозвать приглашение");
        }
    };

    const columns: TableProps<WorkspaceInvitation>["columns"] = [
        {
            title: "Email",
            dataIndex: "email",
            key: "email",
            render: (email: string) => <Text>{email}</Text>,
        },
        {
            title: "Роль",
            dataIndex: "role",
            key: "role",
            width: 150,
            render: (role: WorkspaceRole) => roleLabels[role],
        },
        {
            title: "Статус",
            dataIndex: "status",
            key: "status",
            width: 120,
            render: (status: WorkspaceInvitationStatus) => (
                <Tag color={statusColors[status]}>{statusLabels[status]}</Tag>
            ),
        },
        {
            title: "Истекает",
            dataIndex: "expires_at",
            key: "expires_at",
            width: 160,
            render: (expiresAt: string, invitation) => {
                const canRevoke = invitation.status === "pending";

                return (
                    <Space>
                        <Text>{formatDate(expiresAt)}</Text>

                        <Popconfirm
                            title="Отозвать приглашение?"
                            okText="Отозвать"
                            cancelText="Отмена"
                            disabled={!canRevoke}
                            onConfirm={() => {
                                void handleRevoke(invitation.id);
                            }}
                        >
                            <Button
                                danger
                                icon={<StopOutlined/>}
                                disabled={!canRevoke}
                                loading={revokeInvitationMutation.isPending}
                            />
                        </Popconfirm>
                    </Space>
                );
            },
        },
    ];

    return (
        <Table
            rowKey="id"
            columns={columns}
            dataSource={invitations}
            loading={isLoading}
            pagination={{pageSize: 8}}
        />
    );
};
