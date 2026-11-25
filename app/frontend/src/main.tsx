import React from 'react'
import { createRoot } from 'react-dom/client'
import App from './App'
import { isRenderProfilerEnabled } from './components/RenderProfiler'
import './styles/index'

function render(createAppRoot: typeof createRoot) {
  createAppRoot(document.getElementById('root')!).render(
    <React.StrictMode>
      <App />
    </React.StrictMode>,
  )
}

// The default production renderer omits Profiler callbacks.
if (!import.meta.env.DEV && isRenderProfilerEnabled()) {
  void import('react-dom/profiling').then(renderer => render(renderer.createRoot))
} else {
  render(createRoot)
}
