import { useEffect, useRef, type ReactNode } from 'react'

/** Only the operation opened from the current viewer is mounted. */
export function ViewerDialog({ title, onClose, children }: {title:string;onClose:()=>void;children:ReactNode}) {
  const root=useRef<HTMLDialogElement>(null)
  useEffect(()=>{if(root.current&&!root.current.open)root.current.showModal()},[])
  return <dialog ref={root} className="viewer-operation-dialog" aria-label={title} onCancel={onClose} onClose={onClose}>
    <header><h2>{title}</h2><button type="button" aria-label={`关闭${title}`} onClick={onClose}>×</button></header>
    {children}
  </dialog>
}
