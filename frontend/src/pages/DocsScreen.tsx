import { useEffect, useMemo, useRef, useState } from 'react'
import type { LucideIcon } from 'lucide-react'
import {
  Activity, Archive, ArrowRight, BarChart3, BellRing, BookOpen, Bot, BrainCircuit,
  BriefcaseBusiness, Bug, CandlestickChart, Check, ChevronDown, CircleHelp, ClipboardCheck,
  Copy, Cpu, Database, Droplets, ExternalLink, FileCode2, FileDown, FilePlus2, FileSearch,
  FileText, Fingerprint, FolderKanban, FolderOpen, Gavel, Gem, GitMerge, Globe2, Hash,
  KeyRound, Landmark, Layers, LayoutDashboard, Lightbulb, ListChecks, LockKeyhole, Network,
  Newspaper, PanelTop, Power, Radar, Radio, Route, Scale, Search, Settings, Shield,
  ShieldAlert, ShieldCheck, Snowflake, Sparkles, Target, Users, Waypoints, X, Zap,
} from 'lucide-react'
import { SUPPORTED_CHAINS, SUPPORTED_TOKENS, TOTAL_CHAINS } from '../lib/coverage'
import '../styles/docs-screen.css'

type Suite = 'Core' | 'Investigation' | 'Intelligence' | 'Compliance' | 'Advanced' | 'Workspace'

type ScreenDoc = {
  name: string
  route: string
  suite: Suite
  icon: LucideIcon
  summary: string
  features: string[]
  use: string[]
  roles?: string
  status?: 'Primary' | 'Supporting' | 'Public'
  keywords?: string[]
}

const SCREENS: ScreenDoc[] = [
  {
    name: 'Dashboard', route: '/', suite: 'Core', icon: Activity, status: 'Primary',
    summary: 'Mission control for search, recent work, coverage, system health, and fast module launch.',
    features: ['Global address, hash, ENS, and case search', 'Recent investigations and platform metrics', 'Chain and token coverage matrix'],
    use: ['Paste a subject into global search', 'Open a recent investigation or module', 'Confirm data services are online'],
    keywords: ['home', 'launchpad', 'coverage'],
  },
  {
    name: 'Investigation Boards', route: '/boards', suite: 'Core', icon: LayoutDashboard, status: 'Primary',
    summary: 'Persistent crime-wall canvases for wallets, entities, evidence, zones, and analyst-defined links.',
    features: ['Typed pins, red-string relationships, zones, and notes', 'Force, timeline, and grid layouts with undo/redo', 'Read-only sharing, snapshots, minimap, and PNG export'],
    use: ['Create or open a board', 'Add and arrange pins, then connect relationships', 'Snapshot, share, or export the finished board'],
    keywords: ['canvas', 'link analysis', 'crimewall', 'collaboration'],
  },
  {
    name: 'Board Canvas', route: '/boards/:id', suite: 'Workspace', icon: Network, status: 'Supporting',
    summary: 'The working crime-wall for a single investigation board, including pins, links, zones, layouts, and sharing.',
    features: ['Wallet, person, organization, exchange, evidence, event, and custom pins', 'Relationship labels, confidence, lead status, priority, zones, and one-hop expansion', 'Auto-layout, minimap, undo/redo, snapshot, sharing, and PNG export'],
    use: ['Open a board or create one from the board register', 'Build and annotate the relationship map', 'Snapshot the state before sharing or exporting'],
    keywords: ['board detail', 'red string', 'canvas', 'snapshot'],
  },
  {
    name: 'Nexus Graph', route: '/nexus', suite: 'Core', icon: Network, status: 'Primary',
    summary: 'Interactive entity and transaction graph for growing, filtering, and explaining a network.',
    features: ['Force-directed, radial, and community layouts', 'Node expansion, shortest-path analysis, tagging, and focus mode', 'Flow animation, minimap, PNG export, and JSON round-trip'],
    use: ['Seed the graph with an address', 'Expand counterparties and isolate paths', 'Tag findings and export an exhibit'],
    keywords: ['graph', 'd3', 'pathfinding', 'network'],
  },
  {
    name: 'Fund Tracer', route: '/trace', suite: 'Core', icon: Waypoints, status: 'Primary',
    summary: 'Multi-hop tracing across chains with deterministic laundering and cash-out signals.',
    features: ['Linear or wide traversal across one to five hops', 'Mixer, bridge, peel-chain, fan-in, fan-out, and scam alerts', 'Cross-chain continuation and counterparty pivots'],
    use: ['Enter a source and choose depth', 'Review the path and typology alerts', 'Pivot a counterparty into Nexus, Intel, or a case'],
    keywords: ['BFS', 'flow', 'cashout', 'cross-chain'],
  },
  {
    name: 'Address Intel', route: '/intel', suite: 'Core', icon: Shield, status: 'Primary',
    summary: 'A consolidated wallet dossier combining balances, behavior, attribution, exposure, and risk.',
    features: ['Balances, holdings, transactions, and counterparty context', 'Sanctions, scam, mixer, bridge, and public-source enrichment', 'Composite risk score with explainable signals and provenance'],
    use: ['Enter an address or resolved name', 'Review overview, exposure, holdings, and activity', 'Add the subject to a case, board, or trace'],
    keywords: ['wallet', 'dossier', 'risk', 'enrichment'],
  },
  {
    name: 'NFT / TON Sentinel', route: '/nft-tron', suite: 'Core', icon: Gem, status: 'Primary',
    summary: 'Specialized wallet profiling for NFTs and TON/TRON activity.',
    features: ['EVM, TON, and TRON context detection', 'NFT holdings and collection-risk inspection', 'Wash-trade and specialized counterparty signals'],
    use: ['Enter a wallet and select or auto-detect the network', 'Review collection and profile panels', 'Escalate material findings into the case record'],
    keywords: ['NFT', 'TON', 'TRON', 'wash trading'],
  },
  {
    name: 'Auto-Investigate', route: '/auto', suite: 'Investigation', icon: Sparkles, status: 'Primary',
    summary: 'One-click orchestration of tracing, screening, enrichment, and report assembly.',
    features: ['Background investigation jobs with visible progress', 'Consolidated findings and recommended next actions', 'Downloadable result package'],
    use: ['Submit a subject address', 'Monitor the investigation stages', 'Review and export the completed findings'],
    keywords: ['automation', 'one click', 'job'],
  },
  {
    name: 'Entity Investigation', route: '/entity', suite: 'Investigation', icon: Users, status: 'Primary',
    summary: 'Treats multiple addresses as one subject and analyzes aggregate behavior and counterparties.',
    features: ['Paste or upload multi-address subjects', 'Cluster-level inbound, outbound, and internal-flow analysis', 'External counterparty and entity-level risk context'],
    use: ['Provide addresses and chain context', 'Run the entity analysis', 'Save or pivot the resulting cluster'],
    keywords: ['cluster', 'multi-address', 'aggregate'],
  },
  {
    name: 'TX Lens', route: '/tx-lens', suite: 'Investigation', icon: Hash, status: 'Primary',
    summary: 'Transaction microscope that decodes a hash into actors, assets, contracts, and plain-language meaning.',
    features: ['Cross-chain transaction lookup and interpretation', 'Token transfers and contract-interaction breakdown', 'Deep-analysis jobs and evidence filing'],
    use: ['Choose a chain and enter a transaction hash', 'Read the interpretation and inspect flows', 'Save the transaction as evidence'],
    keywords: ['transaction', 'decode', 'interpreter'],
  },
  {
    name: 'DEX Analysis', route: '/dex', suite: 'Investigation', icon: BarChart3, status: 'Primary',
    summary: 'Spot-DEX trading forensics across major Uniswap and PancakeSwap activity.',
    features: ['Swap history and trade direction', 'Buy/sell ratios and volume visualizations', 'Wash-trade pattern detection'],
    use: ['Enter a trader address', 'Inspect swaps and behavior charts', 'Pivot suspicious tokens or counterparties'],
    keywords: ['swap', 'Uniswap', 'PancakeSwap', 'wash trade'],
  },
  {
    name: 'Perpetual DEX Intel', route: '/perp-dex', suite: 'Investigation', icon: CandlestickChart, status: 'Primary',
    summary: 'Derivative-position and trader-risk intelligence for perpetual decentralized exchanges.',
    features: ['Perpetual trader profile and position context', 'Liquidation, leverage, and concentration signals', 'Address-centric analysis with reusable route state'],
    use: ['Enter a trader address', 'Review positions and risk indicators', 'Cross-reference the wallet in Address Intel'],
    keywords: ['perps', 'leverage', 'liquidation', 'Hyperliquid'],
  },
  {
    name: 'Wallet Monitor', route: '/monitor', suite: 'Investigation', icon: BellRing, status: 'Primary',
    summary: 'Continuous address watchlists with rules, activity events, notifications, and delivery channels.',
    features: ['Create and manage monitored addresses', 'Threshold and behavior-based alert rules', 'In-app notifications and external delivery configuration'],
    use: ['Add one or more addresses', 'Configure trigger rules and destinations', 'Triage events from the notification stream'],
    keywords: ['watchlist', 'alerts', 'webhook', 'monitoring'],
  },
  {
    name: 'Evidence Vault', route: '/evidence', suite: 'Investigation', icon: Archive, status: 'Primary',
    summary: 'Tamper-evident storage for findings, artifacts, snapshots, and their custody history.',
    features: ['Case-linked evidence items and annotations', 'SHA-256 integrity and custody verification', 'Audit-ready evidence summaries and exports'],
    use: ['Add an artifact from any investigation screen', 'Annotate and associate it with a case', 'Verify custody before reporting'],
    keywords: ['custody', 'hash', 'artifact', 'audit'],
  },
  {
    name: 'Predictive Intelligence', route: '/predictive', suite: 'Intelligence', icon: BrainCircuit, status: 'Primary',
    summary: 'Model-assisted behavioral forecasting with history, training status, and explicit risk outputs.',
    features: ['Run the full prediction suite for a target address', 'Model status and controlled training workflow', 'Prediction history and signal-specific explanations'],
    use: ['Submit a subject address', 'Run available predictive models', 'Compare outputs with deterministic evidence before escalation'],
    keywords: ['prediction', 'model', 'training', 'forecast'],
  },
  {
    name: 'AI Investigation Agent', route: '/ai-agent', suite: 'Intelligence', icon: Cpu, status: 'Primary',
    summary: 'Evidence-aware copilot for tracing questions, missing-evidence review, and investigation narratives.',
    features: ['Preset forensic tasks and free-form case chat', 'Cash-out, cluster, subpoena, and evidence-gap analysis', 'Copyable and downloadable narratives'],
    use: ['Choose a preset or ask a focused question', 'Attach an address or case context', 'Validate cited evidence before using the response'],
    keywords: ['AI', 'copilot', 'subpoena', 'narrative'],
  },
  {
    name: 'Natural-Language Agent', route: '/nl-agent', suite: 'Intelligence', icon: Bot, status: 'Supporting',
    summary: 'Runs multi-tool investigation instructions written as a single plain-language prompt.',
    features: ['Discovers available investigation tools', 'Plans and executes a multi-step request', 'Returns structured tool results and a final response'],
    use: ['Describe the outcome and subject precisely', 'Run the instruction and follow tool progress', 'Review every generated conclusion against source results'],
    keywords: ['agent', 'prompt', 'tool orchestration'],
  },
  {
    name: 'OSINT Sweep', route: '/osint', suite: 'Intelligence', icon: Radar, status: 'Primary',
    summary: 'Searches public sources for wallet mentions and turns relevant hits into evidence.',
    features: ['Reddit, GitHub, dark-web index, Pastebin, and forum connectors', 'Source filters, caching, and provenance links', 'One-click filing to boards or evidence'],
    use: ['Enter an address', 'Filter and assess source hits', 'File only relevant, attributable results'],
    keywords: ['open source', 'dark web', 'social', 'mentions'],
  },
  {
    name: 'Entity Search', route: '/entity-search', suite: 'Intelligence', icon: FileSearch, status: 'Supporting',
    summary: 'Finds known services, actors, and VASPs across attribution and local-label data.',
    features: ['Name-based entity search', 'Known-address and label consolidation', 'VASP dossier retrieval'],
    use: ['Search an entity name', 'Review matching entities and addresses', 'Open the VASP dossier or pivot to wallet analysis'],
    keywords: ['VASP', 'dossier', 'entity lookup'],
  },
  {
    name: 'Cases', route: '/cases', suite: 'Intelligence', icon: FolderOpen, status: 'Primary',
    summary: 'The organizing layer for subjects, analysts, notes, evidence, tasks, boards, and reports.',
    features: ['Case creation, membership, subjects, notes, and status', 'Linked evidence, boards, reports, and risk context', 'Task workspace and immutable activity audit'],
    use: ['Create a case and define the subject', 'Add members and investigation material', 'Manage work through detail, task, and audit views'],
    keywords: ['case management', 'collaboration', 'notes'],
  },
  {
    name: 'Case Workspace', route: '/cases/:id', suite: 'Workspace', icon: BriefcaseBusiness, status: 'Supporting',
    summary: 'Detailed case view for people, addresses, notes, evidence, boards, and report actions.',
    features: ['Member and role management', 'Case addresses, notes, QA, and linked artifacts', 'Direct navigation to tasks, audit, and reporting'],
    use: ['Open a case from the register', 'Build the subject record and team context', 'Move into tasks, audit, or report generation'],
    keywords: ['case detail', 'members', 'case QA'],
  },
  {
    name: 'Case Tasks', route: '/cases/:id/tasks', suite: 'Workspace', icon: ListChecks, status: 'Supporting',
    summary: 'Collaborative assignment board with messages, deliverables, review, priority, and due dates.',
    features: ['Create, assign, filter, and update tasks', 'Threaded task messages', 'Deliverable submission and reviewer approval or rejection'],
    use: ['Create a scoped task and assign an analyst', 'Discuss and submit deliverables in the task panel', 'Review the deliverable and close the work'],
    keywords: ['assignment', 'deliverable', 'review', 'team'],
  },
  {
    name: 'Case Audit', route: '/cases/:id/audit', suite: 'Workspace', icon: ClipboardCheck, status: 'Supporting',
    summary: 'Searchable activity history for case, member, address, note, task, message, and deliverable events.',
    features: ['Action, date, and text filtering', 'Actor, target, timestamp, and detail context', 'Refreshable chronological audit trail'],
    use: ['Open Audit from a case', 'Filter to the event or period in question', 'Use entries to support governance and review'],
    keywords: ['activity log', 'history', 'governance'],
  },
  {
    name: 'Batch Screen', route: '/batch', suite: 'Intelligence', icon: Layers, status: 'Primary',
    summary: 'Bulk address triage with standardized risk verdicts and downloadable results.',
    features: ['Paste or upload address lists', 'Sanctioned through clean risk grading', 'Sortable and exportable screening results'],
    use: ['Provide the address set', 'Run screening and sort by severity', 'Export results and investigate high-risk subjects'],
    keywords: ['bulk', 'triage', 'CSV'],
  },
  {
    name: 'Labels', route: '/labels', suite: 'Intelligence', icon: Database, status: 'Primary',
    summary: 'Private analyst labels that add organization-specific context across the platform.',
    features: ['Create, search, and manage local address labels', 'Bulk label import', 'Automatic reuse in attribution and risk views'],
    use: ['Search before creating a duplicate', 'Add a label with useful context', 'Import governed label sets when needed'],
    keywords: ['annotation', 'taxonomy', 'import'],
  },
  {
    name: 'Victim Reports', route: '/victim-reports', suite: 'Intelligence', icon: CircleHelp, status: 'Primary',
    summary: 'Operational review of incoming crypto-fraud reports and their scam-address intelligence.',
    features: ['Report intake queue and scam-type summaries', 'Address clustering and related-report context', 'Label confirmation and export'],
    use: ['Review incoming submissions', 'Corroborate addresses and clustered reports', 'Promote supported findings into labels or cases'],
    keywords: ['fraud', 'complaint', 'victim', 'scam'],
  },
  {
    name: 'Scam Network Atlas', route: '/scam-atlas', suite: 'Intelligence', icon: Bug, status: 'Primary',
    summary: 'Network-level view of scam infrastructure, campaigns, victims, and linked identifiers.',
    features: ['Scam infrastructure and relationship mapping', 'Campaign and cluster exploration', 'Investigation pivots from connected scam artifacts'],
    use: ['Search or select a scam subject', 'Explore connected infrastructure and clusters', 'Pivot confirmed leads into a case or graph'],
    keywords: ['campaign', 'infrastructure', 'scam cluster'],
  },
  {
    name: 'Threat Landscape', route: '/threat-landscape', suite: 'Intelligence', icon: Newspaper, status: 'Supporting',
    summary: 'Live blockchain-security news and threat-feed reader with source health and article detail.',
    features: ['Multi-feed synchronization and health state', 'Search and source filtering', 'Article detail with original-source links'],
    use: ['Refresh feeds when needed', 'Filter by source or search headlines', 'Open relevant intelligence at the publisher'],
    keywords: ['RSS', 'news', 'feeds', 'threat intel'],
  },
  {
    name: 'Report Studio', route: '/reports', suite: 'Intelligence', icon: FileText, status: 'Primary',
    summary: 'Generates audience-specific, branded investigation reports from case material.',
    features: ['Executive, technical, legal, and investigative report modes', 'AI-assisted narrative with deterministic fallback', 'Preview, print, PDF, and DOCX-oriented export'],
    use: ['Choose a case and audience', 'Generate and verify the narrative', 'Preview, print, or download the report'],
    keywords: ['report', 'export', 'PDF', 'DOCX'],
  },
  {
    name: 'Sanctions Screener', route: '/sanctions', suite: 'Compliance', icon: ShieldAlert, status: 'Primary',
    summary: 'Single, bulk, and entity sanctions screening with dataset status and refresh controls.',
    features: ['Address and bulk sanctions checks', 'Sanctioned-entity search', 'Local and configured provider data status'],
    use: ['Choose address, batch, or entity mode', 'Run the screen and inspect matching evidence', 'Record the result in the case or filing'],
    keywords: ['OFAC', 'screening', 'watchlist'],
  },
  {
    name: 'Attribution', route: '/attribution', suite: 'Compliance', icon: Fingerprint, status: 'Primary',
    summary: 'Deterministic and analyst attribution with confidence, evidence, and provenance.',
    features: ['Address-to-entity and category resolution', 'Confidence class and contributing sources', 'Auditable source report'],
    use: ['Look up an address with chain context', 'Review confidence and evidence', 'Use the source report when citing attribution'],
    keywords: ['provenance', 'identity', 'entity'],
  },
  {
    name: 'Attribution Submissions', route: '/attribution-submissions', suite: 'Compliance', icon: FilePlus2, status: 'Primary',
    summary: 'Governed label-growth workflow for analyst submissions and reviewer decisions.',
    features: ['Evidence-backed attribution proposals', 'Reviewer approval and rejection queue', 'End-to-end submission audit'],
    use: ['Submit an entity link and evidence', 'Reviewers assess the proposal', 'Approved attribution becomes available platform-wide'],
    keywords: ['review', 'approval', 'label growth'],
  },
  {
    name: 'Regulatory Reports', route: '/regulatory', suite: 'Compliance', icon: Scale, status: 'Primary',
    summary: 'Guided creation of regulator-facing filings and VASP due-diligence dossiers.',
    features: ['SAR, CTR, and Travel Rule report generation', 'Standard suspicious-activity categories', 'Know-Your-VASP dossiers and downloadable output'],
    use: ['Choose a filing type', 'Complete the structured facts and narrative', 'Generate, review, and attach the filing'],
    keywords: ['SAR', 'CTR', 'Travel Rule', 'KYV'],
  },
  {
    name: 'AML Demixing', route: '/demix', suite: 'Compliance', icon: GitMerge, status: 'Primary',
    summary: 'Reconnects candidate flows through mixers, bridges, and chain swaps with explicit confidence.',
    features: ['Mixer and Tornado Cash analysis', 'Bridge and chain-swap correlation', 'Ranked candidate matches with confidence'],
    use: ['Select a demixing mode and target', 'Review timing, amount, and relationship evidence', 'Promote only defensible matches into the trace'],
    keywords: ['mixer', 'Tornado', 'bridge', 'correlation'],
  },
  {
    name: 'Compliance Suite', route: '/comply', suite: 'Compliance', icon: Landmark, status: 'Primary',
    summary: 'Program-level stablecoin and transaction compliance for issuers, fintechs, and banks.',
    features: ['Monitored address-book programs', 'Deterministic KYT screening and Travel Rule evaluation', 'Examiner-ready reports with audit history'],
    use: ['Create a program and define thresholds', 'Add monitored addresses and evaluate activity', 'Generate the program report and audit package'],
    keywords: ['KYT', 'stablecoin', 'GENIUS Act', 'program'],
  },
  {
    name: 'Rule Builder', route: '/rules', suite: 'Compliance', icon: PanelTop, status: 'Supporting',
    summary: 'Builds reusable composite risk rules from governed templates and tests them before activation.',
    features: ['Rule templates and composite rule registry', 'Enable, disable, and delete lifecycle controls', 'Dry-run testing against sample facts'],
    use: ['Start from the closest template', 'Review conditions and activate the rule', 'Dry-run before relying on alerts'],
    keywords: ['policy', 'dry run', 'template', 'rules'],
  },
  {
    name: 'Smart-Contract Forensics', route: '/contract-forensics', suite: 'Advanced', icon: FileCode2, status: 'Primary',
    summary: 'Evidence-first smart-contract analysis for malicious patterns, approvals, similarity, and incidents.',
    features: ['Bytecode/source risk scan and function-selector recovery', 'Wallet approval exposure with malicious-spender checks', 'Bytecode similarity and incident reconstruction'],
    use: ['Choose scan, approvals, similarity, or incident mode', 'Provide the available addresses, bytecode, or event data', 'Treat results as leads and preserve source material'],
    keywords: ['bytecode', 'approval', 'exploit', 'similarity'],
  },
  {
    name: 'Modern Laundering Trace', route: '/laundering', suite: 'Advanced', icon: Droplets, status: 'Primary',
    summary: 'Specialist tracing for address poisoning, instant swaps, peel chains, and micro-fragmentation.',
    features: ['Look-alike address-poisoning detection', 'No-KYC swap continuation analysis', 'Modern laundering typology evaluation'],
    use: ['Choose the matching typology tab', 'Enter the subject and available transaction context', 'Review the explicit confidence and evidence trail'],
    keywords: ['poisoning', 'peel chain', 'fragmentation', 'instant swap'],
  },
  {
    name: 'Court Readiness', route: '/court-readiness', suite: 'Advanced', icon: Gavel, status: 'Primary',
    summary: 'Turns forensic methods and exhibits into defensible, tamper-evident court material.',
    features: ['Daubert-style methodology appendix', 'Heuristic and limitation disclosure', 'Timestamped, tamper-evident exhibit notarization'],
    use: ['Enter case, analyst, and subject context', 'Generate and verify the methodology appendix', 'Notarize each final exhibit and retain its receipt'],
    keywords: ['Daubert', 'court', 'notarize', 'TSA'],
  },
  {
    name: 'Recovery - Freeze & Seizure', route: '/recovery', suite: 'Advanced', icon: Snowflake, status: 'Primary',
    summary: 'Routes traced assets to the organization able to freeze them and manages the request lifecycle.',
    features: ['Issuer or VASP recovery routing', 'Freeze-request preview and package generation', 'Status tracking and recovery summaries'],
    use: ['Enter address, chain, asset, amount, and basis', 'Preview the recipient and request package', 'Create the request and update it through resolution'],
    keywords: ['freeze', 'seizure', 'issuer', 'VASP'],
  },
  {
    name: 'Freeze Desk', route: '/freeze-desk', suite: 'Advanced', icon: Radio, status: 'Primary',
    summary: 'Operational watch desk that detects VASP or mixer contact and drafts a freeze request.',
    features: ['Active and paused illicit-address watches', 'Manual evaluation and scan workflows', 'Intake directory, event log, and freeze KPIs'],
    use: ['Add a watch with case and threshold context', 'Evaluate or scan for actionable contact', 'Review the drafted request in Recovery'],
    keywords: ['beacon', 'watch', 'freeze request', 'KPI'],
  },
  {
    name: 'Settings', route: '/settings', suite: 'Workspace', icon: Settings, status: 'Supporting',
    summary: 'Data-provider keys, AI-provider selection, investigation defaults, theme, and density.',
    features: ['Chain, attribution, OSINT, and AI connector configuration', 'Multiple first-party and OpenAI-compatible AI providers', 'Default trace mode, theme, and table density'],
    use: ['Open the relevant provider group', 'Enter the key, model, or base URL and save', 'Confirm the provider status before using dependent modules'],
    roles: 'Administrator', keywords: ['API keys', 'AI provider', 'preferences'],
  },
  {
    name: 'Investigator Profile', route: '/profile', suite: 'Workspace', icon: Fingerprint, status: 'Supporting',
    summary: 'Identity, report signature, visual preferences, password, sessions, and two-factor security.',
    features: ['Investigator name, title, signature, and accent', 'Password rotation and two-factor authentication', 'Session and team-role information'],
    use: ['Complete your report identity', 'Enable 2FA and protect recovery codes', 'Review security and display preferences'],
    keywords: ['2FA', 'password', 'signature', 'account'],
  },
  {
    name: 'Team Management', route: '/team', suite: 'Workspace', icon: Users, status: 'Supporting',
    summary: 'Team-leader controls for members, roles, temporary credentials, and account recovery.',
    features: ['Rename the team and create member accounts', 'Assign roles and remove members', 'Disable a member 2FA during controlled recovery'],
    use: ['Create the analyst with the correct role', 'Deliver temporary credentials securely', 'Review membership and remove stale access'],
    roles: 'Team leader / administrator', keywords: ['RBAC', 'members', 'access'],
  },
  {
    name: 'Secure Sign In', route: 'startup', suite: 'Workspace', icon: LockKeyhole, status: 'Supporting',
    summary: 'Boot, registration, authentication, session verification, and forced temporary-password rotation.',
    features: ['Cinematic system boot and authentication gate', 'Registration and secure session handling', 'Mandatory password change for provisioned users'],
    use: ['Start CrypTX from the boot screen', 'Sign in or register as permitted', 'Complete any required password rotation'],
    keywords: ['login', 'authentication', 'session'],
  },
  {
    name: 'Public Victim Intake', route: '/portal/report', suite: 'Workspace', icon: CircleHelp, status: 'Public',
    summary: 'Unauthenticated fraud-report form for victims to submit addresses, losses, narrative, and contact context.',
    features: ['Scam type, transaction, asset, and loss capture', 'Victim wallet, narrative, country, and contact context', 'Submission receipt without a CrypTX account'],
    use: ['Share the portal with the reporting victim', 'Submit complete and factual incident details', 'Triage the new record in Victim Reports'],
    roles: 'Public reporter', keywords: ['public', 'intake', 'fraud report'],
  },
  {
    name: 'Shared Board View', route: '/board-share/:token', suite: 'Workspace', icon: Globe2, status: 'Public',
    summary: 'Tokenized, read-only investigation-board view for controlled external sharing.',
    features: ['No CrypTX account required', 'Optional password protection', 'Read-only canvas and board context'],
    use: ['Generate the share link from a board', 'Apply a password when sensitivity requires it', 'Revoke or rotate sharing when the review ends'],
    roles: 'External reviewer', keywords: ['share link', 'read only', 'token'],
  },
]

const SUITES: Array<{ key: Suite; icon: LucideIcon; note: string }> = [
  { key: 'Core', icon: Route, note: 'Start, map, trace, and profile.' },
  { key: 'Investigation', icon: Search, note: 'Deep analysis and evidence capture.' },
  { key: 'Intelligence', icon: BrainCircuit, note: 'Enrichment, cases, AI, and reporting.' },
  { key: 'Compliance', icon: ShieldCheck, note: 'Screening, attribution, programs, and filings.' },
  { key: 'Advanced', icon: Gavel, note: 'Contracts, laundering, court, and recovery.' },
  { key: 'Workspace', icon: FolderKanban, note: 'Access, collaboration, settings, and public views.' },
]

const SECTIONS = [
  { id: 'welcome', label: 'Welcome', group: 'Start here', icon: BookOpen },
  { id: 'quickstart', label: 'Quick start', group: 'Start here', icon: Zap },
  { id: 'workspace', label: 'Workspace tour', group: 'Start here', icon: LayoutDashboard },
  { id: 'workflows', label: 'Guided workflows', group: 'Operate', icon: Route },
  { id: 'screens', label: 'Screen directory', group: 'Operate', icon: PanelTop },
  { id: 'chains', label: 'Coverage', group: 'Reference', icon: Globe2 },
  { id: 'evidence', label: 'Evidence standard', group: 'Reference', icon: Archive },
  { id: 'security', label: 'Security & access', group: 'Reference', icon: LockKeyhole },
  { id: 'shortcuts', label: 'Shortcuts', group: 'Reference', icon: KeyRound },
] as const

const WORKFLOWS = [
  {
    id: 'stolen', label: 'Stolen funds', icon: Waypoints,
    outcome: 'Trace theft proceeds to an attributable service and preserve a recovery-ready package.',
    steps: [
      ['Open the subject', 'Use Address Intel to establish the victim wallet, first outbound transfers, and risk context.'],
      ['Trace and explain', 'Run Fund Tracer, then use Nexus Graph and TX Lens to verify the important hops.'],
      ['Resolve obfuscation', 'Use AML Demixing or Modern Laundering Trace where a mixer, bridge, swap, or poisoning pattern appears.'],
      ['Attribute cash-out', 'Use Entity Search, Attribution, Sanctions, and OSINT Sweep to identify the destination.'],
      ['Freeze and report', 'Seal artifacts in Evidence, route the request through Recovery or Freeze Desk, then generate the case report.'],
    ],
  },
  {
    id: 'compliance', label: 'Compliance review', icon: ShieldCheck,
    outcome: 'Screen a population, investigate exceptions, and produce an examiner-ready record.',
    steps: [
      ['Define policy', 'Configure a Compliance Suite program or create a governed composite rule.'],
      ['Screen subjects', 'Use Batch Screen, Sanctions, and program-level KYT to prioritize exceptions.'],
      ['Investigate hits', 'Open risky addresses in Address Intel, Attribution, and Fund Tracer.'],
      ['Document decisions', 'Save supporting material in Evidence and record case notes and tasks.'],
      ['File or report', 'Generate SAR, CTR, Travel Rule, KYV, or program reports as required.'],
    ],
  },
  {
    id: 'scam', label: 'Scam campaign', icon: Bug,
    outcome: 'Turn public complaints into a clustered infrastructure and attribution case.',
    steps: [
      ['Collect reports', 'Use Public Victim Intake and triage submissions in Victim Reports.'],
      ['Cluster indicators', 'Explore Scam Network Atlas and create a visual Investigation Board.'],
      ['Enrich identities', 'Run OSINT Sweep, Labels, Entity Search, and Attribution on connected artifacts.'],
      ['Coordinate the case', 'Assign Case Tasks, review deliverables, and maintain the Case Audit trail.'],
      ['Publish findings', 'Seal evidence and create an audience-specific report in Report Studio.'],
    ],
  },
]

function copyText(value: string, setCopied: (value: string) => void) {
  if (!navigator.clipboard) return
  void navigator.clipboard.writeText(value).then(() => {
    setCopied(value)
    window.setTimeout(() => setCopied(''), 1400)
  })
}

export default function DocsScreen({ onClose }: { onClose: () => void }) {
  const [query, setQuery] = useState('')
  const [suite, setSuite] = useState<Suite | 'All'>('All')
  const [openScreen, setOpenScreen] = useState<string | null>('Dashboard')
  const [activeSection, setActiveSection] = useState('welcome')
  const [workflow, setWorkflow] = useState('stolen')
  const [chainFamily, setChainFamily] = useState('All')
  const [progress, setProgress] = useState(0)
  const [copied, setCopied] = useState('')
  const [leaving, setLeaving] = useState(false)
  const rootRef = useRef<HTMLDivElement>(null)
  const searchRef = useRef<HTMLInputElement>(null)

  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase()
    return SCREENS.filter(screen => {
      if (suite !== 'All' && screen.suite !== suite) return false
      if (!needle) return true
      return [screen.name, screen.route, screen.suite, screen.summary, screen.roles, ...(screen.keywords || []), ...screen.features, ...screen.use]
        .filter(Boolean).join(' ').toLowerCase().includes(needle)
    })
  }, [query, suite])

  const families = useMemo(() => ['All', ...Array.from(new Set(SUPPORTED_CHAINS.map(chain => chain.family)))], [])
  const visibleChains = chainFamily === 'All' ? SUPPORTED_CHAINS : SUPPORTED_CHAINS.filter(chain => chain.family === chainFamily)
  const activeWorkflow = WORKFLOWS.find(item => item.id === workflow) || WORKFLOWS[0]

  function close() {
    setLeaving(true)
    window.setTimeout(onClose, 240)
  }

  function jumpTo(id: string) {
    document.getElementById(`docs-${id}`)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }

  useEffect(() => {
    const root = rootRef.current
    if (!root) return
    const onScroll = () => {
      const max = root.scrollHeight - root.clientHeight
      setProgress(max > 0 ? Math.min(100, (root.scrollTop / max) * 100) : 0)
    }
    root.addEventListener('scroll', onScroll, { passive: true })
    return () => root.removeEventListener('scroll', onScroll)
  }, [])

  useEffect(() => {
    const observer = new IntersectionObserver(entries => {
      const visible = entries.filter(entry => entry.isIntersecting).sort((a, b) => b.intersectionRatio - a.intersectionRatio)
      if (visible[0]) setActiveSection(visible[0].target.id.replace('docs-', ''))
    }, { root: rootRef.current, rootMargin: '-18% 0px -65% 0px', threshold: [0, 0.15, 0.5] })
    SECTIONS.forEach(section => {
      const node = document.getElementById(`docs-${section.id}`)
      if (node) observer.observe(node)
    })
    return () => observer.disconnect()
  }, [])

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') close()
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault()
        searchRef.current?.focus()
      }
      if (event.key === '/' && document.activeElement?.tagName !== 'INPUT') {
        event.preventDefault()
        searchRef.current?.focus()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  return (
    <div ref={rootRef} className={`cx-docs${leaving ? ' is-leaving' : ''}`}>
      <div className="cxd-progress" aria-hidden="true"><span style={{ width: `${progress}%` }} /></div>

      <header className="cxd-topbar">
        <button className="cxd-brand" type="button" onClick={() => jumpTo('welcome')} aria-label="Go to guide introduction">
          <img src="/cryptx-logo-full.png" alt="CrypTX" />
          <span><strong>User manual</strong><small>Operations guide</small></span>
        </button>
        <label className="cxd-search">
          <Search size={16} aria-hidden="true" />
          <input ref={searchRef} value={query} onChange={event => setQuery(event.target.value)} placeholder="Search screens, tasks, or terms..." />
          {query ? <button type="button" onClick={() => setQuery('')} aria-label="Clear search"><X size={14} /></button> : <kbd>Ctrl K</kbd>}
        </label>
        <button className="cxd-close" type="button" onClick={close}><Power size={15} /> Start CrypTX</button>
      </header>

      <div className="cxd-shell">
        <aside className="cxd-toc" aria-label="Manual contents">
          {[...new Set(SECTIONS.map(section => section.group))].map(group => (
            <div className="cxd-toc-group" key={group}>
              <p>{group}</p>
              {SECTIONS.filter(section => section.group === group).map(section => (
                <button key={section.id} className={activeSection === section.id ? 'active' : ''} onClick={() => jumpTo(section.id)}>
                  <section.icon size={14} /> {section.label}
                </button>
              ))}
            </div>
          ))}
          <div className="cxd-side-note"><ShieldCheck size={16} /><span><b>Verified against the app</b>Updated for {SCREENS.length} implemented screens and {TOTAL_CHAINS} registered chains.</span></div>
        </aside>

        <main className="cxd-main">
          <section id="docs-welcome" className="cxd-section cxd-hero">
            <div className="cxd-kicker"><span /> CRYPTX FIELD MANUAL · 2026 EDITION</div>
            <h1>From first clue to<br /><em>defensible outcome.</em></h1>
            <p>CrypTX brings tracing, attribution, OSINT, compliance, evidence, collaboration, and recovery into one investigation workspace. This manual follows the product as it is implemented today.</p>
            <div className="cxd-hero-actions">
              <button className="primary" onClick={() => jumpTo('quickstart')}>Start the 60-second tour <ArrowRight size={16} /></button>
              <button onClick={() => jumpTo('screens')}>Browse every screen</button>
            </div>
            <div className="cxd-metrics">
              <article><strong>{SCREENS.filter(screen => screen.status === 'Primary').length}</strong><span>Primary tools</span></article>
              <article><strong>{SCREENS.length}</strong><span>Documented screens</span></article>
              <article><strong>{TOTAL_CHAINS}</strong><span>Registered chains</span></article>
              <article><strong>{SUPPORTED_TOKENS.length}</strong><span>Tracked assets</span></article>
            </div>
          </section>

          <section id="docs-quickstart" className="cxd-section">
            <div className="cxd-heading"><span>01 / ORIENTATION</span><h2>Your first investigation in four moves</h2><p>Use the product as a connected workspace. The value comes from preserving context while you pivot between tools.</p></div>
            <div className="cxd-quick-grid">
              {[
                ['01', 'Start with the strongest clue', 'Paste a wallet address, transaction hash, ENS name, or case reference into global search.'],
                ['02', 'Establish the facts', 'Use Address Intel or TX Lens before drawing conclusions. Confirm network, actors, assets, and time.'],
                ['03', 'Expand with purpose', 'Trace funds, map the network, enrich identity, and use specialist tools only where the evidence requires them.'],
                ['04', 'Preserve and communicate', 'File decisive artifacts in Evidence, coordinate in Cases, and generate the right report or recovery package.'],
              ].map(item => <article key={item[0]}><b>{item[0]}</b><h3>{item[1]}</h3><p>{item[2]}</p></article>)}
            </div>
            <div className="cxd-callout"><Lightbulb size={18} /><p><b>Analyst rule:</b> AI and predictive outputs are leads, not evidence. Confirm conclusions against transaction data, source provenance, and the documented method.</p></div>
          </section>

          <section id="docs-workspace" className="cxd-section">
            <div className="cxd-heading"><span>02 / NAVIGATION</span><h2>Know the workspace</h2><p>The shell stays consistent so you can move between modules without losing the subject or case context.</p></div>
            <div className="cxd-workspace-map">
              <div className="top"><strong>Global command bar</strong><span>Module island · global search · threat feed · health · notifications · profile</span></div>
              <div className="body">
                <div><strong>Module directory</strong><span>33 primary tools grouped by mission</span></div>
                <div className="canvas"><strong>Active screen</strong><span>Inputs → analysis → results → pivots → evidence</span><i>Most subjects can move directly into another module, case, board, or report.</i></div>
              </div>
            </div>
            <div className="cxd-three">
              <article><Search size={18} /><h3>Global search</h3><p>Search from the command bar; addresses open in Address Intel. Use the command palette for named modules and paste-and-go actions.</p></article>
              <article><BellRing size={18} /><h3>Notifications</h3><p>Monitor alerts and case-task messages appear in the top bar. Opening a case notification takes you to its working context.</p></article>
              <article><Settings size={18} /><h3>Personal controls</h3><p>Theme, density, profile, security, and provider configuration are available from the account controls.</p></article>
            </div>
          </section>

          <section id="docs-workflows" className="cxd-section">
            <div className="cxd-heading"><span>03 / PLAYBOOKS</span><h2>Guided operational workflows</h2><p>Select a mission to see the shortest defensible path through the product.</p></div>
            <div className="cxd-workflow-tabs" role="tablist" aria-label="Investigation workflows">
              {WORKFLOWS.map(item => <button role="tab" aria-selected={workflow === item.id} className={workflow === item.id ? 'active' : ''} key={item.id} onClick={() => setWorkflow(item.id)}><item.icon size={16} />{item.label}</button>)}
            </div>
            <div className="cxd-workflow-panel">
              <div className="cxd-outcome"><Target size={18} /><span><b>Outcome</b>{activeWorkflow.outcome}</span></div>
              <ol>{activeWorkflow.steps.map(([title, detail], index) => <li key={title}><span>{index + 1}</span><div><h3>{title}</h3><p>{detail}</p></div></li>)}</ol>
            </div>
          </section>

          <section id="docs-screens" className="cxd-section">
            <div className="cxd-heading"><span>04 / COMPLETE DIRECTORY</span><h2>Every implemented screen</h2><p>Filter by mission or search by task. Open a card for capabilities and an exact operating sequence.</p></div>
            <div className="cxd-directory-tools">
              <div className="cxd-suite-tabs">
                <button className={suite === 'All' ? 'active' : ''} onClick={() => setSuite('All')}>All <small>{SCREENS.length}</small></button>
                {SUITES.map(item => <button className={suite === item.key ? 'active' : ''} key={item.key} onClick={() => setSuite(item.key)}><item.icon size={14} />{item.key}<small>{SCREENS.filter(screen => screen.suite === item.key).length}</small></button>)}
              </div>
              <span className="cxd-result-count">{filtered.length} {filtered.length === 1 ? 'screen' : 'screens'}</span>
            </div>
            {filtered.length === 0 ? (
              <div className="cxd-empty"><Search size={28} /><h3>No matching screen</h3><p>Try a route, product name, workflow, or forensic term.</p><button onClick={() => { setQuery(''); setSuite('All') }}>Clear filters</button></div>
            ) : (
              <div className="cxd-screen-grid">
                {filtered.map(screen => {
                  const open = openScreen === screen.name
                  return <article className={`cxd-screen-card${open ? ' open' : ''}`} key={screen.name}>
                    <button className="cxd-screen-summary" onClick={() => setOpenScreen(open ? null : screen.name)} aria-expanded={open}>
                      <span className={`cxd-screen-icon suite-${screen.suite.toLowerCase()}`}><screen.icon size={20} /></span>
                      <span className="cxd-screen-name"><span><b>{screen.name}</b><i>{screen.status || 'Primary'}</i></span><code>{screen.route}</code></span>
                      <ChevronDown className="cxd-chevron" size={17} />
                    </button>
                    <p className="cxd-screen-blurb">{screen.summary}</p>
                    {open && <div className="cxd-screen-detail">
                      <div><h4>What is implemented</h4><ul>{screen.features.map(item => <li key={item}><Check size={13} />{item}</li>)}</ul></div>
                      <div><h4>How to operate it</h4><ol>{screen.use.map((item, index) => <li key={item}><span>{index + 1}</span>{item}</li>)}</ol></div>
                      <footer>
                        <span><ShieldCheck size={13} />{screen.roles || 'Authenticated analyst'}</span>
                        {screen.route.startsWith('/') && <button onClick={() => copyText(screen.route, setCopied)}>{copied === screen.route ? <Check size={13} /> : <Copy size={13} />}{copied === screen.route ? 'Copied' : 'Copy route'}</button>}
                      </footer>
                    </div>}
                  </article>
                })}
              </div>
            )}
          </section>

          <section id="docs-chains" className="cxd-section">
            <div className="cxd-heading"><span>05 / COVERAGE</span><h2>Chain and asset coverage</h2><p>The manual reads coverage from the same registry used by the Dashboard, so this list stays aligned with the product.</p></div>
            <div className="cxd-chain-tabs">{families.map(family => <button key={family} onClick={() => setChainFamily(family)} className={chainFamily === family ? 'active' : ''}>{family}<small>{family === 'All' ? SUPPORTED_CHAINS.length : SUPPORTED_CHAINS.filter(chain => chain.family === family).length}</small></button>)}</div>
            <div className="cxd-chain-grid">
              {visibleChains.map(chain => <article key={chain.id}><span style={{ background: chain.color, color: chain.textColor }}>{chain.symbol.slice(0, 4)}</span><div><b>{chain.name}</b><small>{chain.family} · {chain.explorer}</small></div><i className={chain.liveTrace ? 'live' : ''}>{chain.liveTrace ? 'Live trace' : 'Context only'}</i></article>)}
            </div>
            <div className="cxd-callout"><Globe2 size={18} /><p><b>Coverage is capability-specific.</b> Registration does not mean every connector supports every function. The Dashboard coverage matrix and each tool's chain selector are the operational source of truth.</p></div>
          </section>

          <section id="docs-evidence" className="cxd-section">
            <div className="cxd-heading"><span>06 / EVIDENCE STANDARD</span><h2>Make every conclusion reproducible</h2><p>A professional investigation separates observation, inference, and decision, and preserves the material needed to repeat the analysis.</p></div>
            <div className="cxd-evidence-flow">
              {[
                ['1', 'Collect', 'Capture transaction data, source URL, query context, and time.'],
                ['2', 'Explain', 'Record the method, parameters, confidence, and known limitations.'],
                ['3', 'Seal', 'Store the artifact in Evidence and verify the SHA-256 custody chain.'],
                ['4', 'Review', 'Use case tasks, deliverable review, and the audit log for oversight.'],
                ['5', 'Publish', 'Choose the report, filing, exhibit, or recovery package for the audience.'],
              ].map(item => <article key={item[0]}><span>{item[0]}</span><h3>{item[1]}</h3><p>{item[2]}</p></article>)}
            </div>
            <div className="cxd-warning"><ShieldAlert size={19} /><div><b>Do not overstate confidence.</b><p>Demixing, clustering, contract heuristics, predictive models, and AI narratives can identify strong leads. They still require corroboration before legal, regulatory, or recovery action.</p></div></div>
          </section>

          <section id="docs-security" className="cxd-section">
            <div className="cxd-heading"><span>07 / SECURITY & ACCESS</span><h2>Operate with least privilege</h2><p>CrypTX includes account, team, public-sharing, and provider controls. Treat them as part of the investigation process.</p></div>
            <div className="cxd-three">
              <article><LockKeyhole size={18} /><h3>Protect accounts</h3><p>Use unique passwords, complete forced rotation, enable 2FA, and never share recovery codes or sessions.</p></article>
              <article><Users size={18} /><h3>Govern the team</h3><p>Assign only the role needed, review members regularly, and use controlled recovery when disabling 2FA.</p></article>
              <article><Globe2 size={18} /><h3>Share deliberately</h3><p>Use password-protected board links for external review and revoke access when the engagement ends.</p></article>
            </div>
            <div className="cxd-callout"><KeyRound size={18} /><p><b>Provider credentials:</b> configure keys in Settings, verify connector status, and avoid placing credentials in case notes, prompts, exported files, or shared boards.</p></div>
          </section>

          <section id="docs-shortcuts" className="cxd-section">
            <div className="cxd-heading"><span>08 / QUICK REFERENCE</span><h2>Keyboard and navigation shortcuts</h2></div>
            <div className="cxd-shortcuts">
              <article><kbd>Ctrl / ⌘ K</kbd><span>Open the app command palette; focus manual search while reading docs.</span></article>
              <article><kbd>/</kbd><span>Focus search in this manual.</span></article>
              <article><kbd>Enter</kbd><span>Run the current search or submit a focused form.</span></article>
              <article><kbd>Esc</kbd><span>Close the current overlay or return from this manual.</span></article>
            </div>
            <footer className="cxd-footer">
              <img src="/cryptx-icon.svg" alt="" />
              <div><span>FIELD MANUAL COMPLETE</span><h2>Start with the evidence. Follow the value.</h2><p>Use this guide as a route map, then let each case determine which tools you need.</p></div>
              <button onClick={close}>Start CrypTX <ArrowRight size={16} /></button>
            </footer>
          </section>
        </main>
      </div>

      <button className="cxd-mobile-close" onClick={close} aria-label="Close user manual"><X size={18} /></button>
    </div>
  )
}
