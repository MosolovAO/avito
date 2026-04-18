import React, {useEffect, useState} from 'react'
import {useMutation, useQuery, useQueryClient} from '@tanstack/react-query'
import {Typography, Card, message, Spin} from 'antd'
import {useNavigate, useParams} from 'react-router-dom'
import {ProjectForm} from '../../features/project'
import {getProject, updateProject} from '../../shared/api/projects'
import type {Project} from '../../entities/project'

const {Title} = Typography

export const EditProjectPage: React.FC = () => {
    const {id} = useParams<{ id: string }>()
    const navigate = useNavigate()
    const queryClient = useQueryClient()
    const [projectData, setProjectData] = useState<Partial<Project> | null>()

    const {data: project, isLoading} = useQuery<Project>({
        queryKey: ['project', id],
        queryFn: () => getProject(Number(id)),
        enabled: !!id
    })

    useEffect(() => {
        if (project) {
            setProjectData({project_name: project.project_name})
        }
    }, [project])

    const updateMutation = useMutation({
        mutationFn: (data: Partial<Project>) => updateProject(Number(id), data),
        onSuccess: async () => {
            await queryClient.invalidateQueries({queryKey: ['projects']})
            message.success('Проект успешно обновлен')
            navigate('/projects')
        },
        onError: (error: any) => {
            message.error(error.response?.data?.error || 'Ошибка обновления продукта')
        }
    })

    const handleSubmit = (data: {project_name: string}) => {
        updateMutation.mutate(data)
    }

    const handleCancel = () => {
        navigate('/projects')
    }

    if (isLoading || !projectData) {
        return (
            <div style={{padding: '24px', textAlign: 'center'}}>
                <Spin size="large"/>
            </div>
        )
    }

    return (
        <div style={{padding: '24px'}}>
            <Title level={2}>Редактировать проект</Title>
            <Card>
                <ProjectForm
                    initialData={projectData}
                    onSubmit={handleSubmit}
                    onCancel={handleCancel}
                    loading={updateMutation.isPending}
                />
            </Card>
        </div>
    )

}