import React from 'react'
import {useMutation, useQueryClient} from '@tanstack/react-query'
import {Typography, Card, message} from 'antd'
import {useNavigate} from 'react-router-dom'
import {ProjectForm} from '../../features/project'
import {createProject} from '../../shared/api/projects'

const { Title } = Typography

export const AddProjectPage: React.FC = () => {
    const navigate = useNavigate()
    const queryClient = useQueryClient()

    const createMutation = useMutation({
        mutationFn: (data: {project_name: string }) => createProject(data),
        onSuccess: async () => {
            await queryClient.invalidateQueries({ queryKey: ['projects']})
            navigate('/projects')
        },
        onError: (error: any) => {
            message.error(error.response?.data?.error || 'Ошибка создания проекта')
        },
    })

    const handleSubmit = (data: { project_name: string}) => {
        createMutation.mutate(data)
    }

    const handleCancel = () => {
        navigate('/projects')
    }

    return (
        <div style={{ padding: '24px'}}>
            <Title level={2}>Добавить проект</Title>
            <Card>
                <ProjectForm
                    onSubmit={handleSubmit}
                    onCancel={handleCancel}
                    loading={createMutation.isPending}
                />
            </Card>
        </div>
    )
}