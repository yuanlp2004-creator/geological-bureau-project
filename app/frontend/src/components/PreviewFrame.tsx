import type { ComponentPropsWithoutRef } from 'react'
import selectionStyles from '../styles/text-selection.css?inline'

type Props = ComponentPropsWithoutRef<'iframe'> & { srcDoc: string }

export function PreviewFrame({ srcDoc, ...props }: Props) {
  const previewHtml = srcDoc.replace('</head>', () => `<style>${selectionStyles}</style></head>`)
  return <iframe {...props} srcDoc={previewHtml} />
}
