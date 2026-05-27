import React from 'react'
import {useMutation, useQuery, useQueryClient} from '@tanstack/react-query'
import {Typography, Card, message, Spin} from 'antd'
import {useNavigate} from 'react-router-dom'
import {ProductForm} from '../../features/product/ProductForm'
import {createProduct, getProductCategories} from '../../shared/api/products'
import type {ProductFormData} from '../../entities/product'
import {useAvitoProjectsQuery} from '../../features/avito'
import { getApiErrorMessage } from '../../shared/api/errors'


const {Title} = Typography

export const AddProductPage: React.FC = () => {
    const navigate = useNavigate()
    const queryClient = useQueryClient()

    const {data: categories = [], isLoading: categoriesLoading} = useQuery({
        queryKey: ['product-categories'],
        queryFn: getProductCategories,
        staleTime: 5 * 60 * 1000,
    })

    const avitoAccountsQuery = useAvitoProjectsQuery()
    const avitoAccounts = avitoAccountsQuery.data ?? []

    // Мутация для создания продукта
    const createMutation = useMutation({
        mutationFn: (data: ProductFormData) => createProduct(data),
        onSuccess: () => {
            queryClient.invalidateQueries({queryKey: ['products']})
            message.success('Продукт успешно создан')
            navigate('/products')
        },
        onError: (error: any) => {
            message.error(getApiErrorMessage(error, 'Ошибка создания продукта'))
        }
    })

    const handleSubmit = async (data: ProductFormData) => {
        await createMutation.mutateAsync(data)
    }

    const handleCancel = () => {
        navigate('/products')
    }

    const isLoading = avitoAccountsQuery.isLoading || categoriesLoading || createMutation.isPending

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
                    avitoAccounts={avitoAccounts}
                    categories={categories}
                    onSubmit={handleSubmit}
                    onCancel={handleCancel}
                    loading={createMutation.isPending}
                />
            </Card>
        </div>
    )

}
