<template>
  <!-- eslint-disable vue/no-v-html -->
  <section class="chat-panel">
    <header class="chat-header">
      <div>
        <p class="chat-subtitle">AI 健康饮食食谱助手</p>
        <div class="chat-title-row">
          <h1>{{ currentSessionTitle }}</h1>
        </div>
      </div>
      <div class="chat-tags">
        <span>绿色饮食风格</span>
        <span>一日三餐建议</span>
        <span>支持减脂/增肌/控糖</span>
      </div>
    </header>

    <p
      v-if="initializing"
      class="init-message"
    >
      系统正在初始化会话与多 Agent 状态，请稍候...
    </p>

    <div class="tips-row">
      <button
        v-for="item in quickPrompts"
        :key="item"
        class="tip-button"
        type="button"
        @click="handleQuickSend(item)"
      >
        {{ item }}
      </button>
    </div>

    <div
      ref="messageContainerRef"
      class="message-container"
    >
      <div
        v-for="message in messages"
        :key="message.id"
        class="message-row"
        :class="{
          'message-row--user': message.role === 'user',
          'message-row--assistant': message.role === 'assistant'
        }"
      >
        <div class="message-avatar">
          {{ message.role === 'user' ? '我' : 'AI' }}
        </div>
        <div
          class="message-bubble"
          :class="{
            'message-bubble--loading': message.pending && message.role === 'assistant',
            'message-bubble--failed': message.failed && message.role === 'assistant'
          }"
        >
          <div class="message-role">
            {{ message.role === 'user' ? '你' : '健康饮食助手' }}
          </div>
          <section
            v-if="message.role === 'assistant' && message.thinking_content"
            class="thinking-panel"
          >
            <div class="thinking-title">思考过程</div>
            <pre>{{ message.thinking_content }}</pre>
          </section>
          <p v-if="message.role === 'user'">
            {{ message.content }}
          </p>
          <p v-else-if="message.pending && message.role === 'assistant' && !message.content">
            <span class="loading-dots">
              <i></i><i></i><i></i>
            </span>
            正在生成回答...
          </p>
          <!-- eslint-disable-next-line vue/no-v-html -->
          <div
            v-else
            class="message-markdown"
            v-html="renderMarkdown(message.content)"
          />
          <div
            v-if="message.role === 'assistant' && !message.pending && isWeeklyRecipe(message.content)"
            class="export-actions"
          >
            <button
              class="export-pdf-button"
              type="button"
              :disabled="exportingPdf"
              @click="exportWeeklyRecipePdf(message.content)"
            >
              {{ exportingPdf ? '正在生成 PDF...' : '下载 PDF' }}
            </button>
          </div>
          <div
            v-if="message.role === 'assistant' && !message.pending && message.suggested_questions?.length"
            class="suggestion-list"
          >
            <button
              v-for="question in message.suggested_questions"
              :key="question"
              class="suggestion-button"
              type="button"
              :disabled="sending"
              @click="handleSuggestedQuestion(question)"
            >
              {{ question }}
            </button>
          </div>
          <span>{{ formatDate(message.created_at) }}</span>
        </div>
      </div>
    </div>

    <p
      v-if="errorMessage"
      class="error-message"
    >
      {{ errorMessage }}
    </p>

    <form
      class="composer"
      @submit.prevent="handleSubmit"
    >
      <div class="composer-main">
        <textarea
          v-model.trim="draft"
          class="composer-input"
          placeholder="请输入你的饮食目标，例如：帮我做一份适合减脂的 3 餐食谱；也可以点击右侧图标上传餐食图片。"
          rows="4"
        />
        <label class="composer-upload-button">
          <input
            type="file"
            accept=".pdf,image/*"
            multiple
            @change="handleFileChange"
          >
          <span>📎</span>
        </label>
      </div>

      <div
        v-if="selectedFiles.length"
        class="selected-file-row"
      >
        <span>
          已选择：{{ selectedFiles.map((item) => item.name).join('、') }}
          <template v-if="selectedFiles.length === 2">
            （将按餐前餐后图片对比处理）
          </template>
          <template v-else>
            （将按普通图片处理）
          </template>
        </span>
        <button
          type="button"
          class="remove-file-button"
          @click="clearSelectedFile"
        >
          移除
        </button>
      </div>

      <div class="composer-footer">
        <span>建议补充：年龄、身高体重、运动频率、忌口食物、单位食堂用餐需求。</span>
        <button
          class="send-button"
          type="submit"
          :disabled="sending"
        >
          {{ sending ? '生成中...' : '发送问题' }}
        </button>
      </div>
    </form>
  </section>
  <!-- eslint-enable vue/no-v-html -->
</template>

<script setup>
import { nextTick, ref, watch } from 'vue'

import { renderMarkdown } from '../../utils/markdown'

const props = defineProps({
  messages: {
    type: Array,
    default: () => []
  },
  currentSessionTitle: {
    type: String,
    default: '新的饮食计划'
  },
  workflowState: {
    type: Object,
    default: () => null
  },
  initializing: {
    type: Boolean,
    default: false
  },
  sending: {
    type: Boolean,
    default: false
  },
  errorMessage: {
    type: String,
    default: ''
  }
})

const emit = defineEmits(['send'])
const draft = ref('')
const selectedFiles = ref([])
const messageContainerRef = ref(null)
const exportingPdf = ref(false)
const quickPrompts = [
  '帮我做一份减脂的一日三餐食谱',
  '我在健身增肌，早餐和午餐怎么安排？',
  '我想控糖，晚餐吃什么比较合适？',
  '帮我安排一份清淡养胃的饮食建议'
]

// 只在新增消息时滚动到底部；流式回答和思考内容更新时不强制滚动，避免抢占用户滚动条。
watch(
  () => props.messages.length,
  async () => {
    await nextTick()
    if (messageContainerRef.value) {
      messageContainerRef.value.scrollTop = messageContainerRef.value.scrollHeight
    }
  },
  { immediate: true }
)

function handleSubmit() {
  if (!draft.value && !selectedFiles.value.length) {
    return
  }

  emit('send', {
    content: draft.value,
    files: selectedFiles.value
  })
  draft.value = ''
  clearSelectedFile()
}

function handleQuickSend(content) {
  emit('send', content)
}

function handleSuggestedQuestion(content) {
  emit('send', content)
}

function isWeeklyRecipe(content) {
  const text = content || ''
  const hasWeeklySummary = text.includes('本周总结')
  const hasWeeklyDays = text.includes('周一') && text.includes('周日')
  const hasDailySummary = text.includes('每日总量汇总')

  return hasWeeklySummary || (hasWeeklyDays && hasDailySummary)
}

async function exportWeeklyRecipePdf(content) {
  if (exportingPdf.value) {
    return
  }

  exportingPdf.value = true
  try {
    const pdfBlob = await createRecipePdfBlob(content)
    const url = URL.createObjectURL(pdfBlob)
    const link = document.createElement('a')
    link.href = url
    link.download = `一周食谱规划-${new Date().toISOString().slice(0, 10)}.pdf`
    document.body.appendChild(link)
    link.click()
    link.remove()
    URL.revokeObjectURL(url)
  } finally {
    exportingPdf.value = false
  }
}

async function createRecipePdfBlob(content) {
  const pageWidth = 1123
  const pageHeight = 794
  const scale = 2
  const renderer = createPdfCanvasRenderer({ pageWidth, pageHeight, scale })
  renderer.drawTitle()
  renderMarkdownToPdfCanvas(content, renderer)
  return buildPdfFromJpegPages(renderer.toJpegPages(), {
    pageWidthPt: 841.89,
    pageHeightPt: 595.28
  })
}

function createPdfCanvasRenderer({ pageWidth, pageHeight, scale }) {
  const margin = 42
  const contentWidth = pageWidth - margin * 2
  const pages = []
  let canvas
  let context
  let y = margin

  const setFont = (size, weight = 400) => {
    context.font = `${weight} ${size}px "Microsoft YaHei", "PingFang SC", "Noto Sans CJK SC", sans-serif`
  }

  const newPage = () => {
    canvas = document.createElement('canvas')
    canvas.width = pageWidth * scale
    canvas.height = pageHeight * scale
    context = canvas.getContext('2d')
    context.scale(scale, scale)
    context.fillStyle = '#ffffff'
    context.fillRect(0, 0, pageWidth, pageHeight)
    pages.push(canvas)
    y = margin
  }

  const ensureSpace = (height) => {
    if (y + height > pageHeight - margin) {
      newPage()
    }
  }

  const drawWrappedText = (text, x, maxWidth, options = {}) => {
    const fontSize = options.fontSize || 13
    const lineHeight = options.lineHeight || Math.round(fontSize * 1.65)
    const weight = options.weight || 400
    const color = options.color || '#172554'
    const prefix = options.prefix || ''
    setFont(fontSize, weight)
    context.fillStyle = color
    const lines = wrapCanvasText(context, `${prefix}${text}`, maxWidth)
    const blockHeight = lines.length * lineHeight
    ensureSpace(blockHeight + (options.marginBottom || 0))
    lines.forEach((line, index) => {
      context.fillText(line, x, y + fontSize + index * lineHeight)
    })
    y += blockHeight + (options.marginBottom || 0)
  }

  const drawTitle = () => {
    ensureSpace(62)
    setFont(24, 700)
    context.fillStyle = '#14532d'
    context.fillText('一周食谱规划', margin, y + 24)
    setFont(13, 400)
    context.fillStyle = '#64748b'
    context.fillText('由单位食堂饮食规划智能体生成', margin, y + 48)
    context.strokeStyle = '#bbf7d0'
    context.lineWidth = 2
    context.beginPath()
    context.moveTo(margin, y + 62)
    context.lineTo(pageWidth - margin, y + 62)
    context.stroke()
    y += 84
  }

  const drawHeading = (text, level) => {
    const fontSize = level === 1 ? 22 : level === 2 ? 18 : 15
    const marginTop = level === 1 ? 12 : 16
    y += marginTop
    drawWrappedText(text, margin, contentWidth, {
      fontSize,
      lineHeight: Math.round(fontSize * 1.5),
      weight: 700,
      color: '#14532d',
      marginBottom: 8
    })
  }

  const drawParagraph = (text) => {
    drawWrappedText(text, margin, contentWidth, {
      fontSize: 13,
      lineHeight: 22,
      color: '#172554',
      marginBottom: 8
    })
  }

  const drawListItem = (text) => {
    drawWrappedText(text, margin + 12, contentWidth - 12, {
      fontSize: 13,
      lineHeight: 21,
      color: '#172554',
      prefix: '• ',
      marginBottom: 4
    })
  }

  const drawTable = (rows) => {
    if (!rows.length) {
      return
    }

    const colCount = Math.max(...rows.map((row) => row.length))
    const colWidth = contentWidth / colCount
    const padding = colCount > 5 ? 4 : 6
    const fontSize = colCount > 5 ? 9 : 11
    const lineHeight = colCount > 5 ? 14 : 17

    const wrapRow = (row, rowIndex) => {
      setFont(fontSize, rowIndex === 0 ? 700 : 400)
      return Array.from({ length: colCount }, (_, colIndex) =>
        wrapCanvasText(context, cleanMarkdownText(row[colIndex] || ''), colWidth - padding * 2)
      )
    }

    const drawRowSegment = (wrappedCells, rowIndex, offsets, lineCount) => {
      const rowHeight = Math.max(28, lineCount * lineHeight + padding * 2)
      let x = margin
      setFont(fontSize, rowIndex === 0 ? 700 : 400)
      wrappedCells.forEach((lines, colIndex) => {
        const visibleLines = lines.slice(offsets[colIndex], offsets[colIndex] + lineCount)
        context.fillStyle = rowIndex === 0 ? '#f0fdf4' : '#ffffff'
        context.fillRect(x, y, colWidth, rowHeight)
        context.strokeStyle = '#bbf7d0'
        context.lineWidth = 1
        context.strokeRect(x, y, colWidth, rowHeight)
        context.fillStyle = rowIndex === 0 ? '#14532d' : '#172554'
        visibleLines.forEach((line, lineIndex) => {
          context.fillText(line, x + padding, y + padding + fontSize + lineIndex * lineHeight)
        })
        x += colWidth
      })
      y += rowHeight
    }

    const drawHeader = () => {
      const headerCells = wrapRow(rows[0], 0)
      const headerLines = Math.max(...headerCells.map((lines) => lines.length))
      const headerHeight = Math.max(28, headerLines * lineHeight + padding * 2)
      ensureSpace(headerHeight)
      drawRowSegment(headerCells, 0, Array(colCount).fill(0), headerLines)
    }

    rows.forEach((row, rowIndex) => {
      const wrappedCells = wrapRow(row, rowIndex)
      const offsets = Array(colCount).fill(0)
      let hasRemaining = true

      while (hasRemaining) {
        const remainingLines = Math.max(...wrappedCells.map((lines, cellIndex) => lines.length - offsets[cellIndex]))
        if (remainingLines <= 0) {
          hasRemaining = false
          break
        }

        let availableLines = Math.floor((pageHeight - margin - y - padding * 2) / lineHeight)
        if (availableLines <= 0) {
          newPage()
          if (rowIndex > 0) {
            drawHeader()
          }
          availableLines = Math.floor((pageHeight - margin - y - padding * 2) / lineHeight)
        }

        const lineCount = Math.max(1, Math.min(remainingLines, availableLines))
        drawRowSegment(wrappedCells, rowIndex, offsets, lineCount)
        offsets.forEach((offset, cellIndex) => {
          offsets[cellIndex] = offset + lineCount
        })
      }
    })
    y += 12
  }

  newPage()

  return {
    drawTitle,
    drawHeading,
    drawParagraph,
    drawListItem,
    drawTable,
    toJpegPages: () => pages.map((page) => ({
      bytes: dataUrlToBytes(page.toDataURL('image/jpeg', 0.92)),
      width: page.width,
      height: page.height
    }))
  }
}

function renderMarkdownToPdfCanvas(content, renderer) {
  const lines = (content || '').split(/\r?\n/)
  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index].trim()
    if (!line) {
      continue
    }

    if (line.includes('|') && index + 1 < lines.length && isMarkdownTableSeparator(lines[index + 1])) {
      const tableRows = [parseMarkdownTableRow(line)]
      index += 2
      while (index < lines.length && lines[index].includes('|')) {
        tableRows.push(parseMarkdownTableRow(lines[index]))
        index += 1
      }
      index -= 1
      renderer.drawTable(tableRows)
      continue
    }

    const heading = line.match(/^(#{1,3})\s+(.+)$/)
    if (heading) {
      renderer.drawHeading(cleanMarkdownText(heading[2]), heading[1].length)
      continue
    }

    if (/^[-*]\s+/.test(line)) {
      renderer.drawListItem(cleanMarkdownText(line.replace(/^[-*]\s+/, '')))
      continue
    }

    renderer.drawParagraph(cleanMarkdownText(line))
  }
}

function isMarkdownTableSeparator(line) {
  return /^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$/.test(line || '')
}

function parseMarkdownTableRow(line) {
  return line
    .trim()
    .replace(/^\|/, '')
    .replace(/\|$/, '')
    .split('|')
    .map((item) => item.trim())
}

function wrapCanvasText(context, text, maxWidth) {
  const normalized = cleanMarkdownText(text)
  const safeMaxWidth = Math.max(20, maxWidth - 8)
  const lines = []
  let current = ''
  for (const char of normalized) {
    const next = current + char
    if (context.measureText(next).width > safeMaxWidth && current) {
      lines.push(current)
      current = char
    } else {
      current = next
    }
  }
  if (current) {
    lines.push(current)
  }
  return lines.length ? lines : ['']
}

function cleanMarkdownText(text) {
  return String(text || '')
    .replace(/\*\*(.*?)\*\*/g, '$1')
    .replace(/`([^`]+)`/g, '$1')
    .replace(/&nbsp;/g, ' ')
    .trim()
}

function dataUrlToBytes(dataUrl) {
  const base64 = dataUrl.split(',')[1] || ''
  const binary = atob(base64)
  const bytes = new Uint8Array(binary.length)
  for (let index = 0; index < binary.length; index += 1) {
    bytes[index] = binary.charCodeAt(index)
  }
  return bytes
}

function buildPdfFromJpegPages(pageImages, options = {}) {
  const pageWidthPt = options.pageWidthPt || 595.28
  const pageHeightPt = options.pageHeightPt || 841.89
  const objects = []
  const pageObjectIds = []

  const addObject = (chunks) => {
    objects.push(Array.isArray(chunks) ? chunks : [ascii(chunks)])
    return objects.length
  }

  pageImages.forEach((pageImage) => {
    const imageId = addObject([
      ascii(`<< /Type /XObject /Subtype /Image /Width ${pageImage.width} /Height ${pageImage.height} /ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /DCTDecode /Length ${pageImage.bytes.length} >>\nstream\n`),
      pageImage.bytes,
      ascii('\nendstream')
    ])
    const content = `q\n${pageWidthPt} 0 0 ${pageHeightPt} 0 0 cm\n/Im${imageId} Do\nQ`
    const contentBytes = ascii(content)
    const contentId = addObject(`<< /Length ${contentBytes.length} >>\nstream\n${content}\nendstream`)
    const pageId = addObject(`<< /Type /Page /Parent 0 0 R /MediaBox [0 0 ${pageWidthPt} ${pageHeightPt}] /Resources << /XObject << /Im${imageId} ${imageId} 0 R >> >> /Contents ${contentId} 0 R >>`)
    pageObjectIds.push(pageId)
  })

  const pagesId = addObject('')
  const catalogId = addObject(`<< /Type /Catalog /Pages ${pagesId} 0 R >>`)
  objects[pagesId - 1] = [ascii(`<< /Type /Pages /Kids [${pageObjectIds.map((id) => `${id} 0 R`).join(' ')}] /Count ${pageObjectIds.length} >>`)]
  pageObjectIds.forEach((pageId) => {
    objects[pageId - 1] = [ascii(bytesToText(objects[pageId - 1]).replace('/Parent 0 0 R', `/Parent ${pagesId} 0 R`))]
  })

  return assemblePdf(objects, catalogId)
}

function assemblePdf(objects, catalogId) {
  const chunks = [ascii('%PDF-1.4\n%âãÏÓ\n')]
  const offsets = [0]
  let offset = chunks[0].length

  objects.forEach((objectChunks, index) => {
    offsets.push(offset)
    const header = ascii(`${index + 1} 0 obj\n`)
    const footer = ascii('\nendobj\n')
    chunks.push(header, ...objectChunks, footer)
    offset += header.length + objectChunks.reduce((total, chunk) => total + chunk.length, 0) + footer.length
  })

  const xrefOffset = offset
  const xrefLines = ['xref', `0 ${objects.length + 1}`, '0000000000 65535 f ']
  for (let index = 1; index <= objects.length; index += 1) {
    xrefLines.push(`${String(offsets[index]).padStart(10, '0')} 00000 n `)
  }
  const trailer = `${xrefLines.join('\n')}\ntrailer\n<< /Size ${objects.length + 1} /Root ${catalogId} 0 R >>\nstartxref\n${xrefOffset}\n%%EOF`
  chunks.push(ascii(trailer))

  return new Blob(chunks, { type: 'application/pdf' })
}

function ascii(text) {
  const bytes = new Uint8Array(text.length)
  for (let index = 0; index < text.length; index += 1) {
    bytes[index] = text.charCodeAt(index) & 0xff
  }
  return bytes
}

function bytesToText(chunks) {
  return chunks.map((chunk) => String.fromCharCode(...chunk)).join('')
}

function handleFileChange(event) {
  selectedFiles.value = Array.from(event.target.files || []).slice(0, 2)
}

function clearSelectedFile() {
  selectedFiles.value = []
}

function formatDate(value) {
  if (!value) {
    return '--'
  }

  const date = new Date(value)
  return new Intl.DateTimeFormat('zh-CN', {
    hour: '2-digit',
    minute: '2-digit'
  }).format(date)
}
</script>

<style lang="scss" scoped>
.chat-panel {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
  padding: 28px;
  overflow: hidden;
  background: linear-gradient(180deg, #f7fef9 0%, #ffffff 100%);
}

.init-message {
  margin: 0 0 14px;
  color: #166534;
  font-size: 13px;
}

.chat-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 18px;

  h1 {
    margin: 6px 0 0;
    font-size: 30px;
    color: #14532d;
  }
}

.chat-title-row {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

.chat-subtitle {
  margin: 0;
  color: #6b7280;
  font-size: 14px;
}

.chat-tags {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 10px;

  span {
    padding: 8px 12px;
    border-radius: 999px;
    background: #ecfdf5;
    color: #15803d;
    font-size: 12px;
    font-weight: 600;
  }
}

.tips-row {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  margin-bottom: 18px;
}

.tip-button {
  padding: 10px 14px;
  border: 1px solid rgba(34, 197, 94, 0.16);
  border-radius: 999px;
  background: #ffffff;
  color: #166534;
  cursor: pointer;
}

.message-container {
  display: flex;
  flex-direction: column;
  gap: 18px;
  flex: 1;
  min-height: 0;
  padding: 16px 4px 16px 0;
  overflow-y: auto;
}

.message-row {
  display: flex;
  align-items: flex-start;
  gap: 12px;

  &--user {
    flex-direction: row-reverse;

    .message-bubble {
      background: linear-gradient(135deg, #22c55e 0%, #16a34a 100%);
      color: #ffffff;
      border-bottom-right-radius: 8px;

      .message-role,
      span {
        color: rgba(255, 255, 255, 0.84);
      }
    }
  }

  &--assistant {
    .message-bubble {
      background: #ffffff;
      border: 1px solid rgba(34, 197, 94, 0.12);
      border-bottom-left-radius: 8px;
      box-shadow: 0 10px 28px rgba(15, 23, 42, 0.05);
    }
  }
}

.message-avatar {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 42px;
  height: 42px;
  border-radius: 14px;
  background: #dcfce7;
  color: #166534;
  font-weight: 700;
  flex-shrink: 0;
}

.message-bubble {
  max-width: min(760px, 88%);
  padding: 16px 18px;
  border-radius: 20px;

  p {
    margin: 8px 0 10px;
    white-space: pre-wrap;
    line-height: 1.8;
  }

  span {
    color: #9ca3af;
    font-size: 12px;
  }
}

.message-markdown {
  margin: 8px 0 10px;
  line-height: 1.8;
  color: inherit;

  :deep(h1),
  :deep(h2),
  :deep(h3),
  :deep(h4),
  :deep(h5),
  :deep(h6) {
    margin: 12px 0 8px;
    line-height: 1.5;
    color: inherit;
  }

  :deep(h1) {
    font-size: 24px;
  }

  :deep(h2) {
    font-size: 20px;
  }

  :deep(h3) {
    font-size: 18px;
  }

  :deep(p) {
    margin: 8px 0;
    white-space: normal;
  }

  :deep(ul),
  :deep(ol) {
    margin: 8px 0;
    padding-left: 20px;
  }

  :deep(li) {
    margin: 4px 0;
  }

  :deep(strong) {
    font-weight: 700;
  }

  :deep(code) {
    padding: 2px 6px;
    border-radius: 6px;
    background: rgba(15, 23, 42, 0.08);
    font-family: Consolas, 'Courier New', monospace;
    font-size: 13px;
  }

  :deep(pre) {
    margin: 12px 0;
    padding: 12px 14px;
    border-radius: 12px;
    background: rgba(15, 23, 42, 0.9);
    color: #f8fafc;
    overflow-x: auto;
  }

  :deep(pre code) {
    padding: 0;
    background: transparent;
    color: inherit;
  }

  :deep(blockquote) {
    margin: 12px 0;
    padding-left: 12px;
    border-left: 4px solid rgba(34, 197, 94, 0.35);
    color: #4b5563;
  }

  :deep(a) {
    color: #166534;
    text-decoration: underline;
  }

  :deep(table) {
    width: 100%;
    border-collapse: collapse;
    margin: 12px 0;
  }

  :deep(th),
  :deep(td) {
    border: 1px solid rgba(34, 197, 94, 0.18);
    padding: 8px 10px;
    text-align: left;
  }
}

.message-markdown {
  margin: 8px 0 10px;
  line-height: 1.8;
  color: inherit;

  :deep(h1),
  :deep(h2),
  :deep(h3),
  :deep(h4),
  :deep(h5),
  :deep(h6) {
    margin: 12px 0 8px;
    line-height: 1.5;
    color: inherit;
  }

  :deep(h1) {
    font-size: 24px;
  }

  :deep(h2) {
    font-size: 20px;
  }

  :deep(h3) {
    font-size: 18px;
  }

  :deep(p) {
    margin: 8px 0;
    white-space: normal;
  }

  :deep(ul),
  :deep(ol) {
    margin: 8px 0;
    padding-left: 20px;
  }

  :deep(li) {
    margin: 4px 0;
  }

  :deep(strong) {
    font-weight: 700;
  }

  :deep(code) {
    padding: 2px 6px;
    border-radius: 6px;
    background: rgba(15, 23, 42, 0.08);
    font-family: Consolas, 'Courier New', monospace;
    font-size: 13px;
  }

  :deep(pre) {
    margin: 12px 0;
    padding: 12px 14px;
    border-radius: 12px;
    background: rgba(15, 23, 42, 0.9);
    color: #f8fafc;
    overflow-x: auto;
  }

  :deep(pre code) {
    padding: 0;
    background: transparent;
    color: inherit;
  }

  :deep(blockquote) {
    margin: 12px 0;
    padding-left: 12px;
    border-left: 4px solid rgba(34, 197, 94, 0.35);
    color: #4b5563;
  }

  :deep(a) {
    color: #166534;
    text-decoration: underline;
  }

  :deep(table) {
    width: 100%;
    border-collapse: collapse;
    margin: 12px 0;
  }

  :deep(th),
  :deep(td) {
    border: 1px solid rgba(34, 197, 94, 0.18);
    padding: 8px 10px;
    text-align: left;
  }
}

.message-bubble--loading {
  border-style: dashed !important;
}

.message-bubble--failed {
  border-color: rgba(220, 38, 38, 0.24) !important;
  background: #fff7f7 !important;
}

.message-role {
  color: #15803d;
  font-size: 13px;
  font-weight: 700;
}

.thinking-panel {
  margin: 6px 0 8px;
  padding: 7px 8px;
  border: 1px solid rgba(20, 83, 45, 0.12);
  border-radius: 9px;
  background: #f7fee7;
  color: #3f6212;
}

.thinking-title {
  margin-bottom: 4px;
  font-size: 10px;
  font-weight: 700;
}

.thinking-panel pre {
  max-height: 120px;
  margin: 0;
  overflow-y: auto;
  white-space: pre-wrap;
  word-break: break-word;
  font-family: inherit;
  font-size: 10px;
  line-height: 1.35;
}

.suggestion-list {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin: 12px 0 10px;
}

.export-actions {
  display: flex;
  justify-content: flex-end;
  margin: 12px 0 8px;
}

.export-pdf-button {
  padding: 8px 14px;
  border: 1px solid rgba(22, 163, 74, 0.22);
  border-radius: 999px;
  background: #14532d;
  color: #ffffff;
  font-size: 13px;
  font-weight: 700;
  cursor: pointer;
  transition: transform 0.18s ease, box-shadow 0.18s ease;

  &:hover {
    transform: translateY(-1px);
    box-shadow: 0 10px 20px rgba(20, 83, 45, 0.18);
  }
}

.suggestion-button {
  max-width: 100%;
  padding: 8px 12px;
  border: 1px solid rgba(22, 163, 74, 0.18);
  border-radius: 999px;
  background: #f0fdf4;
  color: #166534;
  font-size: 13px;
  line-height: 1.4;
  text-align: left;
  cursor: pointer;

  &:hover:not(:disabled) {
    border-color: rgba(22, 163, 74, 0.36);
    background: #dcfce7;
  }

  &:disabled {
    opacity: 0.6;
    cursor: not-allowed;
  }
}

.loading-dots {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  margin-right: 8px;
  vertical-align: middle;

  i {
    width: 6px;
    height: 6px;
    border-radius: 50%;
    background: #16a34a;
    animation: blink 1.1s infinite ease-in-out;

    &:nth-child(2) {
      animation-delay: 0.15s;
    }

    &:nth-child(3) {
      animation-delay: 0.3s;
    }
  }
}

@keyframes blink {
  0%,
  80%,
  100% {
    opacity: 0.3;
    transform: scale(0.9);
  }

  40% {
    opacity: 1;
    transform: scale(1);
  }
}

.error-message {
  margin: 0 0 12px;
  color: #dc2626;
  font-size: 14px;
}

.composer {
  margin-top: 18px;
  padding: 18px;
  border-radius: 24px;
  background: #ffffff;
  border: 1px solid rgba(34, 197, 94, 0.12);
  box-shadow: 0 10px 30px rgba(15, 23, 42, 0.05);
}

.composer-main {
  display: flex;
  align-items: stretch;
  gap: 12px;
}

.composer-input {
  flex: 1;
  resize: none;
  border: none;
  background: transparent;
  color: #111827;
  line-height: 1.8;

  &:focus {
    outline: none;
  }
}

.composer-upload-button {
  position: relative;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 52px;
  min-width: 52px;
  border-radius: 16px;
  background: #ecfdf5;
  color: #15803d;
  cursor: pointer;
  border: 1px dashed rgba(34, 197, 94, 0.28);
  font-size: 22px;

  input {
    position: absolute;
    inset: 0;
    opacity: 0;
    cursor: pointer;
  }
}

.selected-file-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-top: 12px;
  color: #4b5563;
  font-size: 13px;
}

.remove-file-button {
  border: none;
  background: transparent;
  color: #dc2626;
  cursor: pointer;
}

.composer-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-top: 14px;
  color: #6b7280;
  font-size: 13px;
}

.send-button {
  min-width: 112px;
  height: 44px;
  border: none;
  border-radius: 14px;
  background: #16a34a;
  color: #ffffff;
  font-weight: 600;
  cursor: pointer;

  &:disabled {
    opacity: 0.72;
    cursor: not-allowed;
  }
}

.chat-panel {
  padding: 20px;
  font-size: 13px;
}

.init-message,
.message-role,
.suggestion-button,
.selected-file-row,
.composer-footer {
  font-size: 12px;
}

.chat-header {
  gap: 12px;
  margin-bottom: 12px;

  h1 {
    font-size: 22px;
  }
}

.chat-subtitle {
  font-size: 12px;
}

.chat-tags {
  gap: 6px;

  span {
    padding: 5px 8px;
    font-size: 11px;
  }
}

.tips-row {
  gap: 8px;
  margin-bottom: 12px;
}

.tip-button {
  padding: 7px 10px;
  font-size: 12px;
}

.message-container {
  gap: 12px;
  padding: 10px 4px 10px 0;
}

.message-row {
  gap: 8px;
}

.message-avatar {
  width: 34px;
  height: 34px;
  border-radius: 10px;
  font-size: 12px;
}

.message-bubble {
  max-width: min(700px, 86%);
  padding: 11px 13px;
  border-radius: 14px;
  font-size: 13px;

  p {
    margin: 6px 0 8px;
    line-height: 1.6;
  }

  span {
    font-size: 11px;
  }
}

.message-markdown {
  margin: 6px 0 8px;
  line-height: 1.6;
  font-size: 13px;

  :deep(h1) {
    font-size: 18px;
  }

  :deep(h2) {
    font-size: 16px;
  }

  :deep(h3) {
    font-size: 15px;
  }

  :deep(code) {
    font-size: 12px;
  }
}

.suggestion-list {
  gap: 6px;
  margin: 8px 0;
}

.suggestion-button {
  padding: 6px 9px;
}

.error-message {
  font-size: 12px;
}

.composer {
  margin-top: 12px;
  padding: 12px;
  border-radius: 16px;
}

.composer-main {
  gap: 8px;
}

.composer-input {
  font-size: 13px;
  line-height: 1.55;
}

.composer-upload-button {
  width: 42px;
  min-width: 42px;
  border-radius: 12px;
  font-size: 18px;
}

.composer-footer {
  margin-top: 10px;
}

.send-button {
  min-width: 92px;
  height: 36px;
  border-radius: 10px;
  font-size: 13px;
}

.chat-panel {
  padding: 16px;
  font-size: 12px;
}

.init-message,
.message-role,
.suggestion-button,
.selected-file-row,
.composer-footer,
.error-message {
  font-size: 11px;
}

.chat-header {
  margin-bottom: 10px;

  h1 {
    font-size: 19px;
  }
}

.chat-subtitle {
  font-size: 11px;
}

.chat-tags span {
  padding: 4px 7px;
  font-size: 10px;
}

.tip-button {
  padding: 6px 9px;
  font-size: 11px;
}

.message-container {
  gap: 10px;
}

.message-avatar {
  width: 30px;
  height: 30px;
  border-radius: 9px;
  font-size: 11px;
}

.message-bubble {
  padding: 9px 11px;
  font-size: 12px;

  p {
    line-height: 1.5;
  }

  span {
    font-size: 10px;
  }
}

.message-markdown {
  font-size: 12px;
  line-height: 1.5;

  :deep(h1) {
    font-size: 16px;
  }

  :deep(h2) {
    font-size: 15px;
  }

  :deep(h3) {
    font-size: 14px;
  }

  :deep(code) {
    font-size: 11px;
  }
}

.suggestion-button {
  padding: 5px 8px;
}

.composer {
  padding: 10px;
}

.composer-input {
  font-size: 12px;
}

.composer-upload-button {
  width: 38px;
  min-width: 38px;
  font-size: 16px;
}

.send-button {
  min-width: 84px;
  height: 32px;
  font-size: 12px;
}

.chat-panel {
  padding: 10px 12px;
  font-size: 11px;
}

.init-message,
.message-role,
.suggestion-button,
.selected-file-row,
.composer-footer,
.error-message {
  font-size: 10px;
}

.chat-header {
  gap: 8px;
  margin-bottom: 8px;

  h1 {
    margin-top: 3px;
    font-size: 16px;
  }
}

.chat-subtitle {
  font-size: 10px;
}

.chat-tags {
  gap: 4px;

  span {
    padding: 3px 6px;
    font-size: 9px;
  }
}

.tips-row {
  gap: 6px;
  margin-bottom: 8px;
}

.tip-button {
  padding: 5px 8px;
  font-size: 10px;
}

.message-container {
  gap: 8px;
  padding: 6px 2px 6px 0;
}

.message-row {
  gap: 6px;
}

.message-avatar {
  width: 26px;
  height: 26px;
  border-radius: 8px;
  font-size: 10px;
}

.message-bubble {
  max-width: min(820px, 90%);
  padding: 7px 9px;
  border-radius: 10px;
  font-size: 11px;

  p {
    margin: 4px 0 5px;
    line-height: 1.42;
  }

  span {
    font-size: 9px;
  }
}

.message-markdown {
  margin: 4px 0 5px;
  font-size: 11px;
  line-height: 1.42;

  :deep(h1) {
    font-size: 14px;
  }

  :deep(h2) {
    font-size: 13px;
  }

  :deep(h3) {
    font-size: 12px;
  }

  :deep(p),
  :deep(ul),
  :deep(ol) {
    margin: 4px 0;
  }

  :deep(code) {
    font-size: 10px;
  }
}

.suggestion-list {
  gap: 5px;
  margin: 6px 0;
}

.suggestion-button {
  padding: 4px 7px;
}

.composer {
  margin-top: 8px;
  padding: 8px;
  border-radius: 12px;
}

.composer-main {
  gap: 6px;
}

.composer-input {
  font-size: 11px;
  line-height: 1.4;
}

.composer-upload-button {
  width: 34px;
  min-width: 34px;
  border-radius: 10px;
  font-size: 14px;
}

.selected-file-row {
  gap: 8px;
  margin-top: 8px;
}

.composer-footer {
  gap: 8px;
  margin-top: 8px;
}

.send-button {
  min-width: 74px;
  height: 28px;
  border-radius: 8px;
  font-size: 11px;
}

@media (max-width: 960px) {
  .chat-panel {
    padding: 14px;
  }

  .chat-header,
  .composer-main,
  .composer-footer {
    flex-direction: column;
    align-items: flex-start;
  }

  .composer-upload-button {
    width: 100%;
    min-height: 48px;
  }

  .chat-tags {
    justify-content: flex-start;
  }

  .message-bubble {
    max-width: 100%;
  }
}

@media (max-width: 640px) {
  .chat-panel {
    height: 100dvh;
    min-height: 100dvh;
    padding: 10px 12px;
    overflow: hidden;
  }

  .chat-header {
    gap: 10px;
    margin-bottom: 10px;
  }

  .chat-title-row {
    gap: 8px;
  }

  .chat-header h1 {
    max-width: 100%;
    font-size: 18px;
    line-height: 1.25;
  }

  .chat-subtitle {
    font-size: 11px;
  }

  .chat-tags {
    display: none;
  }

  .tips-row {
    display: none;
  }

  .message-container {
    flex: 1;
    min-height: 0;
    gap: 10px;
    padding: 8px 0;
    overflow-y: auto;
    overscroll-behavior: contain;
  }

  .message-row {
    gap: 8px;
  }

  .message-avatar {
    width: 30px;
    min-width: 30px;
    height: 30px;
    border-radius: 10px;
    font-size: 11px;
  }

  .message-bubble {
    max-width: calc(100% - 38px);
    padding: 10px 12px;
    border-radius: 14px;
    font-size: 13px;
  }

  .message-row--user .message-bubble {
    max-width: calc(100% - 38px);
  }

  .message-markdown {
    overflow-wrap: anywhere;
  }

  .composer {
    flex-shrink: 0;
    margin-top: 8px;
    padding: 10px;
    border-radius: 16px;
    padding-bottom: max(10px, env(safe-area-inset-bottom));
  }

  .composer-main {
    flex-direction: row;
    align-items: stretch;
    gap: 8px;
  }

  .composer-input {
    min-height: 76px;
    max-height: 120px;
    font-size: 13px;
    line-height: 1.5;
  }

  .composer-upload-button {
    width: 44px;
    min-width: 44px;
    min-height: 44px;
    border-radius: 12px;
  }

  .composer-footer {
    align-items: stretch;
    gap: 8px;
  }

  .composer-footer span {
    display: none;
  }

  .send-button {
    width: 100%;
    min-width: 0;
  }
}
</style>

