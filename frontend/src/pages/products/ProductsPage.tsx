import React from "react";
import {useQuery} from "@tanstack/react-query";
import {getProducts} from "../../shared/api/products.ts";
import {useProductActions} from "../../features/product";
import {ProductList} from "../../widgets/product";
import type {Product} from "../../entities/product";
import {useNavigate} from "react-router-dom";

export const ProductsPage: React.FC = () => {

    const navigate = useNavigate()

    // Загрузка проудктов
    const {data: products = [], isLoading} = useQuery<Product[]>({
        queryKey: ['products'],
        queryFn: getProducts,
    })

    const {toggleActive, delete: deleteProduct, generate} = useProductActions()

    const handleAdd = () => {
        navigate('/products/add')

    }

    const handleEdit = (id: number) => {
        navigate(`/products/${id}/edit`)
    }

    const handleToggleActive = (id: number, action: 'activate' | 'deactivate') => {
        toggleActive({id, action})
    }

    const handleGenerate = (id: number) => {
        generate(id)
    }


    return (
        <ProductList
            products={products}
            loading={isLoading}
            onAdd={handleAdd}
            onDelete={deleteProduct}
            onEdit={handleEdit}
            onToggleActive={handleToggleActive}
            onGenerate={handleGenerate}
        />
    )
}