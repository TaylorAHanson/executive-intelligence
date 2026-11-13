import { useEffect, useRef, useState } from 'react'

/**
 * The width of an element, kept current as it changes: for layouts that depend
 * on the room a component has rather than on the window, such as a table
 * beside a tray that may or may not be open. Zero until the first measurement,
 * so render a safe default for 0.
 */
export function useElementWidth<T extends HTMLElement>() {
  const ref = useRef<T>(null)
  const [width, setWidth] = useState(0)

  useEffect(() => {
    const element = ref.current
    if (!element) return
    const observer = new ResizeObserver(([entry]) => setWidth(Math.round(entry.contentRect.width)))
    observer.observe(element)
    return () => observer.disconnect()
  }, [])

  return [ref, width] as const
}
