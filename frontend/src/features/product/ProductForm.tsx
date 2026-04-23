import React, {useEffect, useRef, useState} from 'react'
import {Form, Button, Space} from 'antd'
import type {ProductOption, ProductFormData} from '../../entities/product'
import type {Project} from "../../entities/project";
import type {ProductImageValue} from "../../entities/product/types.ts";
import {getProductOptions} from '../../shared/api/products'
import {useQuery} from "@tanstack/react-query";
import {
    BasicInfoSection,
    TitlesSection,
    DescriptionsSection,
    ImagesSection,
    AddressesSection,
    OptionsSection,
    ContactSection,
    ScheduleSection,
    SettingsSection
} from "./components";


type ProductFormValues = Omit<ProductFormData, 'options'> & {
    options?: Record<string, string | undefined>
}

const toFormValues = (data?: Partial<ProductFormData>): Partial<ProductFormValues> | undefined => {
    if (!data) {
        return undefined
    }

    const {options, ...rest} = data

    return {
        ...rest,
        options: options?.reduce<Record<string, string | undefined>>((acc, option) => {
            acc[String(option.option_id)] = option.value
            return acc
        }, {}),
    }
}

interface ProductFormProps {
    projects: Project[]
    categories: string[]
    initialData?: Partial<ProductFormData>
    onSubmit: (data: ProductFormData) => Promise<void>
    onCancel: () => void
    loading?: boolean
}

export const ProductForm: React.FC<ProductFormProps> = ({
                                                            projects,
                                                            initialData,
                                                            categories,
                                                            onSubmit,
                                                            onCancel,
                                                            loading = false,
                                                        }) => {
    const [form] = Form.useForm<ProductFormValues>()

    const category = (Form.useWatch('category', form) ?? "").trim()
    const previousCategoryRef = useRef<string | undefined>(initialData?.category)

    const [titles, setTitles] = useState<string[]>(initialData?.titles || [''])
    const [descriptions, setDescriptions] = useState<string[]>(initialData?.descriptions || [''])
    const [addresses, setAddresses] = useState<string[]>(initialData?.addresses || [])
    const [mainImages, setMainImages] = useState<ProductImageValue[]>(initialData?.main_images || [])
    const [additionalImages, setAdditionalImages] = useState<ProductImageValue[]>(initialData?.additional_images || [])
    const [randomizeEnabled, setRandomizeEnabled] = useState<boolean>(
        initialData?.price_randomization_enabled ?? false)

    const isFirstRender = useRef(true)

    const {data: options = [], isFetching: optionsLoading} = useQuery<ProductOption[]>({
        queryKey: ['options', category],
        queryFn: () => getProductOptions(category),
        enabled: Boolean(category),
        staleTime: 5 * 60 * 1000,
    })

    useEffect(() => {
        if (previousCategoryRef.current && previousCategoryRef.current !== category) {
            form.setFieldValue('options', {})
        }

        previousCategoryRef.current = category
    }, [category, form])

    // Синхронизация с initialData
    useEffect(() => {
        if (isFirstRender.current) {
            isFirstRender.current = false
            return
        }
        if (initialData) {
            const formValues = toFormValues(initialData)

            if (formValues) {
                form.setFieldsValue(formValues)
            }

            setTitles(initialData.titles || [''])
            setDescriptions(initialData.descriptions || [''])
            setAddresses(initialData.addresses || [])
            setMainImages(initialData.main_images || [])
            setAdditionalImages(initialData.additional_images || [])
            setRandomizeEnabled(initialData.price_randomization_enabled ?? false)
        }
    }, [initialData, form]);

    // Обработка и отправка формы
    const handleSubmit = async () => {
        try {
            const values = await form.validateFields()

            const selectedOptions = Object.entries(values.options ?? {})
                .filter(([, value]) => Boolean(value))
                .map(([optionId, value]) => ({
                    option_id: Number(optionId),
                    value: value as string,
                }))

            const formData: ProductFormData = {
                ...values,
                price_randomization_enabled: randomizeEnabled,
                options: selectedOptions,
                titles: titles.filter(t => t.trim()),
                descriptions: descriptions.filter(d => d.trim()),
                addresses: addresses.filter(a => a.trim()),
                main_images: mainImages,
                additional_images: additionalImages,
                // Если рандомизация выключена - очищаем поля
                price_min: randomizeEnabled ? values.price_min : 0,
                price_max: randomizeEnabled ? values.price_max : 0,
                price_step: randomizeEnabled ? values.price_step : 0,

            }
            await onSubmit(formData)

        } catch (error) {
            console.error('Ошибка валидации', error)
        }
    }


    return (
        <Form form={form} layout='vertical' initialValues={{
            ...toFormValues(initialData),
            schedule: {
                frequency: initialData?.schedule?.frequency ?? 1,
                days: initialData?.schedule?.days ?? [],
            },

        }}>
            {/*Основная информация*/}
            <BasicInfoSection randomizeEnabled={randomizeEnabled} onRandomizeChange={setRandomizeEnabled}
                              projects={projects} categories={categories}/>

            {/* Заголовки */}
            <TitlesSection initialTitles={titles} onChange={(newTitles) => setTitles(newTitles)}/>

            {/* Описания */}
            <DescriptionsSection initialDescriptions={descriptions}
                                 onChange={(newDescriptions) => setDescriptions(newDescriptions)}/>

            {/* Изображения */}
            <ImagesSection initialMainImages={mainImages} initialAdditionalImages={additionalImages}
                           onAdditionalImagesChange={setAdditionalImages}
                           onMainImagesChange={setMainImages}/>

            {/* Адреса */}
            <AddressesSection initialAddresses={addresses} onChange={(newAddresses) => setAddresses(newAddresses)}/>

            {/* Опции */}
            <OptionsSection options={options} loading={optionsLoading}/>

            {/* Расписание */}
            <ScheduleSection/>

            {/* Контакты */}
            <ContactSection/>

            {/* Дополнительные настройки */}
            <SettingsSection/>

            {/* Кнопки действий */}
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