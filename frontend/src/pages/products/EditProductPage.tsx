import React from "react";
import {useNavigate, useParams} from "react-router-dom";
import {useMutation, useQuery, useQueryClient} from '@tanstack/react-query'
import {Typography, Card, message, Spin} from 'antd'
import {ProductForm} from '../../features/product/ProductForm'
import {getProduct, updateProduct, getProductCategories} from '../../shared/api/products'
import type {ProductFormData, Product} from '../../entities/product'
import {useAvitoProjectsQuery} from '../../features/avito'

const {Title} = Typography

// Нормализация описания
const normalizeDescriptions = (description: Product['descriptions']): string[] => {
    if (Array.isArray(description)) {
        return description
    }

    return Object.values(description ?? {})
}

// Подготовка данных для формы
const mapProductToFormData = (
    product: Product,
): Partial<ProductFormData> => ({
    name: product.name,
    price_randomization_enabled: product.price_randomization_enabled,
    titles: product.titles,
    main_images: product.main_images,
    additional_images: product.additional_images,
    main_image_asset_ids: product.main_image_asset_ids,
    additional_image_asset_ids: product.additional_image_asset_ids,
    descriptions: normalizeDescriptions(product.descriptions),
    addresses: product.addresses,
    category: product.category,
    listingfee: product.base_data?.ListingFee,
    email: product.base_data?.EMail,
    contactphone: product.base_data?.ContactPhone,
    managername: product.base_data?.ManagerName,
    avitostatus: product.base_data?.AvitoStatus,
    companyname: product.base_data?.CompanyName,
    contactmethod: product.base_data?.ContactMethod,
    adtype: product.base_data?.AdType,
    availability: product.base_data?.Availability,
    price: product.price,
    price_min: product.price_min,
    price_max: product.price_max,
    price_step: product.price_step,
    avito_account_ids:
        product.avito_account_ids
        ?? product.avito_accounts?.map((account) => account.id)
        ?? [],
    options: product.options ?? [],
    schedule: product.schedule ?? {},
})

export const EditProductPage: React.FC = () => {
    const {id} = useParams<{ id: string }>()
    const navigate = useNavigate()
    const queryClient = useQueryClient()

    const {data: categories = [], isLoading: categoriesLoading} = useQuery({
        queryKey: ['product-categories'],
        queryFn: getProductCategories,
        staleTime: 5 * 60 * 1000,
    })

    // Загрузка продукта
    const {data: productData, isLoading: productLoading} = useQuery({
        queryKey: ['product', id],
        queryFn: () => getProduct(Number(id)),
        enabled: Boolean(id),
        select: mapProductToFormData
    })

    const avitoAccountsQuery = useAvitoProjectsQuery()
    const avitoAccounts = avitoAccountsQuery.data ?? []

    // Мутация для обновления продукта
    const updateMutation = useMutation({
        mutationFn: (data: ProductFormData) => updateProduct(Number(id), data),
        onSuccess: async () => {
            await queryClient.invalidateQueries({queryKey: ['products']})
            await queryClient.invalidateQueries({queryKey: ['product', id]})
            message.success('Продукт успешно обновлен')
            navigate('/products')
        },
        onError: (error: any) => {
            message.error(error.response?.data?.error || 'Ошибка обновления продукта')
        }
    })

    const handleSubmit = async (data: ProductFormData) => {
        await updateMutation.mutateAsync(data)
    }

    const handleCancel = () => {
        navigate('/products')
    }

    const isLoading = (
        productLoading ||
        avitoAccountsQuery.isLoading ||
        !productData ||
        categoriesLoading
    )

    if (isLoading) {
        return (
            <div style={{padding: '24px', textAlign: 'center'}}>
                <Spin size="large"/>
            </div>
        )
    }

    return (
        <div style={{padding: ''}}>
            <Title level={2}>Редактировать продукт</Title>
            <Card>
                <ProductForm
                    avitoAccounts={avitoAccounts}
                    categories={categories}
                    initialData={productData || undefined}
                    onSubmit={handleSubmit}
                    onCancel={handleCancel}
                    loading={updateMutation.isPending}
                />
            </Card>
        </div>
    )
}
