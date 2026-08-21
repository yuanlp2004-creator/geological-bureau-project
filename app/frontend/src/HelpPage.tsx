import { useEffect, useState } from 'react'
import { BookOpen, Search, X } from 'lucide-react'
import { api, type HelpTopic } from './api'

export function HelpPage({ token, onToast }: { token: string; onToast: (message: string) => void }) {
  const [topics, setTopics] = useState<HelpTopic[]>([])
  const [selected, setSelected] = useState<HelpTopic | null>(null)
  const [query, setQuery] = useState('')
  const load = async (value = '') => { try { const result = await api.helpTopics(token, value); setTopics(result); setSelected((current) => current && result.some((item) => item.slug === current.slug) ? current : result[0] ?? null) } catch (error) { onToast(error instanceof Error ? error.message : '无法读取帮助内容') } }
  useEffect(() => { void load() }, [])
  const updateQuery = (value: string) => { setQuery(value); void load(value) }
  return <div className="page-content help-page" data-testid="help-page">
    <div className="page-intro help-intro">
      <div><span className="section-kicker">S20 / OFFLINE HELP</span><h1>帮助中心</h1><p>离线帮助覆盖导航、核心流程、错误码、兼容性、设备安全与维护。</p></div>
      <div className="search-field"><Search size={15} /><input aria-label="搜索帮助主题" value={query} onChange={(event) => updateQuery(event.target.value)} placeholder="搜索帮助主题" />{query && <button className="help-search-clear" title="清空搜索" aria-label="清空搜索" onClick={() => updateQuery('')}><X size={14} /></button>}</div>
    </div>
    <div className="help-grid">
      <section className="surface help-index">
        <div className="surface-heading"><div><span className="section-kicker">TABLE OF CONTENTS</span><h2>主题目录</h2></div><div className="help-index-meta"><span>{topics.length} 项</span><BookOpen size={17} /></div></div>
        <div className="help-topic-list">{topics.map((topic) => <button className={`help-topic-row ${selected?.slug === topic.slug ? 'active' : ''}`} aria-pressed={selected?.slug === topic.slug} key={topic.slug} onClick={() => setSelected(topic)}><span><strong>{topic.title}</strong><small>{topic.section} · {topic.keywords.slice(0, 3).join(' / ')}</small></span></button>)}{topics.length === 0 && <div className="help-index-empty">没有匹配主题</div>}</div>
      </section>
      <section className="surface help-article">{selected ? <><header><span className="section-kicker">{selected.section.toUpperCase()}</span><h2>{selected.title}</h2></header><p>{selected.body}</p><div className="help-routes"><strong>关联模块</strong>{selected.related_routes.map((route) => <code key={route}>{route}</code>)}</div></> : <div className="empty-state">没有匹配的帮助主题</div>}</section>
    </div>
  </div>
}
