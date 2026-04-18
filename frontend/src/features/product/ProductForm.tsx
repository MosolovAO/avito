import React, {useEffect, useRef, useState} from 'react'
import {Form, Button, Space} from 'antd'
import type {ProductOption, ProductFormData} from '../../entities/product'
import type {Project} from "../../entities/project";
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

interface ProductFormProps {
    projects: Project[]
    options: ProductOption[]
    initialData?: Partial<ProductFormData>
    onSubmit: (data: ProductFormData) => Promise<void>
    onCancel: () => void
    loading?: boolean
}

export const ProductForm: React.FC<ProductFormProps> = ({
                                                            projects,
                                                            options,
                                                            initialData,
                                                            onSubmit,
                                                            onCancel,
                                                            loading = false,
                                                        }) => {
    const [form] = Form.useForm<ProductFormData>()
    const [titles, setTitles] = useState<string[]>(initialData?.titles || [''])
    const [descriptions, setDescriptions] = useState<string[]>(initialData?.descriptions || [''])
    const [addresses, setAddresses] = useState<string[]>(initialData?.addresses || [])
    const [mainImages, setMainImages] = useState<File[]>(initialData?.main_images || [])
    const [additionalImages, setAdditionalImages] = useState<File[]>(initialData?.additional_images || [])

    const [randomizeEnabled, setRandomizeEnabled] = useState<boolean>(
        initialData?.price_min !== undefined && initialData.price_min !== null
    )

    const isFirstRender = useRef(true)

    // Синхронизация с initialData
    useEffect(() => {
        if (isFirstRender.current) {
            isFirstRender.current = false
            return
        }
        if (initialData) {
            form.setFieldsValue(initialData)
            setTitles(initialData.titles || [''])
            setDescriptions(initialData.descriptions || [''])
            setAddresses(initialData.addresses || [])
            setMainImages(initialData.main_images || [])
            setAdditionalImages(initialData.additional_images || [])
            setRandomizeEnabled(initialData.price_min !== undefined && initialData.price_min !== null
            )
        }
    }, [initialData, form]);

    // Обработка и отправка формы
    const handleSubmit = async () => {
        try {
            const values = await form.validateFields()

            const formData: ProductFormData = {
                ...values,
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
            form.resetFields()
        } catch (error) {
            console.error('Ошибка валидации', error)
        }
    }


    return (
        <Form form={form} layout='vertical' initialValues={{
            ...initialData,
            schedule: {
                frequency: 1,
                days: initialData?.schedule?.days || []
            }

        }}>
            {/*Основная информация*/}
            <BasicInfoSection randomizeEnabled={randomizeEnabled} onRandomizeChange={setRandomizeEnabled}
                              projects={projects}/>

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
            <OptionsSection options={options}/>

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