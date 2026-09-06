import { createContext, useContext, useEffect, useMemo, useRef, useState } from 'react'
import {
  AUTH_TOKEN_KEY,
  AUTH_REFRESH_TOKEN_KEY,
  changeAuthPassword,
  fetchCurrentSession,
  listAuthSessions,
  loginUser,
  logoutUser,
  logoutOtherSessions,
  registerUser,
  revokeAuthSession,
  requestPasswordReset,
  resetPassword,
  updateAuthProfile,
  verify2FALogin,
  beaconLogout,
  type AuthSession,
  type AuthSessionInfo,
  type AuthUser,
  type LoginResponse,
} from '../api/client'

type AuthMode = 'login' | 'register' | 'forgot' | 'reset'

interface AuthContextValue {
  user: AuthUser | null
  session: AuthSessionInfo | null
  loading: boolean
  mode: AuthMode
  setMode: (mode: AuthMode) => void
  signIn: (email: string, password: string) => Promise<LoginResponse>
  signIn2FA: (pendingToken: string, code: string) => Promise<void>
  signUp: (payload: { email: string; password: string; name?: string; registration_type?: string; team_name?: string }) => Promise<void>
  forgotPassword: (email: string) => Promise<{ dev_reset_token?: string | null }>
  completeReset: (token: string, password: string) => Promise<void>
  updateProfile: (payload: { name: string }) => Promise<void>
  changePassword: (payload: { current_password: string; new_password: string }) => Promise<void>
  listSessions: () => Promise<{ current_session_id: string; sessions: AuthSessionInfo[] }>
  revokeSession: (sessionId: string) => Promise<void>
  logoutOthers: () => Promise<void>
  signOut: () => Promise<void>
}

const AuthContext = createContext<AuthContextValue | null>(null)

function persistSession(session: AuthSession, setUser: (u: AuthUser) => void, setSession: (s: AuthSessionInfo | null) => void) {
  sessionStorage.setItem(AUTH_TOKEN_KEY, session.access_token)
  sessionStorage.setItem(AUTH_REFRESH_TOKEN_KEY, session.refresh_token)
  setUser(session.user)
  setSession(session.session || null)
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null)
  const [session, setSession] = useState<AuthSessionInfo | null>(null)
  const [loading, setLoading] = useState(true)
  const [mode, setMode] = useState<AuthMode>('login')
  const beaconFired = useRef(false)

  async function signOut() {
    const refresh = sessionStorage.getItem(AUTH_REFRESH_TOKEN_KEY)
    try {
      await logoutUser(refresh)
    } catch {
      // Local cleanup still happens when the server is unavailable.
    }
    sessionStorage.removeItem(AUTH_TOKEN_KEY)
    sessionStorage.removeItem(AUTH_REFRESH_TOKEN_KEY)
    setUser(null)
    setSession(null)
    setMode('login')
  }

  /* ── Session bootstrap + tab-close beacon ── */
  useEffect(() => {
    let cancelled = false
    async function load() {
      const token = sessionStorage.getItem(AUTH_TOKEN_KEY)
      if (!token) {
        setLoading(false)
        return
      }
      try {
        const current = await fetchCurrentSession()
        if (!cancelled) {
          setUser(current.user)
          setSession(current.session)
        }
      } catch {
        sessionStorage.removeItem(AUTH_TOKEN_KEY)
        sessionStorage.removeItem(AUTH_REFRESH_TOKEN_KEY)
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    load()

    const onExpired = () => signOut()
    window.addEventListener('cryptx-auth-expired', onExpired)

    // Beacon logout on tab close — revokes the server-side session after 1 min
    const onBeforeUnload = () => {
      if (!beaconFired.current && sessionStorage.getItem(AUTH_TOKEN_KEY)) {
        beaconFired.current = true
        beaconLogout()
      }
    }
    window.addEventListener('beforeunload', onBeforeUnload)

    return () => {
      cancelled = true
      window.removeEventListener('cryptx-auth-expired', onExpired)
      window.removeEventListener('beforeunload', onBeforeUnload)
    }
  }, [])

  const value = useMemo<AuthContextValue>(() => ({
    user,
    session,
    loading,
    mode,
    setMode,
    signIn: async (email, password) => {
      const result = await loginUser(email, password)
      // If 2FA is required, return the response without persisting a session
      if (result.requires_2fa) {
        return result
      }
      // Normal login — persist the session
      persistSession(result as AuthSession, setUser, setSession)
      return result
    },
    signIn2FA: async (pendingToken, code) => {
      const session = await verify2FALogin(pendingToken, code)
      persistSession(session, setUser, setSession)
    },
    signUp: async payload => {
      persistSession(await registerUser(payload), setUser, setSession)
    },
    forgotPassword: async email => requestPasswordReset(email),
    completeReset: async (token, password) => {
      await resetPassword(token, password)
      setMode('login')
    },
    updateProfile: async payload => {
      setUser(await updateAuthProfile(payload))
    },
    changePassword: async payload => {
      persistSession(await changeAuthPassword(payload), setUser, setSession)
    },
    listSessions: listAuthSessions,
    revokeSession: revokeAuthSession,
    logoutOthers: logoutOtherSessions,
    signOut,
  }), [user, session, loading, mode])

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used inside AuthProvider')
  return ctx
}
