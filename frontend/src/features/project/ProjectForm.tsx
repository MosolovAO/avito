import React from "react";
import {Form, Input, Button, Space} from 'antd'
import type {Project} from '../../entities/project'

interface ProjectFormProps {
    initialData?: Partial<Project>
    onSubmit: (data: { project_name: string }) => void
    onCancel: () => void
    loading?: boolean
}

export const ProjectForm: React.FC<ProjectFormProps> = ({
                                                            initialData,
                                                            onSubmit,
                                                            onCancel,
                                                            loading = false,
                                                        }) => {
    const [form] = Form.useForm()

    const handleSubmit = async () => {
        try {
            const values = await form.validateFields()
            onSubmit(values)
        } catch (error) {
            console.error('Ошибка валидации', error)
        }
    }

    return (
        <Form form={form} layout={"vertical"} initialValues={initialData}>
            <Form.Item
                name="project_name"
                label="Название проекта"
                rules={[{required: true, message: 'Введите название проекта'}]}
            >
                <Input placeholder="Например: Основной проект"/>

            </Form.Item>

            <Space>
                <Button type="primary" onClick={handleSubmit} loading={loading}>
                    Сохранить
                </Button>
                <Button onClick={onCancel}>
                    Отмена
                </Button>
            </Space>
        </Form>
    )
}