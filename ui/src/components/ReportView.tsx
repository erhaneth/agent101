import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

export function ReportView({ markdown }: { markdown: string }) {
  return (
    <article className="prose">
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{markdown}</ReactMarkdown>
    </article>
  )
}