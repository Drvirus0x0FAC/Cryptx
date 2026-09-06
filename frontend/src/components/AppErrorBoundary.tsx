import React from 'react'
import { AlertTriangle, RotateCcw } from 'lucide-react'
import i18n from '../i18n'

type Props = {
  children: React.ReactNode
}

type State = {
  error: Error | null
}

export default class AppErrorBoundary extends React.Component<Props, State> {
  state: State = { error: null }

  static getDerivedStateFromError(error: Error): State {
    return { error }
  }

  componentDidCatch(error: Error) {
    console.error('UI render failure', error)
  }

  render() {
    if (!this.state.error) return this.props.children

    // Class components can't use the useTranslation hook; read from the i18next
    // instance directly. The error boundary sits high in the tree, so it can
    // safely rely on the already-initialised single language.
    const t = i18n.t.bind(i18n)

    return (
      <div className="min-h-screen bg-bg-primary p-6 text-text-primary">
        <div className="mx-auto max-w-3xl rounded-lg border border-risk-mixer/40 bg-risk-mixer/10 p-5">
          <div className="flex items-start gap-3">
            <AlertTriangle className="mt-0.5 shrink-0 text-risk-mixer" size={20} />
            <div className="min-w-0">
              <p className="text-sm font-bold uppercase tracking-widest text-risk-mixer">{t('components:errorBoundary.title')}</p>
              <p className="mt-2 text-sm text-text-secondary">
                {t('components:errorBoundary.message')}
              </p>
              <pre className="mt-3 max-h-64 overflow-auto rounded border border-border bg-bg-primary/70 p-3 text-xs text-text-secondary">
                {this.state.error.message}
              </pre>
              <button className="btn-secondary mt-4" onClick={() => this.setState({ error: null })}>
                <RotateCcw size={14} />
                {t('components:errorBoundary.returnToApp')}
              </button>
            </div>
          </div>
        </div>
      </div>
    )
  }
}
