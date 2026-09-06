import { Routes, Route, Navigate, useParams } from 'react-router-dom'
import { lazy, Suspense, useState, FormEvent } from 'react'
import Layout from './components/Layout'
import MobileNav from './components/MobileNav'
import BootScreen from './components/BootScreen'
// Eager: entry-point pages needed for first paint / auth gate
import Dashboard from './pages/Dashboard'
import AuthScreen from './pages/AuthScreen'
import { useAuth } from './auth/AuthContext'
import { useLocation } from 'react-router-dom'
import { AlertTriangle, Loader2, LockKeyhole, ShieldCheck } from 'lucide-react'

// P8 fix: lazy-load the heavy investigation pages so they split into separate
// chunks instead of all shipping in the initial bundle. NexusGraph alone is
// ~272KB; BoardCanvas ~101KB. This cuts initial-load significantly.
const AddressIntel = lazy(() => import('./pages/AddressIntel'))
const FundTracer = lazy(() => import('./pages/FundTracer'))
const DexAnalysis = lazy(() => import('./pages/DexAnalysis'))
const Settings = lazy(() => import('./pages/Settings'))
const BatchScreener = lazy(() => import('./pages/BatchScreener'))
const CaseManager = lazy(() => import('./pages/CaseManager'))
const CaseDetail = lazy(() => import('./pages/CaseDetail'))
const LabelIntel = lazy(() => import('./pages/LabelIntel'))
const NexusGraph = lazy(() => import('./pages/NexusGraph'))
const TxLens = lazy(() => import('./pages/TxLens'))
const EvidenceVault = lazy(() => import('./pages/EvidenceVault'))
const AiAgentPage = lazy(() => import('./pages/AiAgentPage'))
const VictimReportPage = lazy(() => import('./pages/VictimReportPage'))
const WalletMonitor = lazy(() => import('./pages/WalletMonitor'))
const NFTTronSentinel = lazy(() => import('./pages/NFTTronSentinel'))
const SanctionsScreener = lazy(() => import('./pages/SanctionsScreener'))
const RegulatoryReports = lazy(() => import('./pages/RegulatoryReports'))
const DemixLab = lazy(() => import('./pages/DemixLab'))
const AttributionLookup = lazy(() => import('./pages/AttributionLookup'))
const AutoInvestigate = lazy(() => import('./pages/AutoInvestigate'))
const UserProfile = lazy(() => import('./pages/UserProfile'))
const Boards = lazy(() => import('./pages/Boards'))
const BoardCanvas = lazy(() => import('./pages/BoardCanvas'))
const BoardSharedView = lazy(() => import('./pages/BoardSharedView'))
const OsintSweepPage = lazy(() => import('./pages/OsintSweepPage'))
const AttributionSubmissions = lazy(() => import('./pages/AttributionSubmissions'))
const BlockchainThreatLandscape = lazy(() => import('./pages/BlockchainThreatLandscape'))
const ReportStudio = lazy(() => import('./pages/ReportStudio'))
const EntityInvestigation = lazy(() => import('./pages/EntityInvestigation'))
const VictimPortal = lazy(() => import('./pages/VictimPortal'))
const DocsScreen = lazy(() => import('./pages/DocsScreen'))
const ContractForensics = lazy(() => import('./pages/ContractForensics'))
const LaunderingTrace = lazy(() => import('./pages/LaunderingTrace'))
const CourtReadiness = lazy(() => import('./pages/CourtReadiness'))
const RecoveryOps = lazy(() => import('./pages/RecoveryOps'))
const ComplianceSuite = lazy(() => import('./pages/ComplianceSuite'))
const FreezeDesk = lazy(() => import('./pages/FreezeDesk'))
const ScamNetworkAtlas = lazy(() => import('./pages/ScamNetworkAtlas'))
const PerpDexIntel = lazy(() => import('./pages/PerpDexIntel'))
const PredictiveIntel = lazy(() => import('./pages/PredictiveIntel'))
const InvestigationGraphHost = lazy(() => import('./pages/InvestigationGraphHost'))
// Phase 1 commercial-launch pages
const NlAgentPage = lazy(() => import('./pages/NlAgentPage'))
const EntitySearchPage = lazy(() => import('./pages/EntitySearchPage'))
const RuleBuilder = lazy(() => import('./pages/RuleBuilder'))
const TeamManagement = lazy(() => import('./pages/TeamManagement'))
const CaseTaskManagement = lazy(() => import('./pages/CaseTaskManagement'))
const CaseAudit = lazy(() => import('./pages/CaseAudit'))

// Suspense fallback for lazy-loaded chunks
const PageLoader = () => (
  <div className="auth-loading">
    <img src="/cryptx-icon.svg" alt="CrypTX" />
    <span>Loading module…</span>
  </div>
)

function AddressIntelRedirect() {
  const { addr } = useParams()
  return <Navigate to={`/intel/${addr}`} replace />
}

function NexusRedirect() {
  const { addr } = useParams()
  return <Navigate to={addr ? `/nexus/${addr}` : '/nexus'} replace />
}

function HolisticAddrRedirect() {
  const { addr } = useParams()
  return <Navigate to={addr ? `/trace/${addr}` : '/trace'} replace />
}

function ForcePasswordChange() {
  const auth = useAuth()
  const [newPw, setNewPw] = useState('')
  const [confirmPw, setConfirmPw] = useState('')
  const [currentPw, setCurrentPw] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    if (newPw !== confirmPw) { setError('Passwords do not match'); return }
    setBusy(true); setError('')
    try {
      await auth.changePassword({ current_password: currentPw, new_password: newPw })
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally { setBusy(false) }
  }

  return (
    <div style={{
      position: 'fixed', inset: 0, zIndex: 99999,
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      background: 'rgb(var(--bg-deep, 10 12 18))',
    }}>
      <div style={{
        width: 400, padding: 32, borderRadius: 16,
        background: 'rgb(var(--bg-card, 18 22 30))',
        border: '1px solid rgb(var(--bg-border, 40 44 55) / 0.6)',
        boxShadow: '0 24px 64px rgb(0 0 0 / 0.5)',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 20 }}>
          <LockKeyhole size={20} style={{ color: 'rgb(var(--cxv-acc, 56 224 255))' }} />
          <h2 style={{ margin: 0, fontSize: 18, fontWeight: 700, color: 'rgb(var(--text-primary, 230 234 240))' }}>
            Password Change Required
          </h2>
        </div>
        <p style={{ fontSize: 13, color: 'rgb(var(--text-muted, 130 136 148))', marginBottom: 20, lineHeight: 1.5 }}>
          Your account was created with a temporary password. Please set a new password to continue.
        </p>
        <form onSubmit={handleSubmit}>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            <input
              type="password" value={currentPw} onChange={e => setCurrentPw(e.target.value)}
              placeholder="Current (temporary) password" required
              style={{
                padding: '10px 14px', borderRadius: 10, fontSize: 14,
                background: 'rgb(255 255 255 / 0.04)', border: '1px solid rgb(var(--bg-border, 40 44 55) / 0.5)',
                color: 'rgb(var(--text-primary, 230 234 240))', outline: 'none',
              }}
            />
            <input
              type="password" value={newPw} onChange={e => setNewPw(e.target.value)}
              placeholder="New password" required minLength={10}
              style={{
                padding: '10px 14px', borderRadius: 10, fontSize: 14,
                background: 'rgb(255 255 255 / 0.04)', border: '1px solid rgb(var(--bg-border, 40 44 55) / 0.5)',
                color: 'rgb(var(--text-primary, 230 234 240))', outline: 'none',
              }}
            />
            <input
              type="password" value={confirmPw} onChange={e => setConfirmPw(e.target.value)}
              placeholder="Confirm new password" required minLength={10}
              style={{
                padding: '10px 14px', borderRadius: 10, fontSize: 14,
                background: 'rgb(255 255 255 / 0.04)', border: '1px solid rgb(var(--bg-border, 40 44 55) / 0.5)',
                color: 'rgb(var(--text-primary, 230 234 240))', outline: 'none',
              }}
            />
          </div>
          {error && (
            <div style={{
              display: 'flex', alignItems: 'center', gap: 6, marginTop: 12,
              padding: '8px 12px', borderRadius: 8, fontSize: 12,
              background: 'rgb(var(--cxv-brand, 255 82 125) / 0.12)',
              border: '1px solid rgb(var(--cxv-brand, 255 82 125) / 0.4)',
              color: 'rgb(var(--cxv-brand, 255 82 125))',
            }}>
              <AlertTriangle size={13} /> {error}
            </div>
          )}
          <button
            type="submit" disabled={busy}
            style={{
              display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8,
              width: '100%', marginTop: 16, padding: '12px 0', borderRadius: 10,
              border: 'none', cursor: busy ? 'wait' : 'pointer', fontWeight: 700, fontSize: 14,
              color: '#fff',
              background: 'linear-gradient(135deg, rgb(var(--cxv-acc, 56 224 255)), rgb(var(--cxv-acc2, 139 92 246)))',
              boxShadow: '0 8px 24px rgb(var(--cxv-acc, 56 224 255) / 0.3)',
            }}
          >
            {busy ? <Loader2 size={15} className="animate-spin" /> : <ShieldCheck size={15} />}
            Set New Password
          </button>
        </form>
      </div>
    </div>
  )
}

export default function App() {
  const { user, loading } = useAuth()
  const location = useLocation()
  const [bootDone, setBootDone] = useState(false)
  const [showDocs, setShowDocs] = useState(false)

  // Public tokenized board shares render without a CrypTX account (read-only).
  if (location.pathname.startsWith('/board-share/')) {
    return (
      <Suspense fallback={<PageLoader />}>
        <Routes>
          <Route path="/board-share/:token" element={<BoardSharedView />} />
        </Routes>
      </Suspense>
    )
  }

  // Public victim intake portal — no auth required.
  if (location.pathname.startsWith('/portal')) {
    return (
      <Suspense fallback={<PageLoader />}>
        <Routes>
          <Route path="/portal/report" element={<VictimPortal />} />
        </Routes>
      </Suspense>
    )
  }

  if (loading) {
    return (
      <div className="auth-loading">
        <img src="/cryptx-icon.svg" alt="CrypTX" />
        <span>Verifying secure session...</span>
      </div>
    )
  }
  // In-app User Guide — reachable from the boot splash ("Read CrypTX Docs")
  // before login. Rendered as a full-screen overlay; closing returns to the splash.
  if (!user && showDocs) {
    return (
      <Suspense fallback={<PageLoader />}>
        <DocsScreen onClose={() => setShowDocs(false)} />
      </Suspense>
    )
  }
  // Cinematic boot splash — plays every time an unauthenticated user visits.
  // The user must click "START CRYPTX" to proceed to the login screen.
  if (!user && !bootDone) return <BootScreen onComplete={() => setBootDone(true)} onOpenDocs={() => setShowDocs(true)} />
  if (!user) return <AuthScreen />

  // Force password change overlay — blocks all access until the user rotates
  // their temporary password (team members created by a team leader).
  if (user.must_change_password) return <ForcePasswordChange />

  // Bare Nexus Graph embed — rendered without Layout shell so it can be
  // loaded inside an iframe by the InvestigationGraphHost page.
  if (location.pathname.startsWith('/nexus-embed')) {
    return (
      <Suspense fallback={<PageLoader />}>
        <Routes>
          <Route path="/nexus-embed" element={<NexusGraph />} />
          <Route path="/nexus-embed/:addr" element={<NexusGraph />} />
        </Routes>
      </Suspense>
    )
  }

  return (
    <Layout>
      <Suspense fallback={<PageLoader />}>
      <Routes>
        <Route path="/" element={<Dashboard />} />
        {/* Address Intel */}
        <Route path="/intel" element={<AddressIntel />} />
        <Route path="/intel/:addr" element={<AddressIntel />} />
        {/* Legacy address routes */}
        <Route path="/address" element={<Navigate to="/intel" replace />} />
        <Route path="/address/:addr" element={<AddressIntelRedirect />} />
        {/* Fund Tracer */}
        <Route path="/trace" element={<FundTracer />} />
        <Route path="/trace/:addr" element={<FundTracer />} />
        {/* DEX */}
        <Route path="/dex" element={<DexAnalysis />} />
        <Route path="/dex/:addr" element={<DexAnalysis />} />
        {/* Local Forensics → embedded into Nexus Graph */}
        <Route path="/forensics" element={<Navigate to="/nexus" replace />} />
        <Route path="/forensics/:addr" element={<NexusRedirect />} />
        {/* AI Copilot → redirected to AI Agent */}
        <Route path="/ai" element={<Navigate to="/ai-agent" replace />} />
        {/* Threat Intelligence → merged into Nexus Graph */}
        <Route path="/threat-intel" element={<Navigate to="/nexus" replace />} />
        {/* Nexus Graph */}
        <Route path="/nexus" element={<NexusGraph />} />
        <Route path="/nexus/:addr" element={<NexusGraph />} />
        {/* Investigation Graph — iframe-hosted standalone screen */}
        <Route path="/investigation-graph" element={<InvestigationGraphHost />} />
        <Route path="/investigation-graph/:addr" element={<InvestigationGraphHost />} />
        {/* V2 F7: Multi-address entity investigation */}
        <Route path="/entity" element={<EntityInvestigation />} />
        {/* Intel Lab + Cross-Chain → merged into Nexus Graph */}
        <Route path="/intel-lab" element={<Navigate to="/nexus" replace />} />
        {/* Timeline → rolled back */}
        <Route path="/timeline" element={<Navigate to="/" replace />} />
        {/* Wallet Monitor */}
        <Route path="/monitor" element={<WalletMonitor />} />
        {/* NFT / TRON Sentinel */}
        <Route path="/nft-tron" element={<NFTTronSentinel />} />
        {/* Holistic Cross-Chain Trace */}
        {/* Consolidation: HolisticTrace merged into FundTracer (/trace).
            /holistic now redirects there since both used the same backend engine. */}
        <Route path="/holistic" element={<Navigate to="/trace" replace />} />
        <Route path="/holistic/:addr" element={<HolisticAddrRedirect />} />
        {/* Deterministic Attribution */}
        <Route path="/attribution" element={<AttributionLookup />} />
        <Route path="/attribution/:addr" element={<AttributionLookup />} />
        {/* Attribution submission workflow (label-growth loop) */}
        <Route path="/attribution-submissions" element={<AttributionSubmissions />} />
        {/* Investigation Boards (persistent canvases) */}
        <Route path="/boards" element={<Boards />} />
        <Route path="/boards/:id" element={<BoardCanvas />} />
        {/* OSINT Sweep */}
        <Route path="/osint" element={<OsintSweepPage />} />
        <Route path="/osint/:addr" element={<OsintSweepPage />} />
        {/* One-click Auto-Investigation */}
        <Route path="/auto" element={<AutoInvestigate />} />
        <Route path="/auto/:addr" element={<AutoInvestigate />} />
        {/* Compliance: Sanctions / Regulatory / Demixing */}
        <Route path="/sanctions" element={<SanctionsScreener />} />
        <Route path="/regulatory" element={<RegulatoryReports />} />
        <Route path="/demix" element={<DemixLab />} />
        {/* 2026 enhancement domains */}
        <Route path="/contract-forensics" element={<ContractForensics />} />
        <Route path="/laundering" element={<LaunderingTrace />} />
        <Route path="/court-readiness" element={<CourtReadiness />} />
        <Route path="/recovery" element={<RecoveryOps />} />
        {/* Next-Horizon 2026-07 domains */}
        <Route path="/comply" element={<ComplianceSuite />} />
        <Route path="/freeze-desk" element={<FreezeDesk />} />
        <Route path="/scam-atlas" element={<ScamNetworkAtlas />} />
        <Route path="/perp-dex" element={<PerpDexIntel />} />
        <Route path="/perp-dex/:addr" element={<PerpDexIntel />} />
        {/* Predictive Intelligence (pre-crime engine) */}
      <Route path="/predictive" element={<PredictiveIntel />} />
      <Route path="/predictive/:addr" element={<PredictiveIntel />} />

      {/* Phase 1 commercial-launch pages */}
      <Route path="/nl-agent" element={<NlAgentPage />} />
      <Route path="/entity-search" element={<EntitySearchPage />} />
      <Route path="/rules" element={<RuleBuilder />} />
        {/* Evidence Vault */}
        <Route path="/evidence" element={<EvidenceVault />} />
        <Route path="/evidence/:id" element={<EvidenceVault />} />
        <Route path="/crosschain" element={<Navigate to="/nexus" replace />} />
        {/* AI Investigation Agent */}
        <Route path="/ai-agent" element={<AiAgentPage />} />
        {/* Report Studio (mega report generator) */}
        <Route path="/reports" element={<ReportStudio />} />
        {/* Blockchain Threat Landscape (RSS threat feeds) */}
        <Route path="/threat-landscape" element={<BlockchainThreatLandscape />} />
        <Route path="/threat-landscape/:id" element={<BlockchainThreatLandscape />} />
        {/* Victim Reports & Scam Intelligence */}
        <Route path="/victim-reports" element={<VictimReportPage />} />
        {/* TX Lens */}
        <Route path="/tx-lens" element={<TxLens />} />
        <Route path="/tx-lens/:chain/:hash" element={<TxLens />} />
        {/* Batch Screening */}
        <Route path="/batch" element={<BatchScreener />} />
        {/* Local Labels */}
        <Route path="/labels" element={<LabelIntel />} />
        {/* Case Management */}
        <Route path="/cases" element={<CaseManager />} />
        <Route path="/cases/:id" element={<CaseDetail />} />
        <Route path="/cases/:id/tasks" element={<CaseTaskManagement />} />
        <Route path="/cases/:id/audit" element={<CaseAudit />} />
        {/* Transaction Detail — merged into TX Lens (consolidation: /tx → /tx-lens) */}
        <Route path="/tx/:chain/:hash" element={<Navigate to={`/tx-lens`} replace />} />
        {/* Settings */}
        <Route path="/settings" element={<Settings />} />
        <Route path="/profile" element={<UserProfile />} />
        <Route path="/team" element={<TeamManagement />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
      </Suspense>
      <MobileNav />
    </Layout>
  )
}
