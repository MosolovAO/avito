import {Button, Popconfirm, Space, Table, Typography} from "antd";
import type {Project} from "../../entities/project";
import React from "react";
import {useNavigate} from "react-router-dom";
import {DeleteOutlined, EditOutlined, PlusOutlined} from "@ant-design/icons";

const {Title} = Typography

interface ProjectListProps {
    projects: Project[]
    loading: boolean
     onDelete: (id: number) => void
}

export const ProjectList: React.FC<ProjectListProps> = ({
                                                            projects,
                                                            loading,
                                                            onDelete,

                                                        }) => {
    const navigate = useNavigate()

    const columns = [
        {
            title: 'ID',
            dataIndex: 'id',
            key: 'id',
            width: 60,
        },
        {
            title: 'Название',
            dataIndex: 'project_name',
            key: 'project_name'
        },
        {
            title: 'Действие',
            key: 'actions',
            width: 150,
            render: (_: any, record: Project) => (
                <Space size="small">
                    <Button
                        icon={<EditOutlined/>}
                        onClick={() => navigate(`/projects/${record.id}/edit`)}
                    />

                    <Popconfirm
                        title="Удалить проект?"
                        onConfirm={() => onDelete(record.id)}
                        okText="Да"
                        cancelText="Отмена"
                    >
                        <Button danger icon={<DeleteOutlined/>}/>

                    </Popconfirm>
                </Space>
            ),
        },
    ]

    return (

        <div style={{padding: '24px'}}>
            <div style={{display: 'flex', justifyContent: 'space-between', marginBottom: '16px'}}>
                <Title level={2}>Проекты</Title>
                <Button type="primary" icon={<PlusOutlined/>} onClick={() => navigate('/projects/add')}>
                    Добавить проект
                </Button>
            </div>
            <Table
                columns={columns}
                dataSource={projects}
                rowKey="id"
                loading={loading}
                pagination={{pageSize: 10}}
            />
        </div>
    )

}