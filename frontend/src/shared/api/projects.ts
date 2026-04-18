import api from "./axios.ts";
import type { Project } from '../../entities/project'

// Получние всех проектов
export const getProjects = async (): Promise<Project[]> => {
    const response = await api.get('/api/projects/')
    return response.data
}

// Получение одного проекта
export const getProject = async (id: number): Promise<Project> => {
    const response = await api.get(`/api/projects/${id}/`)
    return response.data
}

// Создание проекта
export const createProject = async (data: {project_name: string}): Promise<Project> => {
    const response = await api.post('/api/projects/', data)
    return response.data
}

// Обновление проекта
export const updateProject = async (id: number, data: Partial<Project>): Promise<Project> => {
    const response = await api.patch(`/api/projects/${id}/`, data)
    return response.data
}

// Удаление проекта
export const deleteProject = async (id: number): Promise<void> => {
    await api.delete(`/api/projects/${id}/`)
}