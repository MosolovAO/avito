import React from 'react'
import {useQuery, useMutation, useQueryClient} from '@tanstack/react-query'
import {message} from 'antd'
import {getProjects, deleteProject} from '../../shared/api/projects'
import type {Project} from '../../entities/project'
import {ProjectList} from "../../widgets/project/ProjectList";


export const ProjectsPage: React.FC = () => {

    const queryClient = useQueryClient()

    const {data: projects = [], isLoading} = useQuery<Project[]>({
        queryKey: ['projects'],
        queryFn: getProjects,
    })

    const deleteMutation = useMutation({
        mutationFn: (id: number) => deleteProject(id),
        onSuccess: async () => {
            await queryClient.invalidateQueries({queryKey: ['projects']})
            message.success("Проект удален")
        },
        onError: () => {
            message.error('Ошибка удаления')
        }
    })


    return (
        <ProjectList
            projects={projects}
            loading={isLoading}
            onDelete={deleteMutation.mutate}
        />
    )
}