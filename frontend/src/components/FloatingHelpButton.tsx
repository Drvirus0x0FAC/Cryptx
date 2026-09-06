/**
 * FloatingHelpButton — animated floating help button positioned bottom-right.
 * Hidden on the home page. Features a gradient glow, orbiting ring, and
 * bounce entrance for a catchy, dynamic feel.
 */
import { useEffect, useState } from 'react'
import { useLocation } from 'react-router-dom'
import { HelpCircle } from 'lucide-react'

interface FloatingHelpButtonProps {
  onClick: () => void
}

export default function FloatingHelpButton({ onClick }: FloatingHelpButtonProps) {
  const [entered, setEntered] = useState(false)
  const [hovered, setHovered] = useState(false)
  const location = useLocation()

  // Hide on home page
  const isHome = location.pathname === '/'

  // Entrance animation on mount and route change
  useEffect(() => {
    if (isHome) {
      setEntered(false)
      return
    }
    setEntered(false)
    const t = requestAnimationFrame(() => {
      requestAnimationFrame(() => setEntered(true))
    })
    return () => cancelAnimationFrame(t)
  }, [location.pathname, isHome])

  if (isHome) return null

  return (
    <div className={`floating-help-root ${entered ? 'floating-help-entered' : ''}`}>
      <button
        className={`floating-help-btn ${hovered ? 'floating-help-hovered' : ''}`}
        onClick={onClick}
        onMouseEnter={() => setHovered(true)}
        onMouseLeave={() => setHovered(false)}
        aria-label="How to use this feature"
        title="How to use this feature"
      >
        {/* Orbiting ring */}
        <span className="floating-help-orbit" aria-hidden="true">
          <span className="floating-help-orbit-dot" />
        </span>
        {/* Pulse rings */}
        <span className="floating-help-pulse-ring floating-help-pulse-ring-1" />
        <span className="floating-help-pulse-ring floating-help-pulse-ring-2" />
        {/* Icon */}
        <span className="floating-help-icon">
          <HelpCircle size={22} strokeWidth={2} />
        </span>
      </button>
      <span className={`floating-help-label ${hovered ? 'floating-help-label-visible' : ''}`}>
        How to use this?
      </span>
    </div>
  )
}
