import {useMutation, useQueryClient} from "@tanstack/react-query";
import {message} from 'antd'
import {
    toggleProductActive,
    deleteProduct,
    generateRandomProduct
} from "../../shared/api/products.ts";

/**
 * Хук для действий с продуктами (активация, удаление, генерация)
 */

export const useProductActions = () => {
    const queryClient = useQueryClient()

    // Мутация для активации / деактивации
    const toggleActiveMutation = useMutation({
        mutationFn: ({id, action}: { id: number, action: 'activate' | 'deactivate' }) =>
            toggleProductActive(id, action),
        onSuccess: () => {
            queryClient.invalidateQueries({queryKey: ['products']})
            message.success('Статус обновлен')
        },
        onError: () => {
            message.error("Ошибка обновления статуса")
        }
    })

    // Мутация для удаления
    const deleteMutation = useMutation({
        mutationFn: (id: number) => deleteProduct(id),
        onSuccess: () => {
            queryClient.invalidateQueries({queryKey: ['products']})
            message.success('Продукт удален')
        },
        onError: () => {
            message.error('Ошибка удаления')
        }
    })

    // Мутауия для генерации
    const generateMutation = useMutation({
        mutationFn: (id: number) => generateRandomProduct(id),
        onSuccess: () => {
            message.success('Объявление сгенерировано')
        },
        onError: () => {
            message.error('Ошибка генерации')
        }
    })

    return {
        toggleActive: toggleActiveMutation.mutate,
        delete: deleteMutation.mutate,
        generate: generateMutation.mutate,
        isToggleLoading: toggleActiveMutation.isPending,
        isDeleteLoading: deleteMutation.isPending,
        isGenerateLoading: generateMutation.isPending,
    }
}