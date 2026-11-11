/**
 * Build-time branding, read by `tailwind.config.js` and `vite.config.ts`.
 *
 * The repo ships a neutral theme. A deployment overrides any of it from the
 * gitignored `branding/` folder next to this file:
 *
 *   branding/brand.json   {"name": "...", "assistant": "...", "colors": {"brand": "#..."}}
 *   branding/logo.svg     header logo (otherwise an icon in the brand color)
 *   branding/favicon.svg  browser tab icon (otherwise public/favicon.svg)
 *
 * Branding is baked into the build, so rebuild after changing it.
 */
import { existsSync, readFileSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

export interface BrandColors {
  /** Primary: logo, buttons, links, the first chart series. */
  brand: string
  /** Hover and gradient highlight. */
  bright: string
  /** Gradient shadow and hover. */
  dark: string
  /** Badges, warnings, at-risk marks. Use sparingly. */
  accent: string
}

export interface Brand {
  /** App title: browser tab, header, landing page. */
  name: string
  /** What the agent tray calls itself ("Ask {assistant} ..."). */
  assistant: string
  colors: BrandColors
  /** `data:` URL of branding/logo.svg, or null. */
  logo: string | null
  /** `data:` URL of branding/favicon.svg, or null. */
  favicon: string | null
}

const BRANDING_DIR = path.join(path.dirname(fileURLToPath(import.meta.url)), 'branding')

const DEFAULTS = {
  name: 'Executive Intelligence',
  assistant: 'Exec AI',
  colors: { brand: '#2563EB', bright: '#1D4ED8', dark: '#1E3A8A', accent: '#DC2626' },
}

function svgDataUrl(file: string): string | null {
  const full = path.join(BRANDING_DIR, file)
  if (!existsSync(full)) return null
  return `data:image/svg+xml;base64,${readFileSync(full).toString('base64')}`
}

export function loadBrand(): Brand {
  const file = path.join(BRANDING_DIR, 'brand.json')
  const custom: Partial<Omit<Brand, 'colors'>> & { colors?: Partial<BrandColors> } = existsSync(file)
    ? JSON.parse(readFileSync(file, 'utf8'))
    : {}
  return {
    name: custom.name ?? DEFAULTS.name,
    assistant: custom.assistant ?? DEFAULTS.assistant,
    colors: { ...DEFAULTS.colors, ...custom.colors },
    logo: svgDataUrl('logo.svg'),
    favicon: svgDataUrl('favicon.svg'),
  }
}

/** `#RRGGBB` as an `rgba(...)` string, for gradients and shadows. */
export function rgba(hex: string, alpha: number): string {
  const n = parseInt(hex.replace('#', ''), 16)
  return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${alpha})`
}
