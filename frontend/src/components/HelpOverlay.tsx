/**
 * HelpOverlay — cinematic in-app help system for CrypTX.
 *
 * Opens as a full-screen overlay with professional animations explaining
 * the current module: what it does, input type, example, and expected output.
 */
import { useEffect, useState, useCallback, useRef } from 'react'
import { X, HelpCircle, Zap, ArrowRight, CheckCircle2, Lightbulb, Sparkles } from 'lucide-react'
import { getHelpForRoute, type HelpEntry } from './helpContent'

interface HelpOverlayProps {
  isOpen: boolean
  onClose: () => void
  pathname: string
}

export default function HelpOverlay({ isOpen, onClose, pathname }: HelpOverlayProps) {
  const [visible, setVisible] = useState(false)
  const [animStage, setAnimStage] = useState(0)
  const overlayRef = useRef<HTMLDivElement>(null)
  const help = getHelpForRoute(pathname)

  useEffect(() => {
    if (isOpen) {
      setVisible(true)
      setAnimStage(0)
      requestAnimationFrame(() => {
        requestAnimationFrame(() => setAnimStage(1))
        setTimeout(() => setAnimStage(2), 200)
        setTimeout(() => setAnimStage(3), 400)
        setTimeout(() => setAnimStage(4), 600)
        setTimeout(() => setAnimStage(5), 800)
      })
    } else {
      setAnimStage(0)
      const t = setTimeout(() => setVisible(false), 500)
      return () => clearTimeout(t)
    }
  }, [isOpen])

  const handleKeyDown = useCallback((e: KeyboardEvent) => {
    if (e.key === 'Escape') onClose()
  }, [onClose])

  useEffect(() => {
    if (isOpen) {
      document.addEventListener('keydown', handleKeyDown)
      document.body.style.overflow = 'hidden'
    }
    return () => {
      document.removeEventListener('keydown', handleKeyDown)
      document.body.style.overflow = ''
    }
  }, [isOpen, handleKeyDown])

  if (!visible || !help) return null

  return (
    <div
      ref={overlayRef}
      className={`help-overlay-root ${animStage >= 1 ? 'help-overlay-visible' : ''}`}
      onClick={(e) => { if (e.target === overlayRef.current) onClose() }}
    >
      {/* Animated background particles */}
      <div className="help-particles" aria-hidden="true">
        {Array.from({ length: 20 }).map((_, i) => (
          <span key={i} className="help-particle" style={{
            '--i': i,
            '--x': `${Math.random() * 100}%`,
            '--y': `${Math.random() * 100}%`,
            '--delay': `${Math.random() * 2}s`,
            '--duration': `${3 + Math.random() * 4}s`,
            '--size': `${2 + Math.random() * 4}px`,
          } as React.CSSProperties} />
        ))}
      </div>

      {/* Main content panel */}
      <div className={`help-panel ${animStage >= 1 ? 'help-panel-enter' : ''}`}>
        {/* Header */}
        <div className={`help-header ${animStage >= 2 ? 'help-header-enter' : ''}`}>
          <div className="help-header-badge">
            <HelpCircle size={18} />
            <span>How to use this feature</span>
          </div>
          <button className="help-close-btn" onClick={onClose} aria-label="Close help">
            <X size={20} />
          </button>
        </div>

        {/* Title section */}
        <div className={`help-title-section ${animStage >= 2 ? 'help-title-enter' : ''}`}>
          <div className="help-title-icon">
            <Sparkles size={24} />
          </div>
          <h1 className="help-title">{help.title}</h1>
          <p className="help-subtitle">{help.subtitle}</p>
        </div>

        {/* Content sections with staggered animation */}
        <div className="help-content">
          {/* What it does */}
          <div className={`help-section ${animStage >= 3 ? 'help-section-enter' : ''}`} style={{ transitionDelay: '0ms' }}>
            <div className="help-section-header">
              <div className="help-section-icon help-icon-what">
                <Zap size={16} />
              </div>
              <h2>What it does</h2>
            </div>
            <p className="help-description">{help.description}</p>
          </div>

          {/* Input */}
          <div className={`help-section ${animStage >= 3 ? 'help-section-enter' : ''}`} style={{ transitionDelay: '150ms' }}>
            <div className="help-section-header">
              <div className="help-section-icon help-icon-input">
                <ArrowRight size={16} />
              </div>
              <h2>Input</h2>
            </div>
            <div className="help-input-box">
              <div className="help-input-type">
                <span className="help-label">Type</span>
                <span>{help.inputType}</span>
              </div>
              <div className="help-input-example">
                <span className="help-label">Example</span>
                <code>{help.inputExample}</code>
              </div>
            </div>
          </div>

          {/* Output */}
          <div className={`help-section ${animStage >= 4 ? 'help-section-enter' : ''}`} style={{ transitionDelay: '300ms' }}>
            <div className="help-section-header">
              <div className="help-section-icon help-icon-output">
                <CheckCircle2 size={16} />
              </div>
              <h2>Expected Output</h2>
            </div>
            <p className="help-description">{help.outputDescription}</p>
          </div>

          {/* Tips */}
          {help.tips && help.tips.length > 0 && (
            <div className={`help-section ${animStage >= 5 ? 'help-section-enter' : ''}`} style={{ transitionDelay: '450ms' }}>
              <div className="help-section-header">
                <div className="help-section-icon help-icon-tips">
                  <Lightbulb size={16} />
                </div>
                <h2>Pro Tips</h2>
              </div>
              <ul className="help-tips-list">
                {help.tips.map((tip, i) => (
                  <li key={i} className="help-tip-item">
                    <span className="help-tip-bullet" />
                    <span>{tip}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className={`help-footer ${animStage >= 5 ? 'help-footer-enter' : ''}`}>
          <span className="help-footer-hint">Press <kbd>Esc</kbd> to close</span>
        </div>
      </div>
    </div>
  )
}
