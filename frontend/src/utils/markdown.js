import DOMPurify from 'dompurify'
import MarkdownIt from 'markdown-it'

const markdown = new MarkdownIt({
  html: false,
  linkify: true,
  typographer: true,
  breaks: true
})

// 将 AI 返回的 Markdown 文本渲染为安全 HTML。
export function renderMarkdown(content) {
  const renderedHtml = markdown.render(content || '')

  return DOMPurify.sanitize(renderedHtml)
}

