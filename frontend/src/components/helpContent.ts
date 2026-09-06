/**
 * Help content for every CrypTX module.
 *
 * Each entry describes what the feature does, what input it expects,
 * an example input, and what output the user should expect.
 * The HelpOverlay reads this map based on the current route.
 */

export interface HelpEntry {
  title: string
  subtitle: string
  description: string
  inputType: string
  inputExample: string
  outputDescription: string
  tips?: string[]
}

const HELP_MAP: Record<string, HelpEntry> = {
  '/': {
    title: 'Dashboard',
    subtitle: 'Your investigation command center',
    description: 'The Dashboard is your central hub for all investigation activity. It provides a real-time overview of ongoing cases, recent investigations, risk alerts, and quick-access shortcuts to every module. Use the search bar to instantly look up any blockchain address, transaction hash, or entity.',
    inputType: 'Search query — blockchain address, transaction hash, domain, or entity name',
    inputExample: '0x71c92e1a3c9f4b8d6e5f0a1b2c3d4e5f6a7b8c9d',
    outputDescription: 'Instant navigation to the relevant investigation module with pre-filled data, plus a live overview of your workspace activity.',
    tips: ['Press Ctrl+K to open the command palette for faster navigation', 'Recent investigations appear in the bottom panel for quick resumption'],
  },
  '/intel': {
    title: 'Address Intelligence',
    subtitle: 'Deep-dive into any blockchain address',
    description: 'Address Intelligence performs a comprehensive analysis of any blockchain address across 15+ chains. It aggregates on-chain data, risk scores, entity labels, exposure analysis, and behavioral patterns to give you a complete picture of the address\'s activity and risk profile.',
    inputType: 'Blockchain address (EVM, BTC, SOL, TRX, TON, etc.)',
    inputExample: '0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045',
    outputDescription: 'Full address profile including: risk score (0-100), entity labels, transaction history, token holdings, exposure breakdown, behavioral tags, and cross-chain presence.',
    tips: ['Paste any address format — the system auto-detects the chain', 'Risk scores are color-coded: green (low), amber (medium), red (high)'],
  },
  '/trace': {
    title: 'Fund Tracer',
    subtitle: 'Follow the money across chains',
    description: 'Fund Tracer visualizes the complete flow of funds from a source address through multiple hops, chains, and intermediaries. It identifies mixing services, bridge crossings, cash-out points, and entity clusters — essential for AML investigations and asset recovery.',
    inputType: 'Source blockchain address or transaction hash',
    inputExample: 'bc1q9f3z8y4h2k5m6n7p0w1x2v3b4c5d6e7f8g9h',
    outputDescription: 'Interactive fund-flow graph showing: all fund paths, hop counts, total volumes, mixer/bridge detections, cash-out probability scores, and entity attributions at each node.',
    tips: ['Use the depth slider to control how many hops to trace', 'Red nodes indicate high-risk entities or mixers'],
  },
  '/dex': {
    title: 'DEX Analysis',
    subtitle: 'Decentralized exchange trading intelligence',
    description: 'Analyzes an address\'s activity on decentralized exchanges (DEXes) including swap history, liquidity provision, token launches participated in, wash-trading patterns, and sandwich attack exposure. Covers Uniswap, SushiSwap, PancakeSwap, and 50+ other DEX protocols.',
    inputType: 'Blockchain address with DEX activity',
    inputExample: '0xAb5801a7D398351b8bE11C439e05C5b3259aeC9B',
    outputDescription: 'DEX profile including: total swap volume, unique tokens traded, top DEX protocols used, liquidity pool positions, suspected wash-trading alerts, and PnL analysis.',
    tips: ['High-frequency small swaps may indicate bot activity', 'Token launch participation is flagged separately for rug-pull risk'],
  },
  '/nexus': {
    title: 'Nexus Graph',
    subtitle: 'Entity relationship visualization',
    description: 'Nexus Graph builds an interactive relationship graph connecting addresses, entities, transactions, and labels. It uses graph algorithms to detect clusters, identify common ownership, and reveal hidden connections between seemingly unrelated addresses.',
    inputType: 'One or more blockchain addresses to analyze relationships',
    inputExample: '0x71c92e1a3c9f4b8d6e5f0a1b2c3d4e5f6a7b8c9d',
    outputDescription: 'Interactive force-directed graph showing: connected addresses, entity clusters, transaction flows, common-input links, and risk propagation across the network.',
    tips: ['Click any node to drill into its full intelligence profile', 'Use the cluster detection to find co-controlled addresses'],
  },
  '/entity': {
    title: 'Entity Investigation',
    subtitle: 'Profile real-world entities behind addresses',
    description: 'Builds comprehensive dossiers on real-world entities (exchanges, mixers, DeFi protocols, darknet markets, sanctioned individuals) associated with blockchain addresses. Aggregates data from 20+ intelligence sources including on-chain analysis, OSINT feeds, and sanctions lists.',
    inputType: 'Entity name, address, or label to investigate',
    inputExample: 'Tornado Cash',
    outputDescription: 'Entity dossier including: type classification, associated addresses, risk rating, jurisdiction, sanctions status, connected entities, and timeline of significant events.',
    tips: ['Entities are auto-classified: Exchange, Mixer, DeFi, OTC, Darknet, etc.', 'Cross-reference with sanctions lists for compliance checks'],
  },
  '/tx-lens': {
    title: 'Transaction Lens',
    subtitle: 'Microscopic transaction forensics',
    description: 'Provides a detailed forensic breakdown of a single blockchain transaction. Decodes smart contract interactions, token transfers, internal transactions, gas analysis, and state changes. Essential for understanding complex DeFi exploits, MEV attacks, and multi-step transactions.',
    inputType: 'Transaction hash (any supported chain)',
    inputExample: '0x5c504ed432cb51138bcf09aa5e8a410dd4a1e204ef84bfed1be16dfba1b22060',
    outputDescription: 'Transaction breakdown including: decoded method calls, token flow diagram, internal transactions, gas usage analysis, state changes, risk flags, and human-readable explanation.',
    tips: ['The decoded view shows exactly what the smart contract executed', 'Internal transactions reveal hidden fund movements'],
  },
  '/monitor': {
    title: 'Wallet Monitor',
    subtitle: 'Real-time address surveillance',
    description: 'Set up persistent monitoring on blockchain addresses to receive real-time alerts when transactions occur. Configure custom notification thresholds, polling intervals, and alert delivery channels. Ideal for tracking suspects, monitoring compliance, or watching your own infrastructure.',
    inputType: 'Blockchain address + monitoring configuration (label, poll interval, alert threshold)',
    inputExample: 'Address: 0x71c9...af32 | Label: "Suspect Alpha" | Interval: 60s',
    outputDescription: 'Active monitoring dashboard with: real-time transaction alerts, notification history, balance change tracking, and configurable alert rules.',
    tips: ['Set shorter poll intervals for high-priority targets', 'Combine with case management for structured investigations'],
  },
  '/nft-tron': {
    title: 'NFT & TRON Sentinel',
    subtitle: 'NFT and TRON network intelligence',
    description: 'Specialized module for analyzing NFT holdings, collections, and TRON blockchain activity. Profiles NFT portfolios, detects wash-trading in NFT markets, identifies rare token movements, and monitors TRX/TRC-20 token flows.',
    inputType: 'Blockchain address (EVM for NFTs, TRX for TRON network)',
    inputExample: 'TN3W4H6rK2ce4vX9YonAHGc3jSgRQUqMgR (TRON)',
    outputDescription: 'NFT/TRON profile including: collection holdings, floor value estimates, trading history, wash-trade detection, TRX balance, TRC-20 tokens, and DeFi positions on TRON.',
    tips: ['NFT wash-trading is flagged with confidence scores', 'TRON DeFi positions include SunSwap and JustLend data'],
  },
  '/auto': {
    title: 'Auto Investigate',
    subtitle: 'One-click full-spectrum investigation',
    description: 'Automatically runs a comprehensive investigation across all modules for a given address. Combines address intelligence, fund tracing, entity lookup, risk scoring, OSINT sweep, and sanctions screening into a single unified report. The fastest way to get a 360° view.',
    inputType: 'Blockchain address to investigate',
    inputExample: '0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045',
    outputDescription: 'Unified investigation report combining: risk score, entity labels, fund flow summary, sanctions matches, OSINT findings, behavioral tags, and recommended next steps.',
    tips: ['Auto-investigate runs all modules in parallel for speed', 'Review each section for details — the summary is just the overview'],
  },
  '/ai-agent': {
    title: 'AI Investigator',
    subtitle: 'Natural language blockchain investigation',
    description: 'An AI-powered investigation assistant that understands natural language queries about blockchain activity. Ask it to trace funds, explain transactions, identify suspicious patterns, or generate investigation narratives. Powered by advanced LLMs with blockchain-specific context.',
    inputType: 'Natural language question or investigation request',
    inputExample: '"Trace the flow of funds from 0x71c9...af32 and identify any mixer interactions"',
    outputDescription: 'AI-generated investigation narrative with: step-by-step fund flow analysis, entity attributions, risk assessments, visual diagrams, and actionable conclusions.',
    tips: ['Be specific with addresses and chain names for best results', 'The AI can chain multiple investigation steps in a single query'],
  },
  '/osint': {
    title: 'OSINT Sweep',
    subtitle: 'Open-source intelligence gathering',
    description: 'Performs an automated open-source intelligence sweep across the web for a given address or entity. Searches breach databases, paste sites, forums, social media, and dark web sources for any mentions, associations, or exposed credentials linked to the target.',
    inputType: 'Blockchain address, email, username, or domain',
    inputExample: '0x71c92e1a3c9f4b8d6e5f0a1b2c3d4e5f6a7b8c9d',
    outputDescription: 'OSINT report including: breach mentions, paste site hits, forum posts, social media connections, dark web references, and confidence-scored associations.',
    tips: ['Results are sourced from public databases only', 'Low-confidence matches should be manually verified'],
  },
  '/cases': {
    title: 'Case Manager',
    subtitle: 'Structured investigation management',
    description: 'Create and manage structured investigation cases. Link addresses, evidence, notes, and team members to a case. Track investigation progress, generate reports, and maintain a chain of custody for all evidence. Supports collaboration across multiple analysts.',
    inputType: 'Case name, description, and linked addresses/evidence',
    inputExample: 'Case: "Operation Dark Flow" | Addresses: 3 suspects | Status: Active',
    outputDescription: 'Case dashboard with: linked addresses and their risk profiles, evidence vault, investigation timeline, team assignments, notes, and exportable reports.',
    tips: ['Add evidence early — the chain of custody is timestamped', 'Use tags to categorize addresses within a case'],
  },
  '/batch': {
    title: 'Batch Screener',
    subtitle: 'Screen hundreds of addresses at once',
    description: 'Upload or paste a list of blockchain addresses to screen them all simultaneously against risk databases, sanctions lists, and entity labels. Returns a consolidated risk report for the entire batch. Ideal for compliance checks, portfolio screening, or bulk due diligence.',
    inputType: 'List of blockchain addresses (one per line, CSV, or file upload)',
    inputExample: '0x71c9...af32\nbc1q9f...4e2a\nTN3W4H...qMgR',
    outputDescription: 'Batch screening report: per-address risk scores, sanctions matches, entity labels, exposure totals, and a summary dashboard with risk distribution.',
    tips: ['CSV upload supports up to 10,000 addresses per batch', 'Export results as CSV for compliance records'],
  },
  '/sanctions': {
    title: 'Sanctions Screener',
    subtitle: 'Regulatory sanctions compliance',
    description: 'Screens blockchain addresses against global sanctions lists including OFAC, EU, UN, UK HMT, and 15+ other regulatory databases. Provides match confidence scores, list source attribution, and compliance-ready reports for regulatory submissions.',
    inputType: 'Blockchain address or entity name',
    inputExample: '0x8589...3f2e',
    outputDescription: 'Sanctions screening result: match status (clear/match/potential), matched lists, confidence score, jurisdiction details, and exportable compliance certificate.',
    tips: ['A "potential" match requires manual review — it may be a false positive', 'Export compliance reports for audit trails'],
  },
  '/attribution': {
    title: 'Attribution Lookup',
    subtitle: 'Identify who controls an address',
    description: 'Determines the real-world entity behind a blockchain address using a combination of on-chain heuristics, label databases, OSINT correlations, and community-sourced intelligence. Covers exchanges, mixers, DeFi protocols, individual actors, and sanctioned entities.',
    inputType: 'Blockchain address to attribute',
    inputExample: '0x28C6c06298d514Db089934071355E5743bf21d60',
    outputDescription: 'Attribution result: entity name, entity type (Exchange/Mixer/Individual/etc.), confidence level, source attribution, and linked addresses in the same cluster.',
    tips: ['Confidence levels: High (>90%), Medium (60-90%), Low (<60%)', 'Submit your own attributions to help the community'],
  },
  '/demix': {
    title: 'Demix Lab',
    subtitle: 'Mixer/deanonymization analysis',
    description: 'Advanced deanonymization engine that analyzes addresses that have interacted with mixing services (Tornado Cash, Wasabi, Samourai, etc.). Uses statistical analysis, timing correlation, and denomination clustering to attempt to link pre-mix and post-mix addresses.',
    inputType: 'Address that has interacted with a mixer',
    inputExample: '0x4e5b2c1a8f3d7e9f0a1b2c3d4e5f6a7b8c9d0e1f',
    outputDescription: 'Demixing analysis: mixer interaction history, deposit/withdrawal correlation scores, potential pre-mix source addresses, confidence levels, and statistical evidence.',
    tips: ['Higher correlation scores indicate stronger deanonymization evidence', 'Results should be corroborated with other investigation methods'],
  },
  '/evidence': {
    title: 'Evidence Vault',
    subtitle: 'Court-admissible evidence management',
    description: 'Securely store, hash, and timestamp investigation evidence with full chain-of-custody tracking. Every piece of evidence is cryptographically hashed and optionally timestamped via RFC-3161 trusted timestamping for court admissibility. Supports screenshots, transaction records, and exported reports.',
    inputType: 'Evidence file, URL, or blockchain reference + description',
    inputExample: 'Screenshot of transaction 0x5c50...2060 on Etherscan | Case: "Dark Flow"',
    outputDescription: 'Evidence record with: SHA-256 hash, timestamp, chain-of-custody log, linked case, integrity verification status, and exportable certificate.',
    tips: ['Enable RFC-3161 timestamping for court-admissible evidence', 'Every modification is logged — the chain of custody is immutable'],
  },
  '/boards': {
    title: 'Investigation Boards',
    subtitle: 'Visual collaboration canvas',
    description: 'Create visual investigation boards (similar to detective string boards) where you can place addresses, entities, transactions, and evidence on an infinite canvas. Draw connections, add annotations, and collaborate with team members in real-time.',
    inputType: 'Board name + drag-and-drop elements from investigation results',
    inputExample: 'Board: "Operation Dark Flow" — drag suspect addresses, link transactions, annotate connections',
    outputDescription: 'Interactive canvas with: positioned nodes, connection lines, annotations, shared editing, and exportable board snapshots.',
    tips: ['Share boards with team members for collaborative analysis', 'Use color coding to distinguish suspects, victims, and neutral entities'],
  },
  '/predictive': {
    title: 'Predictive Intelligence',
    subtitle: 'AI-powered risk forecasting',
    description: 'Uses machine learning models to predict future risk patterns, identify emerging threat clusters, and forecast address behavior. Analyzes historical patterns to flag addresses likely to be involved in future illicit activity.',
    inputType: 'Address or entity to analyze for predictive risk',
    inputExample: '0x71c92e1a3c9f4b8d6e5f0a1b2c3d4e5f6a7b8c9d',
    outputDescription: 'Predictive analysis: risk trajectory (rising/stable/declining), behavioral forecasts, cluster evolution predictions, and early-warning alerts for emerging threats.',
    tips: ['Predictive scores improve with more on-chain history', 'Use early warnings to proactively monitor emerging threats'],
  },
  '/labels': {
    title: 'Label Management',
    subtitle: 'Community intelligence database',
    description: 'Manage your custom address labels and browse the community-contributed label database. Labels classify addresses by entity type, risk category, and behavioral tags. Create, import, export, and share labels across your organization.',
    inputType: 'Address + label category + confidence level',
    inputExample: '0x71c9...af32 → "Exchange: Binance" | Confidence: High',
    outputDescription: 'Label database with: categorized addresses, source attribution, confidence levels, and search/filter capabilities. Exportable for integration with other tools.',
    tips: ['Use bulk import to add labels from CSV files', 'High-confidence labels improve risk scoring accuracy'],
  },
  '/reports': {
    title: 'Report Studio',
    subtitle: 'Professional investigation reports',
    description: 'Generate professional, court-ready investigation reports from your case data. Combines address intelligence, fund traces, entity attributions, and evidence into a structured narrative with charts, graphs, and exhibits. Export as PDF, HTML, or JSON.',
    inputType: 'Case ID or investigation data to include in the report',
    inputExample: 'Case: "Dark Flow" | Include: fund trace, entity attributions, evidence vault',
    outputDescription: 'Professional report with: executive summary, methodology, findings, visual exhibits, chain of custody, and appendix. Exportable as PDF/HTML.',
    tips: ['Use templates for consistent report formatting', 'Include the Daubert section for court-admissible methodology'],
  },
  '/threat-landscape': {
    title: 'Blockchain Threat Landscape',
    subtitle: 'Real-time threat intelligence feed',
    description: 'Aggregated cybersecurity and blockchain threat intelligence from 20+ curated sources. Covers vulnerability disclosures, exploit analyses, sanctions updates, scam patterns, and regulatory changes. Stay informed about the latest threats affecting your investigations.',
    inputType: 'No input required — auto-curated feed. Use search to filter topics.',
    inputExample: 'Search: "Tornado Cash sanctions"',
    outputDescription: 'Curated threat feed with: article summaries, source attribution, severity indicators, and full-article detail view with original source links.',
    tips: ['Feed sources are vetted for reliability and relevance', 'Click any article for the full analysis'],
  },
  '/contract-forensics': {
    title: 'Contract Forensics',
    subtitle: 'Smart contract security analysis',
    description: 'Deep forensic analysis of smart contracts including bytecode decompilation, vulnerability detection, exploit pattern matching, and behavioral simulation. Identifies honeypots, rug-pull mechanisms, hidden backdoors, and known vulnerability patterns.',
    inputType: 'Smart contract address',
    inputExample: '0x1f9840a85d5aF5bf1D1762F925BDADdC4201F984',
    outputDescription: 'Contract forensics report: decompiled source, detected vulnerabilities, exploit patterns, honeypot indicators, token analysis, and risk assessment.',
    tips: ['Always verify contract source code on the block explorer', 'Honeypot detection uses multiple heuristic signals'],
  },
  '/laundering': {
    title: 'Laundering Trace',
    subtitle: 'Money laundering pattern detection',
    description: 'Specialized engine for detecting money laundering patterns including chain-hopping, layering, integration techniques, and professional laundering services. Identifies common typologies: peeling chains, coinjoins, nested mixers, and cross-chain tunnels.',
    inputType: 'Source address or transaction to analyze for laundering patterns',
    inputExample: '0x71c92e1a3c9f4b8d6e5f0a1b2c3d4e5f6a7b8c9d',
    outputDescription: 'Laundering analysis: detected typologies, pattern confidence scores, involved services (mixers/bridges/OTC), chain-hop map, and integration/cash-out identification.',
    tips: ['Peeling chains show repeated small withdrawals from a large deposit', 'Cross-chain tunnels often use bridges + DEX swaps'],
  },
  '/court-readiness': {
    title: 'Court Readiness',
    subtitle: 'Legal admissibility preparation',
    description: 'Prepares investigation evidence and methodology for court submission. Validates chain of custody, generates Daubert-compliant methodology documentation, calculates error rates, and produces judge-friendly exhibits. Ensures your blockchain evidence meets legal standards.',
    inputType: 'Case ID or evidence set to validate',
    inputExample: 'Case: "Dark Flow" | Validate: all evidence + methodology',
    outputDescription: 'Court-readiness report: chain-of-custody validation, Daubert documentation, error-rate analysis, exhibit package, and admissibility checklist.',
    tips: ['Enable RFC-3161 timestamping early in the investigation', 'Document your methodology as you go — don\'t retroactively'],
  },
  '/recovery': {
    title: 'Recovery Ops',
    subtitle: 'Asset recovery operations',
    description: 'Operational toolkit for cryptocurrency asset recovery. Identifies cash-out points, generates freeze requests for exchanges and VASPs, tracks assets through custody transitions, and produces the documentation needed for law enforcement coordination and legal proceedings.',
    inputType: 'Case ID or address to track for recovery',
    inputExample: 'Case: "Dark Flow" | Track stolen funds to cash-out',
    outputDescription: 'Recovery operations dashboard: fund location tracking, cash-out point identification, VASP contact details, freeze request templates, and law enforcement referral package.',
    tips: ['Act quickly — funds at exchanges can be frozen if reported in time', 'Use the freeze request templates for faster VASP coordination'],
  },
  '/comply': {
    title: 'Compliance Suite',
    subtitle: 'Regulatory compliance toolkit',
    description: 'Comprehensive compliance toolkit combining sanctions screening, travel rule verification, KYV (Know Your VASP) checks, transaction monitoring alerts, and regulatory report generation. Designed for crypto businesses needing to meet AML/CFT obligations.',
    inputType: 'Address, transaction, or customer identifier to screen',
    inputExample: 'Customer wallet: 0x71c9...af32 | Transaction: 0x5c50...2060',
    outputDescription: 'Compliance report: sanctions screening results, travel rule compliance status, VASP identification, risk categorization, and regulatory filing recommendations.',
    tips: ['Run screening before and after transactions for ongoing monitoring', 'Export compliance reports for regulatory audit trails'],
  },
  '/freeze-desk': {
    title: 'Freeze Desk',
    subtitle: 'Asset freeze coordination',
    description: 'Operational desk for coordinating asset freeze requests across exchanges, VASPs, and law enforcement agencies. Tracks freeze request status, manages communication templates, and maintains a database of VASP contacts and legal requirements by jurisdiction.',
    inputType: 'Target address/exchange + case reference',
    inputExample: 'Address: 0x71c9...af32 | Exchange: Binance | Case: "Dark Flow"',
    outputDescription: 'Freeze desk dashboard: request status tracking, VASP contact directory, jurisdiction-specific legal requirements, communication templates, and law enforcement liaison contacts.',
    tips: ['Time is critical — most exchanges require action within 24-48 hours', 'Include the transaction hash and chain in every freeze request'],
  },
  '/scam-atlas': {
    title: 'Scam Network Atlas',
    subtitle: 'Scam infrastructure mapping',
    description: 'Maps and analyzes scam infrastructure networks including phishing sites, fake token contracts, social engineering operations, and pump-and-dump schemes. Identifies shared infrastructure, common operators, and victim patterns across scam campaigns.',
    inputType: 'Suspected scam address, contract, or domain',
    inputExample: '0xdead...beef (suspected rug-pull contract)',
    outputDescription: 'Scam atlas visualization: connected scam operations, shared infrastructure, operator clusters, victim count estimates, and timeline of scam activity.',
    tips: ['Report confirmed scams to help build the database', 'Cross-reference with OSINT findings for operator identification'],
  },
  '/perp-dex': {
    title: 'Perp DEX Intel',
    subtitle: 'Perpetual futures exchange analysis',
    description: 'Specialized analysis of perpetual futures trading on decentralized exchanges. Tracks leveraged positions, liquidation patterns, funding rate manipulation, and whale activity on platforms like dYdX, GMX, Hyperliquid, and Jupiter.',
    inputType: 'Trader address on a perp DEX',
    inputExample: '0x71c92e1a3c9f4b8d6e5f0a1b2c3d4e5f6a7b8c9d (Hyperliquid)',
    outputDescription: 'Perp trading profile: open positions, PnL history, liquidation events, funding rate impact, leverage patterns, and market manipulation indicators.',
    tips: ['Sudden large position closures may indicate insider trading', 'Funding rate manipulation is a common oracle attack vector'],
  },
  '/victim-reports': {
    title: 'Victim Reports',
    subtitle: 'Victim incident management',
    description: 'Manage victim incident reports from initial intake through investigation to resolution. Provides a structured intake form, evidence collection workflow, and victim communication tracking. Supports the victim portal for direct report submission.',
    inputType: 'Victim report data (incident details, stolen amounts, suspect addresses)',
    inputExample: 'Victim: John Doe | Stolen: 5 BTC | Suspect: 0x71c9...af32 | Date: 2026-07-15',
    outputDescription: 'Victim report dashboard: incident timeline, linked investigations, evidence status, communication log, and resolution tracking.',
    tips: ['Collect as much detail as possible during initial intake', 'Link the report to a case for structured investigation'],
  },
  '/settings': {
    title: 'Settings',
    subtitle: 'Platform configuration',
    description: 'Configure your CrypTX deployment including API keys for blockchain explorers and AI providers, tool feature toggles, notification preferences, and system parameters. Admin-only: API key changes affect all users in your organization.',
    inputType: 'Configuration values (API keys, feature toggles, preferences)',
    inputExample: 'Etherscan API Key: YOUR_KEY_HERE | AI Provider: DeepSeek | Timeout: 120s',
    outputDescription: 'Updated configuration applied immediately. API keys are validated on save. Feature toggles take effect on next page load.',
    tips: ['API keys are stored encrypted in the server environment', 'Test API keys after saving to verify connectivity'],
  },
  '/profile': {
    title: 'User Profile',
    subtitle: 'Your account settings',
    description: 'Manage your personal account settings including display name, password, active sessions, security preferences, and notification settings. Review and revoke active sessions from any device.',
    inputType: 'Profile fields (name, password, session management)',
    inputExample: 'Name: "Agent Smith" | Change password | Revoke session on "Chrome/Windows"',
    outputDescription: 'Updated profile with: new display name, confirmed password change, active session list with revoke capability.',
    tips: ['Revoke unknown sessions immediately', 'Use a strong, unique password for your account'],
  },
  '/nl-agent': {
    title: 'NL Investigation Agent',
    subtitle: 'Natural language multi-step investigation',
    description: 'An advanced AI agent that executes multi-step investigation workflows from natural language instructions. It can trace funds, run OSINT sweeps, check sanctions, build cases, and generate reports — all from a single prompt. The most powerful investigation tool.',
    inputType: 'Natural language investigation instruction',
    inputExample: '"Investigate 0x71c9...af32: trace stolen funds, identify the exchange cash-out, and prepare a freeze request"',
    outputDescription: 'Multi-step investigation execution with: progress tracking, intermediate results, final report, and recommended actions. Each step is logged for audit.',
    tips: ['Be specific about what you want — the agent follows your instructions literally', 'Review each step\'s output before approving the final report'],
  },
  '/rules': {
    title: 'Alert Rules',
    subtitle: 'No-code alert configuration',
    description: 'Create custom alert rules using a visual no-code rule builder. Define conditions based on address risk, transaction patterns, entity labels, and sanctions matches. When conditions are met, alerts are triggered and delivered to your configured channels.',
    inputType: 'Rule conditions (visual builder) + alert delivery configuration',
    inputExample: 'IF risk_score > 80 AND entity_type = "Mixer" THEN alert via email + create case',
    outputDescription: 'Active alert rules with: condition definitions, dry-run results, alert history, and delivery confirmation.',
    tips: ['Use dry-run to test rules before activating them', 'Combine multiple conditions with AND/OR for precise targeting'],
  },
}

/**
 * Get help content for the current route.
 * Matches the most specific route prefix.
 */
export function getHelpForRoute(pathname: string): HelpEntry | null {
  // Exact match first
  if (HELP_MAP[pathname]) return HELP_MAP[pathname]

  // Prefix match (e.g., /intel/0x123 → /intel)
  const sortedKeys = Object.keys(HELP_MAP).sort((a, b) => b.length - a.length)
  for (const key of sortedKeys) {
    if (pathname.startsWith(key) && (pathname.length === key.length || pathname[key.length] === '/' || pathname[key.length] === '?')) {
      return HELP_MAP[key]
    }
  }

  // Fallback: try the first path segment
  const segment = '/' + pathname.split('/').filter(Boolean)[0]
  if (HELP_MAP[segment]) return HELP_MAP[segment]

  return null
}
