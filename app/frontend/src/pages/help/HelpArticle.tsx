import { Fragment, useEffect, useMemo, useRef, useState } from 'react'
import { helpIllustrations } from './helpIllustrations'

type Block = { type: 'heading' | 'paragraph' | 'ordered' | 'unordered' | 'table' | 'image'; lines: string[] }

// Only allow bundled illustrations by key. Help content cannot select a URL,
// local file or remote resource, and all other text is escaped by React.
function blocks(body: string): Block[] {
  const lines = body.replace(/\r\n?/g, '\n').split('\n')
  const result: Block[] = []
  const tableDivider = (line: string) => /^\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?$/.test(line.trim())
  for (let i = 0; i < lines.length;) {
    const line = lines[i].trim()
    if (!line) { i++; continue }
    const illustration = /^!\[([^\]]+)\]\(help:([a-z0-9-]+)\)$/.exec(line)
    if (illustration && Object.prototype.hasOwnProperty.call(helpIllustrations, illustration[2])) {
      result.push({ type: 'image', lines: [illustration[1], illustration[2]] }); i++; continue
    }
    if (/^#{2,3} /.test(line)) {
      result.push({ type: 'heading', lines: [line.replace(/^#{2,3} /, '')] }); i++; continue
    }
    if (line.startsWith('|') && tableDivider(lines[i + 1] ?? '')) {
      const rows = [line]; i += 2
      while (i < lines.length && lines[i].trim().startsWith('|')) rows.push(lines[i++].trim())
      result.push({ type: 'table', lines: rows }); continue
    }
    const ordered = /^\d+\. /.test(line), unordered = /^- /.test(line)
    if (ordered || unordered) {
      const pattern = ordered ? /^\d+\. / : /^- /, items: string[] = []
      while (i < lines.length && pattern.test(lines[i].trim())) items.push(lines[i++].trim().replace(pattern, ''))
      result.push({ type: ordered ? 'ordered' : 'unordered', lines: items }); continue
    }
    const paragraph = [line]; i++
    while (i < lines.length && lines[i].trim() && !/^(#{2,3} |\d+\. |- |\||!\[)/.test(lines[i].trim())) paragraph.push(lines[i++].trim())
    result.push({ type: 'paragraph', lines: [paragraph.join('\n')] })
  }
  return result
}

function inline(text: string) {
  return text.split(/(`[^`]+`|\*\*[^*]+\*\*)/g).map((part, i) =>
    part.startsWith('`') ? <code key={i}>{part.slice(1, -1)}</code> :
      part.startsWith('**') ? <strong key={i}>{part.slice(2, -2)}</strong> : <Fragment key={i}>{part}</Fragment>)
}

export function HelpArticle({ body, slug }: { body: string; slug: string }) {
  const content = useMemo(() => blocks(body), [body])
  const dialog = useRef<HTMLDialogElement>(null)
  const [enlarged, setEnlarged] = useState<{ caption: string; key: string } | null>(null)
  useEffect(() => { dialog.current?.close() }, [slug])
  const headings = content.flatMap((block, i) => block.type === 'heading' ? [{ title: block.lines[0], id: `help-${slug}-${i}` }] : [])
  return <div className="help-manual" aria-label="使用说明正文">
    {headings.length > 1 && <nav className="help-contents" aria-label="本节目录">
      <strong>本节目录</strong>
      {headings.map(item => <a key={item.id} href={`#${item.id}`} onClick={event => {
        event.preventDefault()
        const heading = document.getElementById(item.id)
        heading?.scrollIntoView({ block: 'start' })
        heading?.focus({ preventScroll: true })
      }}>{item.title}</a>)}
    </nav>}
    {content.map((block, i) => {
      if (block.type === 'image') {
        const [caption, key] = block.lines, picture = helpIllustrations[key]
        return <figure className="help-illustration" key={i}>
          <button type="button" className="help-image-button" aria-label={`放大查看：${caption}`} onClick={() => {
            setEnlarged({ caption, key })
            dialog.current?.showModal()
          }}>
            <img src={picture.src} alt={caption} width={picture.width} height={picture.height} loading="lazy" />
          </button>
          <figcaption>{caption}<span>点击放大</span></figcaption>
        </figure>
      }
      if (block.type === 'heading') return <h3 key={i} id={`help-${slug}-${i}`} tabIndex={-1}>{block.lines[0]}</h3>
      if (block.type === 'ordered' || block.type === 'unordered') {
        const List = block.type === 'ordered' ? 'ol' : 'ul'
        return <List key={i}>{block.lines.map((line, j) => <li key={j}>{inline(line)}</li>)}</List>
      }
      if (block.type === 'table') {
        const rows = block.lines.map(line => line.replace(/^\|/, '').replace(/\|$/, '').split('|').map(cell => cell.trim()))
        return <div className="help-table-scroll" key={i} role="region" aria-label="参数说明表" tabIndex={0}><table>
          <thead><tr>{rows[0].map((cell, j) => <th key={j} scope="col">{inline(cell)}</th>)}</tr></thead>
          <tbody>{rows.slice(1).map((row, j) => <tr key={j}>{row.map((cell, k) => <td key={k}>{inline(cell)}</td>)}</tr>)}</tbody>
        </table></div>
      }
      return <p key={i}>{inline(block.lines[0])}</p>
    })}
    <dialog className="help-image-dialog" ref={dialog} aria-label={enlarged?.caption ?? '帮助图片'}
      onClose={() => setEnlarged(null)} onClick={event => { if (event.target === event.currentTarget) dialog.current?.close() }}>
      <div className="help-image-heading"><strong>{enlarged?.caption}</strong>
        <button type="button" className="secondary-button" autoFocus onClick={() => dialog.current?.close()}>关闭大图</button>
      </div>
      {enlarged && <img src={helpIllustrations[enlarged.key].src} alt={enlarged.caption} />}
    </dialog>
  </div>
}
