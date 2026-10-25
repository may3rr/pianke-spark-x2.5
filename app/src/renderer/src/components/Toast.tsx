import { closeToast, undoToast, useToast } from '../lib/toast'
import { XmarkIcon } from './Icons'

export default function Toast() {
  const t = useToast()
  if (!t) return null
  return (
    <div className="toast" key={t.id} role="status" data-toast>
      <span className="toast-text">{t.text}</span>
      {t.undo && (
        <button className="link-accent t13" onClick={undoToast} data-toast-undo>
          撤销
        </button>
      )}
      <button className="icon-btn" aria-label="关闭" onClick={closeToast}>
        <XmarkIcon size={12} />
      </button>
    </div>
  )
}
