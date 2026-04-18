import React, {useEffect, useState} from "react";
import {useNavigate, useParams} from "react-router-dom";
import {useMutation, useQuery, useQueryClient} from '@tanstack/react-query'
import {Typography, Card, message, Spin} from 'antd'
import {ProductForm} from '../../features/product/ProductForm'
import {getProjects, getProductOptions, getProduct, updateProduct} from '../../shared/api/products'
import type {ProductFormData, Product} from '../../entities/product'


const {Title} = Typography

export const EditProductPage: React.FC = () => {
    const {id} = useParams<{ id: string }>()
    const navigate = useNavigate()
    const queryClient = useQueryClient()
    const [productData, setProductData] = useState<Partial<ProductFormData> | null>(null)


    // Загрузка продукта
    const {data: product, isLoading: productLoading} = useQuery<Product>({
        queryKey: ['product', id],
        queryFn: () => getProduct(Number(id)),
        enabled: !!id,
    })

    // Загрузка проектов
    const {data: projects = [], isLoading: projectsLoading} = useQuery({
        queryKey: ['projects'],
        queryFn: getProjects,
    })

    // Загрузка опций
    const {data: options = [], isLoading: optionsLoading} = useQuery({
        queryKey: ['options'],
        queryFn: getProductOptions
    })

    // Подготовка данных для формы
    useEffect(() => {
        if (product) {
            setProductData({
                titles: product.titles,
                main_images: product.main_images,
                additional_images: product.additional_images,
                descriptions: product.descriptions,
                addresses: product.addresses,
                category: product.category,
                listingfee: product.listingfee,
                email: product.email,
                contactphone: product.contactphone,
                managername: product.managername,
                avitostatus: product.avitostatus,
                companyname: product.companyname,
                contactmethod: product.contactmethod,
                adtype: product.adtype,
                availability: product.availability,
                price: product.price,
                price_min: product.price_min,
                price_max: product.price_max,
                price_step: product.price_step,
                projects: product.projects?.map(p => p.id) || [],
                options: [],
                schedule: product.schedule || {},
            })
        }
    }, [product])

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

    const handleSubmit = (data: ProductFormData) => {
        updateMutation.mutate(data)
    }

    const handleCancel = () => {
        navigate('/products')
    }

    const isLoading = productLoading || projectsLoading || optionsLoading || !productData

    if (isLoading) {
        return (
            <div style={{padding: '24px', textAlign: 'center'}}>
                <Spin size="large"/>
            </div>
        )
    }

    return (
        <div style={{padding: '24px'}}>
            <Title level={2}>Редактировать продукт</Title>
            <Card>
                <ProductForm
                    projects={projects}
                    options={options}
                    initialData={productData || undefined}
                    onSubmit={handleSubmit}
                    onCancel={handleCancel}
                    loading={updateMutation.isPending}
                />
            </Card>
        </div>
    )
}