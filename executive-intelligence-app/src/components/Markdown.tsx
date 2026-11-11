import ReactMarkdown, { type Components } from 'react-markdown'
import remarkGfm from 'remark-gfm'

// react-markdown ignores raw HTML in the source, so agent output can't inject markup.
const components: Components = {
  p: ({ children }) => <p className="my-2 first:mt-0 last:mb-0">{children}</p>,
  ul: ({ children }) => <ul className="my-2 list-disc space-y-1 pl-5">{children}</ul>,
  ol: ({ children }) => <ol className="my-2 list-decimal space-y-1 pl-5">{children}</ol>,
  h1: ({ children }) => <h3 className="mb-1 mt-3 text-base font-bold first:mt-0">{children}</h3>,
  h2: ({ children }) => <h3 className="mb-1 mt-3 text-sm font-bold first:mt-0">{children}</h3>,
  h3: ({ children }) => <h4 className="mb-1 mt-3 text-sm font-semibold first:mt-0">{children}</h4>,
  strong: ({ children }) => <strong className="font-semibold">{children}</strong>,
  a: ({ children, href }) => (
    <a href={href} target="_blank" rel="noopener noreferrer" className="text-brand underline">
      {children}
    </a>
  ),
  code: ({ children }) => <code className="rounded bg-canvas-dark px-1 font-mono text-[0.8em]">{children}</code>,
  pre: ({ children }) => (
    <pre className="my-2 overflow-x-auto rounded-lg bg-canvas-dark p-2 font-mono text-xs [&_code]:bg-transparent [&_code]:p-0">
      {children}
    </pre>
  ),
  table: ({ children }) => (
    <div className="my-2 overflow-x-auto">
      <table className="w-full border-collapse text-xs">{children}</table>
    </div>
  ),
  th: ({ children }) => <th className="border-b border-line px-2 py-1 text-left font-semibold">{children}</th>,
  td: ({ children }) => <td className="border-b border-line/60 px-2 py-1 align-top">{children}</td>,
  blockquote: ({ children }) => <blockquote className="my-2 border-l-2 border-line pl-3 text-ink-light">{children}</blockquote>,
  hr: () => <hr className="my-3 border-line" />,
}

/** Renders the agent's GitHub-flavored markdown in the tray's message style. */
export default function Markdown({ children }: { children: string }) {
  return (
    <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
      {children}
    </ReactMarkdown>
  )
}
