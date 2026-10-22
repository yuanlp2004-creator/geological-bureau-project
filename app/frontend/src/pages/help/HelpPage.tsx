import { TaskLayout } from '../../layout/TaskLayout'
import { SectionHeading } from '../../components/SectionHeading'
import { useEffect, useRef, useState } from 'react'
import { BookOpen, Search, X } from 'lucide-react'
import { api, type HelpTopic } from '../../api'
import { HelpArticle } from './HelpArticle'
import './help.css'

export function HelpPage({ token, onToast }: { token: string; onToast: (message: string) => void }) {
  const [topics, setTopics] = useState<HelpTopic[]>([])
  const [selected, setSelected] = useState<HelpTopic | null>(null)
  const [query, setQuery] = useState('')
  const requestId = useRef(0)
  const catalogue = useRef<HelpTopic[]>([])
  const article = useRef<HTMLElement>(null)
  const load = async (value = '') => {
    const currentRequest = ++requestId.current
    try {
      const result = await api.helpTopics(token, value)
      if (currentRequest !== requestId.current) return
      if (!value) catalogue.current = result
      setTopics(result)
      setSelected((current) =>
        result.find((item) => item.slug === current?.slug) ?? result[0] ?? null
      )
    } catch (error) {
      if (currentRequest !== requestId.current) return
      onToast(error instanceof Error ? error.message : '无法读取帮助内容')
    }
  }
  useEffect(() => {
    void load()
    return () => { requestId.current++ }
  }, [])
  const updateQuery = (value: string) => {
    setQuery(value)
    void load(value)
  }
  const selectTopic = (topic: HelpTopic) => {
    setSelected(topic)
    article.current?.scrollIntoView({ block: 'start' })
  }
  const related = selected ? catalogue.current.filter(topic => topic.slug !== selected.slug &&
    topic.related_routes.some(route => selected.related_routes.includes(route))).slice(0, 5) : []
  return (
    <div className="page-content help-page refined-page remaining-page" data-testid="help-page">
      
      <TaskLayout className="help-grid" showEmptyRail hasItems={Boolean(topics.length)} current={selected?.title ?? '没有匹配主题'}>
        <section className="surface help-index">
          <div className="surface-heading">
            <div>
              <h2>主题目录</h2>
            </div>
            <div className="help-index-meta">
              <span>{topics.length} 项</span>
              <BookOpen size={17} />
            </div>
          </div>
           <div className="search-field">
          <Search size={15} />
          <input
            aria-label="搜索帮助主题"
            value={query}
            onChange={(event) => updateQuery(event.target.value)}
            placeholder="搜索帮助主题"
          />
          {query && (
            <button
              className="help-search-clear"
              title="清空搜索"
              aria-label="清空搜索"
              onClick={() => updateQuery('')}
            >
              <X size={14} />
            </button>
          )}
        </div> 
<div className="help-topic-list">
            {topics.map((topic) => (
              <button
                className={`help-topic-row ${selected?.slug === topic.slug ? 'active' : ''}`}
                aria-pressed={selected?.slug === topic.slug}
                key={topic.slug}
                onClick={() => selectTopic(topic)}
              >
                <span>
                  <strong>{topic.title}</strong>
                  <small>
                    {topic.section} · {topic.keywords.slice(0, 3).join(' / ')}
                  </small>
                </span>
              </button>
            ))}
            {topics.length === 0 && <div className="help-index-empty">没有匹配主题</div>}
          </div>
        </section>
        <section className="surface help-article" ref={article}>
          {selected ? (
            <>
              <header className="surface-heading">
                <SectionHeading title={selected.title} description={selected.section} />
              </header>
              <HelpArticle body={selected.body} slug={selected.slug} />
              {related.length > 0 && <nav className="help-related" aria-label="继续阅读">
                <strong>继续阅读</strong>
                {related.map(topic => <button key={topic.slug} className="secondary-button" onClick={() => selectTopic(topic)}>{topic.title}</button>)}
              </nav>}
            </>
          ) : (
            <div className="empty-state">没有匹配的帮助主题</div>
          )}
        </section>
      </TaskLayout>
    </div>
  )
}
