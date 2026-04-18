import React from 'react'
import {Form, Select, Card} from 'antd'
import type {Project} from '../../../../entities/project'

interface ProjectsSectionProps {
    projects: Project[]
}

export const ProjectsSection: React.FC<ProjectsSectionProps> = ({projects}) => {
    return (
        <Card title="📁 Проекты" style={{marginBottom: '16px'}}>
            <Form.Item
                name="projects"
                label="Выберите проекты"
                rules={[{required: true, message: 'Выберите хотя бы один проект'}]}
            >
                <Select mode="multiple" placeholder="Выберите проекты">
                    {projects.map((project) => (
                        <Select.Option key={project.id} value={project.id}>
                            {project.project_name}
                        </Select.Option>
                    ))}
                </Select>
            </Form.Item>
        </Card>
    )
}