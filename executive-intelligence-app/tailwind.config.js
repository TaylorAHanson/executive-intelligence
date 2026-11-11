import { loadBrand, rgba } from './brand.config.ts'

const { colors: brand } = loadBrand()

/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      // One primary on white, dark neutral text, the accent used sparingly.
      // The brand colors come from brand.config.ts. Use these names rather
      // than sprinkling hex values through components.
      colors: {
        brand: {
          DEFAULT: brand.brand,
          bright: brand.bright,
          dark: brand.dark,
        },
        accent: brand.accent,
        canvas: {
          DEFAULT: '#F5F6F8', // panels behind white cards
          dark: '#EAECEF',
        },
        line: '#DDE1E6', // borders
        ink: {
          DEFAULT: '#151515',
          light: '#555555',
          muted: '#666666',
        },
      },
      fontFamily: {
        sans: ['"Roboto Flex"', 'Roboto', '-apple-system', 'BlinkMacSystemFont', 'Segoe UI', 'sans-serif'],
      },
      backgroundImage: {
        'landing-glow':
          `radial-gradient(1200px 800px at 50% 30%, ${rgba(brand.brand, 0.1)}, transparent 70%),` +
          `radial-gradient(900px 700px at 90% 80%, ${rgba(brand.bright, 0.08)}, transparent 70%),` +
          'linear-gradient(180deg, #FFFFFF 0%, #F5F6F8 100%)',
      },
      boxShadow: {
        tile: '0 6px 20px rgba(21,21,21,.08)',
        'tile-hover': `0 14px 36px ${rgba(brand.dark, 0.18)}`,
        supervisor: `0 20px 50px ${rgba(brand.dark, 0.35)}`,
        'supervisor-hover': `0 24px 60px ${rgba(brand.dark, 0.5)}`,
      },
    },
  },
  plugins: [],
}
