import React from 'react'
import {Form, Button, Space, Row, Col, message} from 'antd'
import type {
    ProductCategory,
    ProductFormData,
} from "../../entities/product";
import {resolveProductImages} from './lib/resolveProductImages'
import type {AvitoAccount} from '../../entities/avito/types'

interface ProductFormProps {
    avitoAccounts: AvitoAccount[]
    categories: ProductCategory[]
    initialData?: Partial<ProductFormData>
    onSubmit: (data: ProductFormData) => Promise<void>
    onCancel: () => void
    loading?: boolean
}

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

import {
    buildProductFormData,
    createProductInitialValues,
    normalizeCategory,
    type ProductFormValues,
} from './lib/productFormMapper'

import {useProductOptions} from './model/useProductOptions'


export const ProductForm: React.FC<ProductFormProps> = ({
                                                            avitoAccounts,
                                                            initialData,
                                                            categories,
                                                            onSubmit,
                                                            onCancel,
                                                            loading = false,
                                                        }) => {
    const [form] = Form.useForm<ProductFormValues>()
    const initialValues = createProductInitialValues(initialData)

    const submittingRef = React.useRef(false)
    const [isSubmitting, setIsSubmitting] = React.useState(false)

    const watchedCategory = Form.useWatch('category', form)
    const category = normalizeCategory(watchedCategory ?? initialValues.category)

    const submitLoading = loading || isSubmitting


    const {
        data: options = [],
        isFetching: optionsLoading,
        error: optionsError,
    } = useProductOptions(category)

    const handleValuesChange = (changedValues: Partial<ProductFormValues>) => {
        if ('category' in changedValues) {
            form.setFieldValue('options', {})
        }
    }
    // Обработка и отправка формы
    const handleSubmit = async () => {

        if (loading || submittingRef.current) {
            return
        }

        submittingRef.current = true
        setIsSubmitting(true)

        try {
            try {
                await form.validateFields()
            } catch {
                return
            }

            const values = form.getFieldsValue(true) as ProductFormValues

            let mainImages: Awaited<ReturnType<typeof resolveProductImages>>
            let additionalImages: Awaited<ReturnType<typeof resolveProductImages>>

            try {
                [mainImages, additionalImages] = await Promise.all([
                    resolveProductImages(values.main_images),
                    resolveProductImages(values.additional_images),
                ])
            } catch {
                message.error('Не удалось загрузить изображения')
                return
            }


            try {
                await onSubmit(buildProductFormData(values, {
                    mainImages: mainImages.urls,
                    additionalImages: additionalImages.urls,
                    mainImageAssetIds: mainImages.assetIds,
                    additionalImageAssetIds: additionalImages.assetIds,
                }))
            } catch {
                // Ошибку create/update показывает родительская mutation.onError.
            }
        } finally {
            submittingRef.current = false
            setIsSubmitting(false)
        }
    }


    return (
        <Form<ProductFormValues>
            form={form}
            layout='vertical'
            initialValues={initialValues}
            onValuesChange={handleValuesChange}
        >
            {/*Основная информация*/}
            <BasicInfoSection avitoAccounts={avitoAccounts} categories={categories}/>

            {/* Заголовки */}
            <TitlesSection/>

            {/* Описания */}
            <DescriptionsSection/>

            {/* Изображения */}
            <ImagesSection/>

            {/* Адреса */}
            <AddressesSection/>

            {/* Опции */}
            <OptionsSection
                options={options}
                loading={optionsLoading}
                error={optionsError}
            />

            {/* Расписание */}
            <ScheduleSection/>

            <Row gutter={[16, 16]}>
                <Col xs={24} lg={12}>
                    {/* Контакты */}
                    <ContactSection/>
                </Col>

                <Col xs={24} lg={12}>
                    {/* Дополнительные настройки */}
                    <SettingsSection/>
                </Col>
            </Row>

            {/* Кнопки действий */}
            <Space>
                <Button type="primary" onClick={handleSubmit} loading={loading} disabled={submitLoading}>
                    Сохранить
                </Button>

                <Button onClick={onCancel} disabled={submitLoading}>
                    Отмена
                </Button>
            </Space>
        </Form>
    )
}