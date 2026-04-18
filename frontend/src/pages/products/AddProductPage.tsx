import React from 'react'
import {useMutation, useQuery, useQueryClient} from '@tanstack/react-query'
import {Typography, Card, message, Spin} from 'antd'
import {useNavigate} from 'react-router-dom'
import {ProductForm} from '../../features/product/ProductForm'
import {getProjects, getProductOptions, createProduct} from '../../shared/api/products'
import type {ProductFormData} from '../../entities/product'

const {Title} = Typography

export const AddProductPage: React.FC = () => {
    const navigate = useNavigate()
    const queryClient = useQueryClient()

    // Загрущка проектов
    const {data: projects = [], isLoading: projectsLoading} = useQuery({
        queryKey: ['projects'],
        queryFn: getProjects,
    })

    // Загрузка опций
    const {data: options = [], isLoading: optionsLoading} = useQuery({
        queryKey: ['options'],
        queryFn: getProductOptions,
    })

    // Мутация для создания продукта
    const createMutation = useMutation({
        mutationFn: (data: ProductFormData) => createProduct(data),
        onSuccess: () => {
            queryClient.invalidateQueries({queryKey: ['products']})
            message.success('Продукт успешно создан')
            navigate('/products')
        },
        onError: (error: any) => {
            message.error(error.response?.data?.error || 'Ошибка создания продукта')
        }
    })

    const handleSubmit = (data: ProductFormData) => {
        createMutation.mutate(data)
    }

    const handleCancel = () => {
        navigate('/products')
    }

    const isLoading = projectsLoading || optionsLoading || createMutation.isPending

    if (isLoading) {
        return (
            <div style={{padding: '24px', textAlign: 'center'}}>
                <Spin size="large"/>
            </div>
        )
    }
    return (
        <div style={{padding: '24px'}}>
            <Title level={2}>Добавить продукт</Title>
            <Card>
                <ProductForm
                    projects={projects}
                    options={options}
                    onSubmit={handleSubmit}
                    onCancel={handleCancel}
                    loading={createMutation.isPending}
                />
            </Card>
        </div>
    )

}
