/**
 * Insight prose with `**bold**` for its figures. Only bold is recognised;
 * anything else in the text is shown as written, never as HTML.
 */
export default function Rich({ text, strong = 'text-ink' }: { text: string; strong?: string }) {
  const parts = text.split(/\*\*(.+?)\*\*/g)
  return (
    <>
      {parts.map((part, i) =>
        i % 2 === 1 ? (
          <strong key={i} className={`font-semibold ${strong}`}>
            {part}
          </strong>
        ) : (
          part
        ),
      )}
    </>
  )
}
