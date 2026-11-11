import brand from 'virtual:brand'

/** From brand.config.ts; see "Branding" in the app README. */
export const APP_TITLE = brand.name
export const ASSISTANT_NAME = brand.assistant
export const LOGO_URL = brand.logo
export const BRAND_COLOR = brand.colors.brand
export const ACCENT_COLOR = brand.colors.accent

/**
 * Chart series colors, in the order series are assigned. The first is the
 * brand color. Keep in step with `tailwind.config.js`, which recharts cannot
 * read.
 */
export const SERIES_COLORS = [brand.colors.brand, '#0E7C66', '#5E33B5', '#E5641E', brand.colors.dark, brand.colors.accent, '#7A8699']

export const CHART_GRID = '#DDE1E6'
export const CHART_AXIS = '#666666'
