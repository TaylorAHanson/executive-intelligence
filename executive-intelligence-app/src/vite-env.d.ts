/// <reference types="vite/client" />

/** Mirrors `Brand` in brand.config.ts, which uses Node APIs the app build can't type-check. */
declare module 'virtual:brand' {
  const brand: {
    name: string
    assistant: string
    colors: { brand: string; bright: string; dark: string; accent: string }
    logo: string | null
    favicon: string | null
  }
  export default brand
}
