import { BRAND_COLOR } from '../../brand'

/**
 * Insight prose with `**bold**` for its figures. Only bold is recognised;
 * anything else in the text is shown as written, never as HTML.
 *
 * `highlight` marks each figure with a pen-stroke behind it instead of
 * coloring it. The text cannot say whether a figure is good news, so it must
 * not be colored as if it did.
 */
export default function Rich({
  text,
  strong = 'text-ink',
  highlight = false,
}: {
  text: string
  strong?: string
  highlight?: boolean
}) {
  const parts = text.split(/\*\*(.+?)\*\*/g)
  const pen = highlight
    ? { backgroundImage: `linear-gradient(transparent 62%, color-mix(in srgb, ${BRAND_COLOR} 20%, transparent) 62%)` }
    : undefined
  return (
    <>
      {parts.map((part, i) =>
        i % 2 === 1 ? (
          <strong key={i} className={`font-semibold ${strong}`} style={pen}>
            {part}
          </strong>
        ) : (
          part
        ),
      )}
    </>
  )
}
