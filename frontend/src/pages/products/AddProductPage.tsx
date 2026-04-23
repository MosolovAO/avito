import React from 'react'
import {useMutation, useQuery, useQueryClient} from '@tanstack/react-query'
import {Typography, Card, message, Spin} from 'antd'
import {useNavigate} from 'react-router-dom'
import {ProductForm} from '../../features/product/ProductForm'
import {getProjects, createProduct, getProductCategories} from '../../shared/api/products'
import type {ProductFormData} from '../../entities/product'

const {Title} = Typography

export const AddProductPage: React.FC = () => {
    const navigate = useNavigate()
    const queryClient = useQueryClient()

    const {data: categories = [], isLoading: categoriesLoading} = useQuery({
        queryKey: ['product-categories'],
        queryFn: getProductCategories,
        staleTime: 5 * 60 * 1000,
    })

    // Загрущка проектов
    const {data: projects = [], isLoading: projectsLoading} = useQuery({
        queryKey: ['projects'],
        queryFn: getProjects,
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

    const handleSubmit = async (data: ProductFormData) => {
        await createMutation.mutateAsync(data)
    }

    const handleCancel = () => {
        navigate('/products')
    }

    const isLoading = projectsLoading || categoriesLoading || createMutation.isPending

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
                    categories={categories}
                    onSubmit={handleSubmit}
                    onCancel={handleCancel}
                    loading={createMutation.isPending}
                />
            </Card>
        </div>
    )

}
