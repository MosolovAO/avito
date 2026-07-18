// Тип Product (задача для парсинга)
export interface Product {
    id: number
    name: string
    url: string
    price: number
    activate: boolean
    price_min: number
    price_max: number
    price_step: number
    titles: string[]
    main_images: string[]
    additional_images: string[]
    main_image_asset_ids: number[]
    additional_image_asset_ids: number[]
    descriptions: Record<string, string> | string[]
    addresses: string[]
    category: string
    schedule: ProductSchedule
    schedule_anchor_date: string
    schedule_timezone: string
    next_update_time: string | null
    last_run_at: string | null
    last_successful_run_at: string | null
    last_run_status: 'idle' | 'running' | 'success' | 'error'
    last_run_error: string | null
    price_randomization_enabled: boolean
    options: ProductSelectionOption[]
    avito_account_ids?: number[]
    avito_accounts?: Array<{
        id: number
        name: string
        export_status: string
    }>
    base_data?: ProductBaseData

    // legacy/form fields, пока оставляем для постепенного вычищения
    listingfee?: string
    email?: string
    contactphone?: string
    managername?: string
    avitostatus?: string
    companyname?: string
    contactmethod?: string
    adtype?: string
    availability?: string
    projects?: { id: number; project_name: string }[]
}

export interface ProductCategory {
    id: number
    name: string
}

export interface ProductSchedule {
    frequency: 1 | 2 | 3 | 4
    days: Array<string | null>
}

export interface ProductImageAssetValue {
    id: number
    url: string
}


// Тип Product1 (созданное объявление)
export interface Product1 {
    id: number
    title: string
    urls: string[]
    description: string
    created_date: string
    task_id: number
    selected_option: Record<string, string>
    project_name: string[]
}

export type ProductOptionValue = string | string[]

export interface ProductSelectionOption {
    option_id: number
    value: ProductOptionValue
}


// Тип ProductOption
export interface ProductOption {
    id: number
    option_title: string
    option_code: string
    option_title_ru: string
    option_title_en: string
    allow_multiple: boolean
    allow_multiple_options: boolean
    categories: number[]
}

export type ProductImageValue = File | ProductImageAssetValue | string

// Типы для формы добавления/редактирования продукта
export interface ProductFormData {
    name: string
    titles: string[]
    price_randomization_enabled: boolean
    main_images: string[]
    additional_images: string[]
    main_image_asset_ids: number[]
    additional_image_asset_ids: number[]
    descriptions: string[]
    addresses: string[]
    category: string
    avito_account_ids: number[]
    base_data?: ProductBaseData
    listingfee?: string
    email?: string
    contactphone?: string
    managername?: string
    avitostatus?: string
    companyname?: string
    contactmethod?: string
    adtype?: string
    availability?: string
    price: number
    price_min: number
    price_max: number
    price_step: number
    projects?: number[]
    options: ProductSelectionOption[]
    schedule: ProductSchedule
}

export interface ProductBaseData {
    Category?: string
    ListingFee?: string
    EMail?: string
    ContactPhone?: string
    ManagerName?: string
    AvitoStatus?: string
    CompanyName?: string
    ContactMethod?: string
    AdType?: string
    Availability?: string
}


/**
 * Тип изображения продукта
 */
export interface ProductImage {
    id?: string | number
    url: string
    file?: File
    isUploaded: boolean
}


/**
 * Ответ сервера после загрузки изображения
 */
export interface UploadImageResponse {
    id: number
    url: string
}

