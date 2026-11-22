import { useLayoutEffect, useRef, type ReactNode } from 'react'
import './legacy-viewing.css'

/** Size the viewing desk between its real top edge and the existing information panel. */
export function LegacyViewingDesk({children}:{children:ReactNode}) {
  const root=useRef<HTMLDivElement>(null)
  useLayoutEffect(()=>{
    const element=root.current
    if(!element)return
    let frame=0
    const update=()=>{
      cancelAnimationFrame(frame)
      frame=requestAnimationFrame(()=>{
        const log=document.querySelector('[data-testid="runtime-messages"]')?.getBoundingClientRect()
        const bottom=log?.top??window.innerHeight
        const height=Math.max(300,Math.floor(bottom-element.getBoundingClientRect().top-8))
        if(element.style.height!==`${height}px`)element.style.height=`${height}px`
      })
    }
    const observer=new ResizeObserver(update)
    if(element.parentElement)observer.observe(element.parentElement)
    const log=document.querySelector('[data-testid="runtime-messages"]')
    if(log)observer.observe(log)
    window.addEventListener('resize',update);update()
    return()=>{cancelAnimationFrame(frame);observer.disconnect();window.removeEventListener('resize',update)}
  },[])
  return <div className="legacy-view-desk" ref={root}>{children}</div>
}
