/**
 * BoardCanvas — crimewall-grade investigation canvas.
 *  • Everything from the classic board: autosave, drag/multi-select, clusters,
 *    tx-split nodes, 1-hop expand, fiat toggle, share links, threaded comments
 *  • Crimewall entities: person / org / exchange / IP / email / phone / social /
 *    evidence / event / wallet pins with lead status (suspect · confirmed ·
 *    cleared · POI) and priority flags
 *  • Red-string mode: draw labeled relationship links (controls, same-owner,
 *    KYC match…) with analyst confidence between ANY two pins
 *  • Zones: named, colored canvas regions (e.g. "Layering", "Cash-out")
 *  • Layouts: force-directed, timeline (by tx time, lanes per chain), grid + fit-to-view
 *  • Pro tools: undo/redo, canvas search, minimap, legend, PNG export
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import {
  ArrowLeft, AtSign, BoxSelect, Building2, CalendarClock, Camera, Check, ChevronDown,
  ChevronUp, Coins, Copy, DollarSign, Expand, FileText, Flag, GitBranch, GitMerge, Globe,
  Landmark, LayoutGrid, Link2, Loader2, Lock, Mail, Maximize2, MessageSquare,
  MousePointer2, Network, Phone, Pin, Plus, Redo2, Search, Server, Share2,
  ShieldAlert, Spline, Split, StickyNote, Trash2, Undo2, User, UserPlus, Users,
  Wallet, Waypoints, X, Boxes,
} from 'lucide-react'
import {
  getBoard, updateBoard, createShare, listShares, revokeShare,
  listComments, addComment, resolveComment, convertBatch,
  boardLinks, addBoardLink,
  EMPTY_BOARD_STATE, RELATIONSHIP_KINDS,
  type Board, type BoardState, type BoardNode, type BoardEdge, type BoardZone,
  type BoardShare, type BoardComment, type NodeShape, type NodeKind, type BoardLink,
  type LeadStatus, type RelationshipKind,
} from '../api/boards'
import { holisticTrace, type HolisticEdge, type HolisticNode } from '../api/holistic'
import { lookupTx } from '../api/client'
import { GraphNodeKit } from '../lib/graphkit'

// ── helpers ───────────────────────────────────────────────────────────────────

let _uid = 0
const uid = (p: string) => `${p}_${Date.now().toString(36)}_${(_uid++).toString(36)}`

const short = (a: string) => (a.length > 14 ? `${a.slice(0, 8)}…${a.slice(-4)}` : a)

const CHAIN_COLORS: Record<string, string> = {
  btc: '#f7931a', eth: '#627eea', tron: '#ff2d55', trx: '#ff2d55', sol: '#9945ff',
  polygon: '#8247e5', arbitrum: '#28a0f0', optimism: '#ff0420', base: '#0052ff',
  bsc: '#f0b90b', zcash: '#ecb244',
}
const chainColor = (c: string) => CHAIN_COLORS[(c || '').toLowerCase()] || '#8e9db5'

function detectChain(addr: string): string {
  if (/^0x[a-fA-F0-9]{40}$/.test(addr)) return 'eth'
  if (/^(bc1|[13])[a-zA-Z0-9]{20,60}$/.test(addr)) return 'btc'
  if (/^T[A-Za-z0-9]{33}$/.test(addr)) return 'tron'
  if (/^[1-9A-HJ-NP-Za-km-z]{32,44}$/.test(addr)) return 'sol'
  return 'eth'
}

const NODE_R = 26
const nodeKey = (chain: string, ref: string) => `${(chain || '').toLowerCase()}:${ref.toLowerCase()}`

const PALETTE = ['#8e9db5', '#5b9fd6', '#d4a843', '#ef4444', '#10b981', '#8b80d4', '#f59e0b', '#7c8aa5']

// ── crimewall entity metadata ─────────────────────────────────────────────────

const ENTITY_META: Record<string, { label: string; color: string; Icon: typeof User; refHint: string }> = {
  person:   { label: 'Person',     color: '#d4a843', Icon: User,          refHint: 'Full name / alias' },
  org:      { label: 'Organization', color: '#5b9fd6', Icon: Building2,   refHint: 'Company / group name' },
  exchange: { label: 'Exchange',   color: '#10b981', Icon: Landmark,      refHint: 'VASP / exchange name' },
  wallet:   { label: 'Wallet',     color: '#7c8aa5', Icon: Wallet,        refHint: 'Wallet label / xpub' },
  ip:       { label: 'IP address', color: '#8b80d4', Icon: Server,        refHint: 'e.g. 185.220.101.4' },
  email:    { label: 'Email',      color: '#d4a843', Icon: Mail,          refHint: 'e.g. suspect@mail.com' },
  phone:    { label: 'Phone',      color: '#34d399', Icon: Phone,         refHint: 'e.g. +1 555 0100' },
  social:   { label: 'Social handle', color: '#f472b6', Icon: AtSign,     refHint: 'e.g. @handle (platform)' },
  evidence: { label: 'Evidence',   color: '#8e9db5', Icon: FileText,      refHint: 'Exhibit ID / URL' },
  event:    { label: 'Event',      color: '#a08866', Icon: CalendarClock, refHint: 'e.g. 2026-01-14 hack' },
}
const ENTITY_KINDS = Object.keys(ENTITY_META) as NodeKind[]
const isEntity = (k: NodeKind) => k in ENTITY_META

// ── social-handle platform picker ─────────────────────────────────────────────
// Brand marks are single-path SVGs (viewBox 0 0 24 24) sourced from Simple Icons.
const SOCIAL_PLATFORMS: { name: string; hex: string; path: string }[] = [
  { name: 'X / Twitter', hex: '#000000', path: 'M14.234 10.162 22.977 0h-2.072l-7.591 8.824L7.251 0H.258l9.168 13.343L.258 24H2.33l8.016-9.318L16.749 24h6.993zm-2.837 3.299-.929-1.329L3.076 1.56h3.182l5.965 8.532.929 1.329 7.754 11.09h-3.182z' },
  { name: 'Telegram', hex: '#26A5E4', path: 'M11.944 0A12 12 0 0 0 0 12a12 12 0 0 0 12 12 12 12 0 0 0 12-12A12 12 0 0 0 12 0a12 12 0 0 0-.056 0zm4.962 7.224c.1-.002.321.023.465.14a.506.506 0 0 1 .171.325c.016.093.036.306.02.472-.18 1.898-.962 6.502-1.36 8.627-.168.9-.499 1.201-.82 1.23-.696.065-1.225-.46-1.9-.902-1.056-.693-1.653-1.124-2.678-1.8-1.185-.78-.417-1.21.258-1.91.177-.184 3.247-2.977 3.307-3.23.007-.032.014-.15-.056-.212s-.174-.041-.249-.024c-.106.024-1.793 1.14-5.061 3.345-.48.33-.913.49-1.302.48-.428-.008-1.252-.241-1.865-.44-.752-.245-1.349-.374-1.297-.789.027-.216.325-.437.893-.663 3.498-1.524 5.83-2.529 6.998-3.014 3.332-1.386 4.025-1.627 4.476-1.635z' },
  { name: 'Discord', hex: '#5865F2', path: 'M20.317 4.3698a19.7913 19.7913 0 00-4.8851-1.5152.0741.0741 0 00-.0785.0371c-.211.3753-.4447.8648-.6083 1.2495-1.8447-.2762-3.68-.2762-5.4868 0-.1636-.3933-.4058-.8742-.6177-1.2495a.077.077 0 00-.0785-.037 19.7363 19.7363 0 00-4.8852 1.515.0699.0699 0 00-.0321.0277C.5334 9.0458-.319 13.5799.0992 18.0578a.0824.0824 0 00.0312.0561c2.0528 1.5076 4.0413 2.4228 5.9929 3.0294a.0777.0777 0 00.0842-.0276c.4616-.6304.8731-1.2952 1.226-1.9942a.076.076 0 00-.0416-.1057c-.6528-.2476-1.2743-.5495-1.8722-.8923a.077.077 0 01-.0076-.1277c.1258-.0943.2517-.1923.3718-.2914a.0743.0743 0 01.0776-.0105c3.9278 1.7933 8.18 1.7933 12.0614 0a.0739.0739 0 01.0785.0095c.1202.099.246.1981.3728.2924a.077.077 0 01-.0066.1276 12.2986 12.2986 0 01-1.873.8914.0766.0766 0 00-.0407.1067c.3604.698.7719 1.3628 1.225 1.9932a.076.076 0 00.0842.0286c1.961-.6067 3.9495-1.5219 6.0023-3.0294a.077.077 0 00.0313-.0552c.5004-5.177-.8382-9.6739-3.5485-13.6604a.061.061 0 00-.0312-.0286zM8.02 15.3312c-1.1825 0-2.1569-1.0857-2.1569-2.419 0-1.3332.9555-2.4189 2.157-2.4189 1.2108 0 2.1757 1.0952 2.1568 2.419 0 1.3332-.9555 2.4189-2.1569 2.4189zm7.9748 0c-1.1825 0-2.1569-1.0857-2.1569-2.419 0-1.3332.9554-2.4189 2.1569-2.4189 1.2108 0 2.1757 1.0952 2.1568 2.419 0 1.3332-.946 2.4189-2.1568 2.4189Z' },
  { name: 'Signal', hex: '#3B45FD', path: 'M12 0q-.934 0-1.83.139l.17 1.111a11 11 0 0 1 3.32 0l.172-1.111A12 12 0 0 0 12 0M9.152.34A12 12 0 0 0 5.77 1.742l.584.961a10.8 10.8 0 0 1 3.066-1.27zm5.696 0-.268 1.094a10.8 10.8 0 0 1 3.066 1.27l.584-.962A12 12 0 0 0 14.848.34M12 2.25a9.75 9.75 0 0 0-8.539 14.459c.074.134.1.292.064.441l-1.013 4.338 4.338-1.013a.62.62 0 0 1 .441.064A9.7 9.7 0 0 0 12 21.75c5.385 0 9.75-4.365 9.75-9.75S17.385 2.25 12 2.25m-7.092.068a12 12 0 0 0-2.59 2.59l.909.664a11 11 0 0 1 2.345-2.345zm14.184 0-.664.909a11 11 0 0 1 2.345 2.345l.909-.664a12 12 0 0 0-2.59-2.59M1.742 5.77A12 12 0 0 0 .34 9.152l1.094.268a10.8 10.8 0 0 1 1.269-3.066zm20.516 0-.961.584a10.8 10.8 0 0 1 1.27 3.066l1.093-.268a12 12 0 0 0-1.402-3.383M.138 10.168A12 12 0 0 0 0 12q0 .934.139 1.83l1.111-.17A11 11 0 0 1 1.125 12q0-.848.125-1.66zm23.723.002-1.111.17q.125.812.125 1.66c0 .848-.042 1.12-.125 1.66l1.111.172a12.1 12.1 0 0 0 0-3.662M1.434 14.58l-1.094.268a12 12 0 0 0 .96 2.591l-.265 1.14 1.096.255.36-1.539-.188-.365a10.8 10.8 0 0 1-.87-2.35m21.133 0a10.8 10.8 0 0 1-1.27 3.067l.962.584a12 12 0 0 0 1.402-3.383zm-1.793 3.848a11 11 0 0 1-2.345 2.345l.664.909a12 12 0 0 0 2.59-2.59zm-19.959 1.1L.357 21.48a1.8 1.8 0 0 0 2.162 2.161l1.954-.455-.256-1.095-1.953.455a.675.675 0 0 1-.81-.81l.454-1.954zm16.832 1.769a10.8 10.8 0 0 1-3.066 1.27l.268 1.093a12 12 0 0 0 3.382-1.402zm-10.94.213-1.54.36.256 1.095 1.139-.266c.814.415 1.683.74 2.591.961l.268-1.094a10.8 10.8 0 0 1-2.35-.869zm3.634 1.24-.172 1.111a12.1 12.1 0 0 0 3.662 0l-.17-1.111q-.812.125-1.66.125a11 11 0 0 1-1.66-.125' },
  { name: 'WhatsApp', hex: '#25D366', path: 'M17.472 14.382c-.297-.149-1.758-.867-2.03-.967-.273-.099-.471-.148-.67.15-.197.297-.767.966-.94 1.164-.173.199-.347.223-.644.075-.297-.15-1.255-.463-2.39-1.475-.883-.788-1.48-1.761-1.653-2.059-.173-.297-.018-.458.13-.606.134-.133.298-.347.446-.52.149-.174.198-.298.298-.497.099-.198.05-.371-.025-.52-.075-.149-.669-1.612-.916-2.207-.242-.579-.487-.5-.669-.51-.173-.008-.371-.01-.57-.01-.198 0-.52.074-.792.372-.272.297-1.04 1.016-1.04 2.479 0 1.462 1.065 2.875 1.213 3.074.149.198 2.096 3.2 5.077 4.487.709.306 1.262.489 1.694.625.712.227 1.36.195 1.871.118.571-.085 1.758-.719 2.006-1.413.248-.694.248-1.289.173-1.413-.074-.124-.272-.198-.57-.347m-5.421 7.403h-.004a9.87 9.87 0 01-5.031-1.378l-.361-.214-3.741.982.998-3.648-.235-.374a9.86 9.86 0 01-1.51-5.26c.001-5.45 4.436-9.884 9.888-9.884 2.64 0 5.122 1.03 6.988 2.898a9.825 9.825 0 012.893 6.994c-.003 5.45-4.437 9.884-9.885 9.884m8.413-18.297A11.815 11.815 0 0012.05 0C5.495 0 .16 5.335.157 11.892c0 2.096.547 4.142 1.588 5.945L.057 24l6.305-1.654a11.882 11.882 0 005.683 1.448h.005c6.554 0 11.89-5.335 11.893-11.893a11.821 11.821 0 00-3.48-8.413Z' },
  { name: 'Facebook', hex: '#0866FF', path: 'M9.101 23.691v-7.98H6.627v-3.667h2.474v-1.58c0-4.085 1.848-5.978 5.858-5.978.401 0 .955.042 1.468.103a8.68 8.68 0 0 1 1.141.195v3.325a8.623 8.623 0 0 0-.653-.036 26.805 26.805 0 0 0-.733-.009c-.707 0-1.259.096-1.675.309a1.686 1.686 0 0 0-.679.622c-.258.42-.374.995-.374 1.752v1.297h3.919l-.386 2.103-.287 1.564h-3.246v8.245C19.396 23.238 24 18.179 24 12.044c0-6.627-5.373-12-12-12s-12 5.373-12 12c0 5.628 3.874 10.35 9.101 11.647Z' },
  { name: 'Instagram', hex: '#FF0069', path: 'M7.0301.084c-1.2768.0602-2.1487.264-2.911.5634-.7888.3075-1.4575.72-2.1228 1.3877-.6652.6677-1.075 1.3368-1.3802 2.127-.2954.7638-.4956 1.6365-.552 2.914-.0564 1.2775-.0689 1.6882-.0626 4.947.0062 3.2586.0206 3.6671.0825 4.9473.061 1.2765.264 2.1482.5635 2.9107.308.7889.72 1.4573 1.388 2.1228.6679.6655 1.3365 1.0743 2.1285 1.38.7632.295 1.6361.4961 2.9134.552 1.2773.056 1.6884.069 4.9462.0627 3.2578-.0062 3.668-.0207 4.9478-.0814 1.28-.0607 2.147-.2652 2.9098-.5633.7889-.3086 1.4578-.72 2.1228-1.3881.665-.6682 1.0745-1.3378 1.3795-2.1284.2957-.7632.4966-1.636.552-2.9124.056-1.2809.0692-1.6898.063-4.948-.0063-3.2583-.021-3.6668-.0817-4.9465-.0607-1.2797-.264-2.1487-.5633-2.9117-.3084-.7889-.72-1.4568-1.3876-2.1228C21.2982 1.33 20.628.9208 19.8378.6165 19.074.321 18.2017.1197 16.9244.0645 15.6471.0093 15.236-.005 11.977.0014 8.718.0076 8.31.0215 7.0301.0839m.1402 21.6932c-1.17-.0509-1.8053-.2453-2.2287-.408-.5606-.216-.96-.4771-1.3819-.895-.422-.4178-.6811-.8186-.9-1.378-.1644-.4234-.3624-1.058-.4171-2.228-.0595-1.2645-.072-1.6442-.079-4.848-.007-3.2037.0053-3.583.0607-4.848.05-1.169.2456-1.805.408-2.2282.216-.5613.4762-.96.895-1.3816.4188-.4217.8184-.6814 1.3783-.9003.423-.1651 1.0575-.3614 2.227-.4171 1.2655-.06 1.6447-.072 4.848-.079 3.2033-.007 3.5835.005 4.8495.0608 1.169.0508 1.8053.2445 2.228.408.5608.216.96.4754 1.3816.895.4217.4194.6816.8176.9005 1.3787.1653.4217.3617 1.056.4169 2.2263.0602 1.2655.0739 1.645.0796 4.848.0058 3.203-.0055 3.5834-.061 4.848-.051 1.17-.245 1.8055-.408 2.2294-.216.5604-.4763.96-.8954 1.3814-.419.4215-.8181.6811-1.3783.9-.4224.1649-1.0577.3617-2.2262.4174-1.2656.0595-1.6448.072-4.8493.079-3.2045.007-3.5825-.006-4.848-.0608M16.953 5.5864A1.44 1.44 0 1 0 18.39 4.144a1.44 1.44 0 0 0-1.437 1.4424M5.8385 12.012c.0067 3.4032 2.7706 6.1557 6.173 6.1493 3.4026-.0065 6.157-2.7701 6.1506-6.1733-.0065-3.4032-2.771-6.1565-6.174-6.1498-3.403.0067-6.156 2.771-6.1496 6.1738M8 12.0077a4 4 0 1 1 4.008 3.9921A3.9996 3.9996 0 0 1 8 12.0077' },
  { name: 'Threads', hex: '#000000', path: 'M12.186 24h-.007c-3.581-.024-6.334-1.205-8.184-3.509C2.35 18.44 1.5 15.586 1.472 12.01v-.017c.03-3.579.879-6.43 2.525-8.482C5.845 1.205 8.6.024 12.18 0h.014c2.746.02 5.043.725 6.826 2.098 1.677 1.29 2.858 3.13 3.509 5.467l-2.04.569c-1.104-3.96-3.898-5.984-8.304-6.015-2.91.022-5.11.936-6.54 2.717C4.307 6.504 3.616 8.914 3.589 12c.027 3.086.718 5.496 2.057 7.164 1.43 1.783 3.631 2.698 6.54 2.717 2.623-.02 4.358-.631 5.8-2.045 1.647-1.613 1.618-3.593 1.09-4.798-.31-.71-.873-1.3-1.634-1.75-.192 1.352-.622 2.446-1.284 3.272-.886 1.102-2.14 1.704-3.73 1.79-1.202.065-2.361-.218-3.259-.801-1.063-.689-1.685-1.74-1.752-2.964-.065-1.19.408-2.285 1.33-3.082.88-.76 2.119-1.207 3.583-1.291a13.853 13.853 0 0 1 3.02.142c-.126-.742-.375-1.332-.75-1.757-.513-.586-1.308-.883-2.359-.89h-.029c-.844 0-1.992.232-2.721 1.32L7.734 7.847c.98-1.454 2.568-2.256 4.478-2.256h.044c3.194.02 5.097 1.975 5.287 5.388.108.046.216.094.321.142 1.49.7 2.58 1.761 3.154 3.07.797 1.82.871 4.79-1.548 7.158-1.85 1.81-4.094 2.628-7.277 2.65Zm1.003-11.69c-.242 0-.487.007-.739.021-1.836.103-2.98.946-2.916 2.143.067 1.256 1.452 1.839 2.784 1.767 1.224-.065 2.818-.543 3.086-3.71a10.5 10.5 0 0 0-2.215-.221z' },
  { name: 'TikTok', hex: '#000000', path: 'M12.525.02c1.31-.02 2.61-.01 3.91-.02.08 1.53.63 3.09 1.75 4.17 1.12 1.11 2.7 1.62 4.24 1.79v4.03c-1.44-.05-2.89-.35-4.2-.97-.57-.26-1.1-.59-1.62-.93-.01 2.92.01 5.84-.02 8.75-.08 1.4-.54 2.79-1.35 3.94-1.31 1.92-3.58 3.17-5.91 3.21-1.43.08-2.86-.31-4.08-1.03-2.02-1.19-3.44-3.37-3.65-5.71-.02-.5-.03-1-.01-1.49.18-1.9 1.12-3.72 2.58-4.96 1.66-1.44 3.98-2.13 6.15-1.72.02 1.48-.04 2.96-.04 4.44-.99-.32-2.15-.23-3.02.37-.63.41-1.11 1.04-1.36 1.75-.21.51-.15 1.07-.14 1.61.24 1.64 1.82 3.02 3.5 2.87 1.12-.01 2.19-.66 2.77-1.61.19-.33.4-.67.41-1.06.1-1.79.06-3.57.07-5.36.01-4.03-.01-8.05.02-12.07z' },
  { name: 'YouTube', hex: '#FF0000', path: 'M23.498 6.186a3.016 3.016 0 0 0-2.122-2.136C19.505 3.545 12 3.545 12 3.545s-7.505 0-9.377.505A3.017 3.017 0 0 0 .502 6.186C0 8.07 0 12 0 12s0 3.93.502 5.814a3.016 3.016 0 0 0 2.122 2.136c1.871.505 9.376.505 9.376.505s7.505 0 9.377-.505a3.015 3.015 0 0 0 2.122-2.136C24 15.93 24 12 24 12s0-3.93-.502-5.814zM9.545 15.568V8.432L15.818 12l-6.273 3.568z' },
  { name: 'Reddit', hex: '#FF4500', path: 'M12 0C5.373 0 0 5.373 0 12c0 3.314 1.343 6.314 3.515 8.485l-2.286 2.286C.775 23.225 1.097 24 1.738 24H12c6.627 0 12-5.373 12-12S18.627 0 12 0Zm4.388 3.199c1.104 0 1.999.895 1.999 1.999 0 1.105-.895 2-1.999 2-.946 0-1.739-.657-1.947-1.539v.002c-1.147.162-2.032 1.15-2.032 2.341v.007c1.776.067 3.4.567 4.686 1.363.473-.363 1.064-.58 1.707-.58 1.547 0 2.802 1.254 2.802 2.802 0 1.117-.655 2.081-1.601 2.531-.088 3.256-3.637 5.876-7.997 5.876-4.361 0-7.905-2.617-7.998-5.87-.954-.447-1.614-1.415-1.614-2.538 0-1.548 1.255-2.802 2.803-2.802.645 0 1.239.218 1.712.585 1.275-.79 2.881-1.291 4.64-1.365v-.01c0-1.663 1.263-3.034 2.88-3.207.188-.911.993-1.595 1.959-1.595Zm-8.085 8.376c-.784 0-1.459.78-1.506 1.797-.047 1.016.64 1.429 1.426 1.429.786 0 1.371-.369 1.418-1.385.047-1.017-.553-1.841-1.338-1.841Zm7.406 0c-.786 0-1.385.824-1.338 1.841.047 1.017.634 1.385 1.418 1.385.785 0 1.473-.413 1.426-1.429-.046-1.017-.721-1.797-1.506-1.797Zm-3.703 4.013c-.974 0-1.907.048-2.77.135-.147.015-.241.168-.183.305.483 1.154 1.622 1.964 2.953 1.964 1.33 0 2.47-.81 2.953-1.964.057-.137-.037-.29-.184-.305-.863-.087-1.795-.135-2.769-.135Z' },
  { name: 'Snapchat', hex: '#FFFC00', path: 'M12.206.793c.99 0 4.347.276 5.93 3.821.529 1.193.403 3.219.299 4.847l-.003.06c-.012.18-.022.345-.03.51.075.045.203.09.401.09.3-.016.659-.12 1.033-.301.165-.088.344-.104.464-.104.182 0 .359.029.509.09.45.149.734.479.734.838.015.449-.39.839-1.213 1.168-.089.029-.209.075-.344.119-.45.135-1.139.36-1.333.81-.09.224-.061.524.12.868l.015.015c.06.136 1.526 3.475 4.791 4.014.255.044.435.27.42.509 0 .075-.015.149-.045.225-.24.569-1.273.988-3.146 1.271-.059.091-.12.375-.164.57-.029.179-.074.36-.134.553-.076.271-.27.405-.555.405h-.03c-.135 0-.313-.031-.538-.074-.36-.075-.765-.135-1.273-.135-.3 0-.599.015-.913.074-.6.104-1.123.464-1.723.884-.853.599-1.826 1.288-3.294 1.288-.06 0-.119-.015-.18-.015h-.149c-1.468 0-2.427-.675-3.279-1.288-.599-.42-1.107-.779-1.707-.884-.314-.045-.629-.074-.928-.074-.54 0-.958.089-1.272.149-.211.043-.391.074-.54.074-.374 0-.523-.224-.583-.42-.061-.192-.09-.389-.135-.567-.046-.181-.105-.494-.166-.57-1.918-.222-2.95-.642-3.189-1.226-.031-.063-.052-.15-.055-.225-.015-.243.165-.465.42-.509 3.264-.54 4.73-3.879 4.791-4.02l.016-.029c.18-.345.224-.645.119-.869-.195-.434-.884-.658-1.332-.809-.121-.029-.24-.074-.346-.119-1.107-.435-1.257-.93-1.197-1.273.09-.479.674-.793 1.168-.793.146 0 .27.029.383.074.42.194.789.3 1.104.3.234 0 .384-.06.465-.105l-.046-.569c-.098-1.626-.225-3.651.307-4.837C7.392 1.077 10.739.807 11.727.807l.419-.015h.06z' },
  { name: 'LinkedIn', hex: '#0A66C2', path: 'M20.447 20.452h-3.554v-5.569c0-1.328-.027-3.037-1.852-3.037-1.853 0-2.136 1.445-2.136 2.939v5.667H9.351V9h3.414v1.561h.046c.477-.9 1.637-1.85 3.37-1.85 3.601 0 4.267 2.37 4.267 5.455v6.286zM5.337 7.433c-1.144 0-2.063-.926-2.063-2.065 0-1.138.92-2.063 2.063-2.063 1.14 0 2.064.925 2.064 2.063 0 1.139-.925 2.065-2.064 2.065zm1.782 13.019H3.555V9h3.564v11.452zM22.225 0H1.771C.792 0 0 .774 0 1.729v20.542C0 23.227.792 24 1.771 24h20.451C23.2 24 24 23.227 24 22.271V1.729C24 .774 23.2 0 22.225 0z' },
  { name: 'GitHub', hex: '#181717', path: 'M12 .297c-6.63 0-12 5.373-12 12 0 5.303 3.438 9.8 8.205 11.385.6.113.82-.258.82-.577 0-.285-.01-1.04-.015-2.04-3.338.724-4.042-1.61-4.042-1.61C4.422 18.07 3.633 17.7 3.633 17.7c-1.087-.744.084-.729.084-.729 1.205.084 1.838 1.236 1.838 1.236 1.07 1.835 2.809 1.305 3.495.998.108-.776.417-1.305.76-1.605-2.665-.3-5.466-1.332-5.466-5.93 0-1.31.465-2.38 1.235-3.22-.135-.303-.54-1.523.105-3.176 0 0 1.005-.322 3.3 1.23.96-.267 1.98-.399 3-.405 1.02.006 2.04.138 3 .405 2.28-1.552 3.285-1.23 3.285-1.23.645 1.653.24 2.873.12 3.176.765.84 1.23 1.91 1.23 3.22 0 4.61-2.805 5.625-5.475 5.92.42.36.81 1.096.81 2.22 0 1.606-.015 2.896-.015 3.286 0 .315.21.69.825.57C20.565 22.092 24 17.592 24 12.297c0-6.627-5.373-12-12-12' },
  { name: 'Mastodon', hex: '#6364FF', path: 'M23.268 5.313c-.35-2.578-2.617-4.61-5.304-5.004C17.51.242 15.792 0 11.813 0h-.03c-3.98 0-4.835.242-5.288.309C3.882.692 1.496 2.518.917 5.127.64 6.412.61 7.837.661 9.143c.074 1.874.088 3.745.26 5.611.118 1.24.325 2.47.62 3.68.55 2.237 2.777 4.098 4.96 4.857 2.336.792 4.849.923 7.256.38.265-.061.527-.132.786-.213.585-.184 1.27-.39 1.774-.753a.057.057 0 0 0 .023-.043v-1.809a.052.052 0 0 0-.02-.041.053.053 0 0 0-.046-.01 20.282 20.282 0 0 1-4.709.545c-2.73 0-3.463-1.284-3.674-1.818a5.593 5.593 0 0 1-.319-1.433.053.053 0 0 1 .066-.054c1.517.363 3.072.546 4.632.546.376 0 .75 0 1.125-.01 1.57-.044 3.224-.124 4.768-.422.038-.008.077-.015.11-.024 2.435-.464 4.753-1.92 4.989-5.604.008-.145.03-1.52.03-1.67.002-.512.167-3.63-.024-5.545zm-3.748 9.195h-2.561V8.29c0-1.309-.55-1.976-1.67-1.976-1.23 0-1.846.79-1.846 2.35v3.403h-2.546V8.663c0-1.56-.617-2.35-1.848-2.35-1.112 0-1.668.668-1.67 1.977v6.218H4.822V8.102c0-1.31.337-2.35 1.011-3.12.696-.77 1.608-1.164 2.74-1.164 1.311 0 2.302.5 2.962 1.498l.638 1.06.638-1.06c.66-.999 1.65-1.498 2.96-1.498 1.13 0 2.043.395 2.74 1.164.675.77 1.012 1.81 1.012 3.12z' },
  { name: 'Bluesky', hex: '#1185FE', path: 'M5.202 2.857C7.954 4.922 10.913 9.11 12 11.358c1.087-2.247 4.046-6.436 6.798-8.501C20.783 1.366 24 .213 24 3.883c0 .732-.42 6.156-.667 7.037-.856 3.061-3.978 3.842-6.755 3.37 4.854.826 6.089 3.562 3.422 6.299-5.065 5.196-7.28-1.304-7.847-2.97-.104-.305-.152-.448-.153-.327 0-.121-.05.022-.153.327-.568 1.666-2.782 8.166-7.847 2.97-2.667-2.737-1.432-5.473 3.422-6.3-2.777.473-5.899-.308-6.755-3.369C.42 10.04 0 4.615 0 3.883c0-3.67 3.217-2.517 5.202-1.026' },
  { name: 'Twitch', hex: '#9146FF', path: 'M11.571 4.714h1.715v5.143H11.57zm4.715 0H18v5.143h-1.714zM6 0L1.714 4.286v15.428h5.143V24l4.286-4.286h3.428L22.286 12V0zm14.571 11.143l-3.428 3.428h-3.429l-3 3v-3H6.857V1.714h13.714Z' },
  { name: 'Medium', hex: '#000000', path: 'M13.54 12a6.8 6.8 0 01-6.77 6.82A6.8 6.8 0 010 12a6.8 6.8 0 016.77-6.82A6.8 6.8 0 0113.54 12zM20.96 12c0 3.54-1.51 6.42-3.38 6.42-1.87 0-3.39-2.88-3.39-6.42s1.52-6.42 3.39-6.42 3.38 2.88 3.38 6.42M24 12c0 3.17-.53 5.75-1.19 5.75-.66 0-1.19-2.58-1.19-5.75s.53-5.75 1.19-5.75C23.47 6.25 24 8.83 24 12z' },
  { name: 'Keybase', hex: '#33A0FF', path: 'M10.445 21.372a.953.953 0 1 1-.955-.954c.524 0 .951.43.951.955m5.923-.001a.953.953 0 1 1-.958-.954c.526 0 .954.43.954.955m4.544-9.16l-.156-.204c-.046-.06-.096-.116-.143-.175-.045-.06-.094-.113-.141-.169-.104-.12-.21-.239-.32-.359l-.075-.08-.091-.099-.135-.13c-.015-.019-.032-.035-.05-.054a10.87 10.87 0 0 0-3.955-2.504l-.23-.078.035-.083a4.109 4.109 0 0 0-.12-3.255 4.11 4.11 0 0 0-2.438-2.16c-.656-.216-1.23-.319-1.712-.305-.033-.105-.1-.577.496-1.848L10.662 0l-.287.399c-.33.455-.648.895-.945 1.328a1.857 1.857 0 0 0-1.245-.58L6.79 1.061h-.012c-.033-.003-.07-.003-.104-.003-.99 0-1.81.771-1.87 1.755l-.088 1.402v.003a1.876 1.876 0 0 0 1.755 1.98l1.002.06c-.065.84.073 1.62.405 2.306a11.28 11.28 0 0 0-3.66 2.484C.912 14.392.912 18.052.912 20.995v1.775l1.305-1.387c.266.93.652 1.807 1.145 2.615H5.06a9.197 9.197 0 0 1-1.68-3.848l1.913-2.03-.985 3.09 1.74-1.267c3.075-2.234 6.745-2.75 10.91-1.53 1.806.533 3.56.04 4.474-1.256l.104-.165c.09.498.14.998.14 1.496 0 1.563-.254 3.687-1.38 5.512h1.612c.776-1.563 1.181-3.432 1.181-5.512-.001-2.2-.786-4.421-2.184-6.274zM8.894 6.192c.122-1.002.577-1.949 1.23-2.97a1.36 1.36 0 0 0 1.283.749c.216-.008.604.025 1.233.232a2.706 2.706 0 0 1 1.608 1.425c.322.681.349 1.442.079 2.15a2.69 2.69 0 0 1-.806 1.108l-.408-.502-.002-.003a1.468 1.468 0 0 0-2.06-.205c-.334.27-.514.66-.534 1.058-1.2-.54-1.8-1.643-1.628-3.04zm4.304 5.11l-.52.425a.228.228 0 0 1-.323-.032l-.11-.135a.238.238 0 0 1 .034-.334l.51-.42-1.056-1.299a.307.307 0 0 1 .044-.436.303.303 0 0 1 .435.041l2.963 3.646a.309.309 0 0 1-.168.499.315.315 0 0 1-.31-.104l-.295-.365-1.045.854a.244.244 0 0 1-.154.055.237.237 0 0 1-.186-.09l-.477-.58a.24.24 0 0 1 .035-.335l1.05-.858-.425-.533zM7.752 4.866l-1.196-.075a.463.463 0 0 1-.435-.488l.09-1.4a.462.462 0 0 1 .461-.437h.024l1.401.091a.459.459 0 0 1 .433.488l-.007.101a9.27 9.27 0 0 0-.773 1.72zm12.525 11.482c-.565.805-1.687 1.08-2.924.718-3.886-1.141-7.397-.903-10.469.7l1.636-5.122-5.29 5.609c.098-3.762 2.452-6.967 5.757-8.312.471.373 1.034.66 1.673.841.16.044.322.074.48.102a1.41 1.41 0 0 0 .21 1.408l.075.09c-.172.45-.105.975.221 1.374l.476.582a1.39 1.39 0 0 0 1.079.513c.32 0 .635-.111.886-.314l.285-.232c.174.074.367.113.566.113a1.45 1.45 0 0 0 .928-.326c.623-.51.72-1.435.209-2.06l-1.67-2.057a4.07 4.07 0 0 0 .408-.38c.135.036.27.077.4.12.266.096.533.197.795.314a9.55 9.55 0 0 1 2.77 1.897c.03.03.06.055.086.083l.17.176c.038.039.076.079.11.12.08.085.16.175.24.267l.126.15c.045.053.086.104.13.16l.114.15c.04.05.079.102.117.154.838 1.149.987 2.329.404 3.157v.005zM7.718 4.115l-.835-.05.053-.836.834.051z' },
  { name: 'Steam', hex: '#111111', path: 'M11.979 0C5.678 0 .511 4.86.022 11.037l6.432 2.658c.545-.371 1.203-.59 1.912-.59.063 0 .125.004.188.006l2.861-4.142V8.91c0-2.495 2.028-4.524 4.524-4.524 2.494 0 4.524 2.031 4.524 4.527s-2.03 4.525-4.524 4.525h-.105l-4.076 2.911c0 .052.004.105.004.159 0 1.875-1.515 3.396-3.39 3.396-1.635 0-3.016-1.173-3.331-2.727L.436 15.27C1.862 20.307 6.486 24 11.979 24c6.627 0 11.999-5.373 11.999-12S18.605 0 11.979 0zM7.54 18.21l-1.473-.61c.262.543.714.999 1.314 1.25 1.297.539 2.793-.076 3.332-1.375.263-.63.264-1.319.005-1.949s-.75-1.121-1.377-1.383c-.624-.26-1.29-.249-1.878-.03l1.523.63c.956.4 1.409 1.5 1.009 2.455-.397.957-1.497 1.41-2.454 1.012H7.54zm11.415-9.303c0-1.662-1.353-3.015-3.015-3.015-1.665 0-3.015 1.353-3.015 3.015 0 1.665 1.35 3.015 3.015 3.015 1.663 0 3.015-1.35 3.015-3.015zm-5.273-.005c0-1.252 1.013-2.266 2.265-2.266 1.249 0 2.266 1.014 2.266 2.266 0 1.251-1.017 2.265-2.266 2.265-1.253 0-2.265-1.014-2.265-2.265z' },
]
function glyphColor(hex: string): string {
  const c = hex.replace('#', '')
  const r = parseInt(c.slice(0, 2), 16), g = parseInt(c.slice(2, 4), 16), b = parseInt(c.slice(4, 6), 16)
  const lum = 0.2126 * r + 0.7152 * g + 0.0722 * b
  return lum < 45 ? '#d1d5db' : hex   // brighten near-black marks on the dark UI
}
function BrandGlyph({ path, color, size = 16 }: { path: string; color: string; size?: number }) {
  return (
    <svg viewBox="0 0 24 24" width={size} height={size} fill={color} aria-hidden="true">
      <path d={path} />
    </svg>
  )
}

const LEAD_META: Record<LeadStatus, { label: string; color: string }> = {
  none:      { label: 'Unassessed', color: '#5b6b83' },
  suspect:   { label: 'Suspect',    color: '#f59e0b' },
  confirmed: { label: 'Confirmed',  color: '#ef4444' },
  cleared:   { label: 'Cleared',    color: '#22c55e' },
  poi:       { label: 'Person of interest', color: '#a855f7' },
}

// ── Professional corporate theme constants ─────────────────────────────────
// Unified palette aligned with NexusEdgeLayer + riskPalette + the app's
// de-purpled graphite theme. Replaces scattered hardcoded Apple-system colors.
const THEME = {
  // Corporate edge colors (aligned with NexusEdgeLayer)
  edgeInflow: '#10b981',       // emerald — incoming funds
  edgeOutflow: '#f59e0b',      // amber — outgoing funds
  edgeCrossChain: '#38bdf8',   // sky — bridge/cross-chain
  edgeRelationship: '#ef4444', // crimson — relationship "red string"
  edgeDefault: '#3b4252',      // graphite — default fund flow
  edgeManual: '#6b7280',       // gray — manually drawn
  // Selection (graphite-bright, not Apple blue)
  selected: '#96a1b5',
  // Text
  textPrimary: '#e2e2e6',
  textSecondary: '#96969e',
  textMuted: '#6c6c76',
  // Node fills (professional graphite — not hardcoded dark)
  cardFill: 'rgb(27 27 30 / 0.95)',
  cardFillLight: 'rgb(245 245 247 / 0.97)',
  cardStroke: 'rgb(52 52 58)',
  // Pills & labels
  pillBg: 'rgb(15 15 17 / 0.92)',
  pillBgCrimson: '#1a0d10',
  pillBgSky: '#0a1520',
}

// Helper to detect light mode at render time (matches GraphNodeKit's useIsLight).
function useIsLightMode(): boolean {
  try {
    return document.documentElement.classList.contains('light')
  } catch {
    return false
  }
}

// ── Responsive text layout for annotation/notes nodes ─────────────────────
// Word-wraps text into lines that fit within a max pixel width, and computes
// the bounding box so the note rectangle grows/shrinks to fit the content.
const NOTE_CHAR_W = 5.4    // approx px per character at fontSize 9
const NOTE_LINE_H = 13     // px line height
const NOTE_PAD_X = 14      // horizontal padding inside the note
const NOTE_PAD_TOP = 26    // space reserved for the title bar + label
const NOTE_PAD_BOTTOM = 10
const NOTE_MIN_W = 120     // minimum note width
const NOTE_MAX_W = 320     // cap so a giant note doesn't fill the screen

function wrapText(text: string, maxCharsPerLine: number): string[] {
  const lines: string[] = []
  for (const rawLine of text.split('\n')) {
    const words = rawLine.split(/\s+/).filter(Boolean)
    if (!words.length) { lines.push(''); continue }
    let current = ''
    for (const word of words) {
      const candidate = current ? current + ' ' + word : word
      if (candidate.length <= maxCharsPerLine) {
        current = candidate
      } else {
        if (current) lines.push(current)
        // If a single word is longer than the line, hard-break it.
        if (word.length > maxCharsPerLine) {
          for (let i = 0; i < word.length; i += maxCharsPerLine) {
            lines.push(word.slice(i, i + maxCharsPerLine))
          }
          current = ''
        } else {
          current = word
        }
      }
    }
    if (current) lines.push(current)
  }
  return lines
}

function computeNoteLayout(label: string, body: string): { width: number; height: number; lines: string[] } {
  // Determine a content width based on the longest word so we don't overflow.
  const longestWord = Math.max(label.length, ...body.split(/\s+/).map(w => w.length), 10)
  let contentWidth = Math.max(longestWord * NOTE_CHAR_W + NOTE_PAD_X * 2, NOTE_MIN_W)
  contentWidth = Math.min(contentWidth, NOTE_MAX_W)
  const innerWidth = contentWidth - NOTE_PAD_X * 2
  const maxChars = Math.floor(innerWidth / NOTE_CHAR_W)
  const lines = wrapText(body, maxChars)
  const height = NOTE_PAD_TOP + lines.length * NOTE_LINE_H + NOTE_PAD_BOTTOM
  return { width: contentWidth, height, lines }
}

const REL_LABEL: Record<string, string> = {
  controls: 'controls', same_owner: 'same owner', kyc_match: 'KYC match',
  communicates: 'communicates', funds: 'funds', associates: 'associates',
  employs: 'employs', registered_to: 'registered to', ip_overlap: 'IP overlap',
  device_match: 'device match', custom: 'custom',
}

const ZONE_COLORS = ['#5b9fd6', '#d4a843', '#ef4444', '#10b981', '#8b80d4', '#f59e0b']

// ── component ─────────────────────────────────────────────────────────────────

type Menu = { x: number; y: number; nodeId?: string; edgeId?: string; zoneId?: string }
type Mode = 'select' | 'link' | 'zone'
type DragState =
  | { type: 'node'; id: string; startX: number; startY: number; orig: Map<string, { x: number; y: number }> }
  | { type: 'pan'; startX: number; startY: number; origVx: number; origVy: number }
  | { type: 'band'; startX: number; startY: number; curX: number; curY: number }
  | { type: 'zone'; id: string; startX: number; startY: number; origX: number; origY: number }
  | { type: 'zoneResize'; id: string; startX: number; startY: number; origW: number; origH: number }
  | { type: 'zoneDraw'; startX: number; startY: number; curX: number; curY: number }

type HistSnap = { nodes: BoardNode[]; edges: BoardEdge[]; clusters: BoardState['clusters']; zones: BoardZone[] }

export default function BoardCanvas() {
  const { t } = useTranslation()
  const { id = '' } = useParams()
  const navigate = useNavigate()
  const svgRef = useRef<SVGSVGElement>(null)

  const [board, setBoard] = useState<Board | null>(null)
  const [st, setSt] = useState<BoardState>(EMPTY_BOARD_STATE)
  const stRef = useRef(st)
  stRef.current = st
  const [loadError, setLoadError] = useState('')
  const [saveState, setSaveState] = useState<'saved' | 'saving' | 'dirty' | 'error'>('saved')
  const saveTimer = useRef<number>()

  const [selection, setSelection] = useState<Set<string>>(new Set())
  const [drag, setDrag] = useState<DragState | null>(null)
  const [menu, setMenu] = useState<Menu | null>(null)
  const [busy, setBusy] = useState('')

  const [mode, setMode] = useState<Mode>('select')
  const [linkFrom, setLinkFrom] = useState<string>('')
  const [cursor, setCursor] = useState<{ x: number; y: number } | null>(null)

  const [addValue, setAddValue] = useState('')
  const [showShare, setShowShare] = useState(false)
  const [showComments, setShowComments] = useState(false)
  const [showEntityMenu, setShowEntityMenu] = useState(false)
  const [showLayoutMenu, setShowLayoutMenu] = useState(false)
  const [showLegend, setShowLegend] = useState(false)
  const [shares, setShares] = useState<BoardShare[]>([])
  const [comments, setComments] = useState<BoardComment[]>([])
  const [shareMode, setShareMode] = useState<'public' | 'private'>('public')
  const [sharePassword, setSharePassword] = useState('')
  const [shareLive, setShareLive] = useState(true)
  const [shareExpiry, setShareExpiry] = useState(0)
  const [newShare, setNewShare] = useState<BoardShare | null>(null)
  const [copied, setCopied] = useState('')
  const [commentBody, setCommentBody] = useState('')
  const [clusterName, setClusterName] = useState('')
  const [namingCluster, setNamingCluster] = useState(false)
  const [links, setLinks] = useState<BoardLink[]>([])
  const [searchQ, setSearchQ] = useState('')
  const [matchIdx, setMatchIdx] = useState(0)
  const [attrK, setAttrK] = useState('')
  const [attrV, setAttrV] = useState('')
  const [histVer, setHistVer] = useState(0) // re-render trigger for undo/redo buttons

  // ── undo / redo history ─────────────────────────────────────────────────────
  const history = useRef<{ past: HistSnap[]; future: HistSnap[] }>({ past: [], future: [] })
  const capture = useCallback((): HistSnap => {
    const s = stRef.current
    return { nodes: s.nodes, edges: s.edges, clusters: s.clusters, zones: s.zones || [] }
  }, [])
  const pushHistory = useCallback(() => {
    const h = history.current
    h.past.push(capture())
    if (h.past.length > 60) h.past.shift()
    h.future = []
    setHistVer((v) => v + 1)
  }, [capture])

  // ── load ────────────────────────────────────────────────────────────────────
  useEffect(() => {
    getBoard(id)
      .then((b) => {
        setBoard(b)
        setSt({
          ...EMPTY_BOARD_STATE, ...b.state,
          zones: b.state?.zones || [],
          preferences: { ...EMPTY_BOARD_STATE.preferences, ...(b.state?.preferences || {}) },
        })
      })
      .catch((e) => setLoadError(e?.response?.data?.detail || t('tools:boardCanvas.loadFailed')))
    boardLinks(id).then(setLinks).catch(() => setLinks([]))
  }, [id])

  // ── autosave ────────────────────────────────────────────────────────────────
  const scheduleSave = useCallback(() => {
    setSaveState('dirty')
    window.clearTimeout(saveTimer.current)
    saveTimer.current = window.setTimeout(async () => {
      setSaveState('saving')
      try {
        const meta = await updateBoard(id, { state: stRef.current })
        setBoard((b) => (b ? { ...b, version: meta.version, state_hash: meta.state_hash, updated_at: meta.updated_at } : b))
        setSaveState('saved')
      } catch {
        setSaveState('error')
      }
    }, 1200)
  }, [id])

  /** history-tracked structural mutation */
  const mutate = useCallback((fn: (s: BoardState) => BoardState) => {
    pushHistory()
    setSt((s) => fn(s))
    scheduleSave()
  }, [scheduleSave, pushHistory])

  /** untracked mutation (viewport / price fills) */
  const mutateQuiet = useCallback((fn: (s: BoardState) => BoardState) => {
    setSt((s) => fn(s))
    scheduleSave()
  }, [scheduleSave])

  const undo = useCallback(() => {
    const h = history.current
    if (!h.past.length) return
    h.future.push(capture())
    const snap = h.past.pop()!
    setSt((s) => ({ ...s, ...snap }))
    setHistVer((v) => v + 1)
    scheduleSave()
  }, [capture, scheduleSave])

  const redo = useCallback(() => {
    const h = history.current
    if (!h.future.length) return
    h.past.push(capture())
    const snap = h.future.pop()!
    setSt((s) => ({ ...s, ...snap }))
    setHistVer((v) => v + 1)
    scheduleSave()
  }, [capture, scheduleSave])

  useEffect(() => () => window.clearTimeout(saveTimer.current), [])

  // ── derived: collapsed-cluster remapping ────────────────────────────────────
  const { visibleNodes, visibleEdges } = useMemo(() => {
    const hidden = new Map<string, string>()
    for (const c of st.clusters) {
      if (!c.collapsed) continue
      for (const m of c.members) hidden.set(m, c.id)
    }
    const nodes = st.nodes.filter((n) => !hidden.has(n.id))
    const seen = new Set<string>()
    const edges: BoardEdge[] = []
    for (const e of st.edges) {
      const s = hidden.get(e.source) || e.source
      const t = hidden.get(e.target) || e.target
      if (s === t) continue
      const k = `${s}|${t}|${e.asset}|${e.txHash}|${e.relationship || ''}`
      if (seen.has(k)) continue
      seen.add(k)
      edges.push(s === e.source && t === e.target ? e : { ...e, source: s, target: t })
    }
    return { visibleNodes: nodes, visibleEdges: edges }
  }, [st.nodes, st.edges, st.clusters])

  const nodeById = useMemo(() => new Map(st.nodes.map((n) => [n.id, n])), [st.nodes])
  const zones = st.zones || []

  // ── canvas search ───────────────────────────────────────────────────────────
  const matches = useMemo(() => {
    const q = searchQ.trim().toLowerCase()
    if (!q) return []
    return st.nodes.filter((n) =>
      n.ref.toLowerCase().includes(q) || n.label.toLowerCase().includes(q)
      || n.caption.toLowerCase().includes(q) || (n.note || '').toLowerCase().includes(q))
  }, [searchQ, st.nodes])
  const matchIds = useMemo(() => new Set(matches.map((m) => m.id)), [matches])

  const centerOn = useCallback((x: number, y: number) => {
    const rect = svgRef.current?.getBoundingClientRect()
    if (!rect) return
    setSt((s) => ({ ...s, viewport: { ...s.viewport, x: rect.width / 2 - x * s.viewport.z, y: rect.height / 2 - y * s.viewport.z } }))
    scheduleSave()
  }, [scheduleSave])

  function jumpToMatch(idx: number) {
    if (!matches.length) return
    const i = ((idx % matches.length) + matches.length) % matches.length
    setMatchIdx(i)
    const n = matches[i]
    centerOn(n.x, n.y)
    setSelection(new Set([n.id]))
  }

  // ── coordinate transforms ───────────────────────────────────────────────────
  const view = st.viewport
  const toWorld = useCallback((cx: number, cy: number) => {
    const rect = svgRef.current?.getBoundingClientRect()
    if (!rect) return { x: 0, y: 0 }
    return { x: (cx - rect.left - view.x) / view.z, y: (cy - rect.top - view.y) / view.z }
  }, [view])

  const centerWorld = useCallback(() => {
    const rect = svgRef.current?.getBoundingClientRect()
    if (!rect) return { x: 300, y: 240 }
    return toWorld(rect.left + rect.width / 2, rect.top + rect.height / 2)
  }, [toWorld])

  // ── layouts ─────────────────────────────────────────────────────────────────
  const fitView = useCallback(() => {
    const rect = svgRef.current?.getBoundingClientRect()
    const ns = stRef.current.nodes
    if (!rect || !ns.length) return
    const xs = ns.map((n) => n.x); const ys = ns.map((n) => n.y)
    const minX = Math.min(...xs) - 140; const maxX = Math.max(...xs) + 140
    const minY = Math.min(...ys) - 110; const maxY = Math.max(...ys) + 110
    const z = Math.max(0.15, Math.min(2.2, Math.min(rect.width / (maxX - minX), rect.height / (maxY - minY))))
    setSt((s) => ({ ...s, viewport: { x: rect.width / 2 - z * (minX + maxX) / 2, y: rect.height / 2 - z * (minY + maxY) / 2, z } }))
    scheduleSave()
  }, [scheduleSave])

  function runForceLayout() {
    setShowLayoutMenu(false)
    const s = stRef.current
    if (s.nodes.length < 2) return
    pushHistory()
    const pos = s.nodes.map((n) => ({ id: n.id, x: n.x + (Math.random() - 0.5), y: n.y + (Math.random() - 0.5) }))
    const idx = new Map(pos.map((p, i) => [p.id, i]))
    const springs = s.edges
      .map((e) => [idx.get(e.source), idx.get(e.target)] as [number | undefined, number | undefined])
      .filter((p): p is [number, number] => p[0] != null && p[1] != null && p[0] !== p[1])
    const N = pos.length
    for (let it = 0; it < 200; it++) {
      const t = 1 - it / 200
      const fx = new Array(N).fill(0); const fy = new Array(N).fill(0)
      for (let i = 0; i < N; i++) {
        for (let j = i + 1; j < N; j++) {
          let dx = pos[i].x - pos[j].x; let dy = pos[i].y - pos[j].y
          const d2 = Math.max(140, dx * dx + dy * dy)
          const f = 42000 / d2
          const d = Math.sqrt(d2)
          dx /= d; dy /= d
          fx[i] += dx * f; fy[i] += dy * f
          fx[j] -= dx * f; fy[j] -= dy * f
        }
      }
      for (const [a, b] of springs) {
        const dx = pos[b].x - pos[a].x; const dy = pos[b].y - pos[a].y
        const d = Math.max(1, Math.sqrt(dx * dx + dy * dy))
        // Hooke's-law spring: force magnitude proportional to (d - restLength),
        // applied along the unit vector toward the partner. (Previous code
        // multiplied by `d` a second time, making the spring scale with distance
        // and producing unstable layouts on larger boards.)
        const restLength = 200
        const f = (d - restLength) * 0.06
        const ux = dx / d, uy = dy / d
        fx[a] += ux * f; fy[a] += uy * f
        fx[b] -= ux * f; fy[b] -= uy * f
      }
      // gentle gravity toward centroid
      const cx0 = pos.reduce((a, p) => a + p.x, 0) / N
      const cy0 = pos.reduce((a, p) => a + p.y, 0) / N
      for (let i = 0; i < N; i++) {
        fx[i] += (cx0 - pos[i].x) * 0.004; fy[i] += (cy0 - pos[i].y) * 0.004
        const cap = 22 * t + 2
        pos[i].x += Math.max(-cap, Math.min(cap, fx[i]))
        pos[i].y += Math.max(-cap, Math.min(cap, fy[i]))
      }
    }
    setSt((s2) => ({ ...s2, nodes: s2.nodes.map((n) => { const i = idx.get(n.id); return i == null ? n : { ...n, x: pos[i].x, y: pos[i].y } }) }))
    scheduleSave()
    window.setTimeout(fitView, 30)
  }

  function runTimelineLayout() {
    setShowLayoutMenu(false)
    const s = stRef.current
    const nodeTs = new Map<string, number>()
    for (const e of s.edges) {
      if (!e.ts) continue
      for (const nid of [e.source, e.target]) {
        nodeTs.set(nid, Math.min(nodeTs.get(nid) ?? Infinity, e.ts))
      }
    }
    if (nodeTs.size === 0) return
    pushHistory()
    const times = [...nodeTs.values()]
    const minT = Math.min(...times); const maxT = Math.max(...times)
    const span = Math.max(1, maxT - minT)
    const laneKey = (n: BoardNode) => (isEntity(n.kind) ? '·entities' : n.kind === 'note' ? '·notes' : (n.chain || 'other').toLowerCase())
    const laneOrder: string[] = []
    for (const n of s.nodes) { const k = laneKey(n); if (!laneOrder.includes(k)) laneOrder.push(k) }
    let undated = 0
    setSt((s2) => ({
      ...s2,
      nodes: s2.nodes.map((n) => {
        const lane = laneOrder.indexOf(laneKey(n))
        const ts = nodeTs.get(n.id)
        if (ts == null) { undated++; return { ...n, x: 40, y: 120 + (undated - 1) * 90 } }
        return { ...n, x: 220 + ((ts - minT) / span) * 1500, y: 120 + lane * 150 }
      }),
    }))
    scheduleSave()
    window.setTimeout(fitView, 30)
  }

  function runGridLayout() {
    setShowLayoutMenu(false)
    const s = stRef.current
    if (!s.nodes.length) return
    pushHistory()
    const sorted = [...s.nodes].sort((a, b) => (a.kind + a.label).localeCompare(b.kind + b.label))
    const cols = Math.max(2, Math.ceil(Math.sqrt(sorted.length)))
    const posMap = new Map(sorted.map((n, i) => [n.id, { x: 140 + (i % cols) * 200, y: 120 + Math.floor(i / cols) * 150 }]))
    setSt((s2) => ({ ...s2, nodes: s2.nodes.map((n) => { const p = posMap.get(n.id); return p ? { ...n, ...p } : n }) }))
    scheduleSave()
    window.setTimeout(fitView, 30)
  }

  function runHierarchicalLayout() {
    setShowLayoutMenu(false)
    const s = stRef.current
    if (!s.nodes.length) return
    pushHistory()
    // BFS from roots (nodes with no incoming fund-flow edge) → top-to-bottom
    // levels. Each level is spread horizontally. Useful for money-flow chains.
    const ids = new Set(s.nodes.map(n => n.id))
    const incoming = new Map<string, number>(s.nodes.map(n => [n.id, 0]))
    const children = new Map<string, string[]>(s.nodes.map(n => [n.id, [] as string[]]))
    for (const e of s.edges) {
      if (e.kind === 'relationship') continue
      if (!ids.has(e.source) || !ids.has(e.target)) continue
      incoming.set(e.target, (incoming.get(e.target) || 0) + 1)
      children.get(e.source)?.push(e.target)
    }
    const levelOf = new Map<string, number>()
    const queue: string[] = s.nodes.filter(n => (incoming.get(n.id) || 0) === 0).map(n => n.id)
    queue.forEach(id => levelOf.set(id, 0))
    // If no roots (cycles), seed from the first node
    if (!queue.length && s.nodes[0]) { queue.push(s.nodes[0].id); levelOf.set(s.nodes[0].id, 0) }
    while (queue.length) {
      const id = queue.shift()!
      const lvl = levelOf.get(id) || 0
      for (const c of (children.get(id) || [])) {
        if (!levelOf.has(c) || (levelOf.get(c) || 0) < lvl + 1) {
          levelOf.set(c, lvl + 1)
          queue.push(c)
        }
      }
    }
    // Any unreached nodes go to the last level
    const maxLevel = Math.max(0, ...Array.from(levelOf.values()))
    s.nodes.forEach(n => { if (!levelOf.has(n.id)) levelOf.set(n.id, maxLevel + 1) })
    // Group by level, then lay out columns per level
    const byLevel = new Map<number, string[]>()
    for (const n of s.nodes) {
      const lvl = levelOf.get(n.id) || 0
      if (!byLevel.has(lvl)) byLevel.set(lvl, [])
      byLevel.get(lvl)!.push(n.id)
    }
    const LEVEL_H = 200, COL_W = 220
    const posMap = new Map<string, { x: number; y: number }>()
    for (const [lvl, ns] of byLevel) {
      ns.forEach((id, i) => {
        const x = 200 + (i - (ns.length - 1) / 2) * COL_W
        const y = 120 + lvl * LEVEL_H
        posMap.set(id, { x, y })
      })
    }
    setSt((s2) => ({ ...s2, nodes: s2.nodes.map((n) => { const p = posMap.get(n.id); return p ? { ...n, ...p } : n }) }))
    scheduleSave()
    window.setTimeout(fitView, 30)
  }

  // ── PNG export ──────────────────────────────────────────────────────────────
  function exportPng() {
    const svgEl = svgRef.current
    if (!svgEl) return
    const rect = svgEl.getBoundingClientRect()
    const clone = svgEl.cloneNode(true) as SVGSVGElement
    clone.setAttribute('width', String(Math.round(rect.width)))
    clone.setAttribute('height', String(Math.round(rect.height)))
    clone.setAttribute('xmlns', 'http://www.w3.org/2000/svg')
    clone.style.background = '#05070d'
    const xml = new XMLSerializer().serializeToString(clone)
    const img = new Image()
    img.onload = () => {
      const cv = document.createElement('canvas')
      cv.width = Math.round(rect.width * 2); cv.height = Math.round(rect.height * 2)
      const cx = cv.getContext('2d')
      if (!cx) return
      cx.fillStyle = '#05070d'; cx.fillRect(0, 0, cv.width, cv.height)
      cx.scale(2, 2)
      cx.drawImage(img, 0, 0)
      cv.toBlob((b) => {
        if (!b) return
        const a = document.createElement('a')
        a.href = URL.createObjectURL(b)
        a.download = `${(board?.name || 'board').replace(/[^\w\- ]+/g, '')}.png`
        a.click()
        window.setTimeout(() => URL.revokeObjectURL(a.href), 5000)
      })
    }
    img.src = 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(xml)
  }

  // ── graph building from trace data ─────────────────────────────────────────
  const importTrace = useCallback((hNodes: HolisticNode[], hEdges: HolisticEdge[], opts: {
    anchor?: { x: number; y: number }; onlyConnectExisting?: boolean; limit?: number
  }) => {
    mutate((s) => {
      const refs = new Map<string, string>()
      for (const n of s.nodes) if (n.kind === 'address') refs.set(nodeKey(n.chain, n.ref), n.id)
      const nodes = [...s.nodes]
      const edges = [...s.edges]
      const edgeKeys = new Set(edges.map((e) => `${e.source}|${e.target}|${e.txHash}|${e.asset}`))
      const ax = opts.anchor?.x ?? 300
      const ay = opts.anchor?.y ?? 240
      let added = 0
      const limit = opts.limit ?? 15

      const ensureNode = (hn: HolisticNode | undefined, chain: string, address: string): string | null => {
        const key = nodeKey(chain, address)
        const existing = refs.get(key)
        if (existing) return existing
        if (opts.onlyConnectExisting) return null
        if (added >= limit) return null
        added++
        const angle = (added / Math.max(limit, 6)) * Math.PI * 2
        const nid = uid('n')
        nodes.push({
          id: nid, kind: 'address', ref: address, chain, caption: '', note: '',
          label: hn?.label || short(address),
          x: ax + Math.cos(angle) * 170 + (Math.random() - 0.5) * 40,
          y: ay + Math.sin(angle) * 170 + (Math.random() - 0.5) * 40,
          color: hn && hn.risk >= 70 ? '#ff2d55' : chainColor(chain),
          shape: 'circle', risk: hn?.risk, vasp: hn?.vasp || null, nodeType: hn?.type,
        })
        refs.set(key, nid)
        return nid
      }

      const hNodeById = new Map(hNodes.map((n) => [n.id, n]))
      for (const he of hEdges) {
        const sn = hNodeById.get(he.source)
        const tn = hNodeById.get(he.target)
        const sAddr = sn?.address || he.source.split(':').pop() || ''
        const tAddr = tn?.address || he.target.split(':').pop() || ''
        if (!sAddr || !tAddr) continue
        const sChain = sn?.chain || he.chain
        const tChain = tn?.chain || he.chain
        const sid = ensureNode(sn, sChain, sAddr)
        const tid = ensureNode(tn, tChain, tAddr)
        if (!sid || !tid || sid === tid) continue
        const ek = `${sid}|${tid}|${he.tx_hash}|${he.asset}`
        if (edgeKeys.has(ek)) continue
        edgeKeys.add(ek)
        edges.push({
          id: uid('e'), source: sid, target: tid, asset: he.asset, value: he.value,
          valueUsd: he.value_usd || null, usdBasis: he.value_usd ? 'engine' : undefined,
          txHash: he.tx_hash, ts: he.timestamp, kind: he.kind, label: '',
          crossChain: he.kind === 'bridge' || sChain.toLowerCase() !== tChain.toLowerCase(),
        })
      }
      return { ...s, nodes, edges }
    })
  }, [mutate])

  // ── actions ─────────────────────────────────────────────────────────────────

  async function handleAdd() {
    const raw = addValue.trim()
    if (!raw) return
    setAddValue('')
    if (/^(0x)?[a-fA-F0-9]{64}$/.test(raw)) { await addTxNode(raw); return }
    const chain = detectChain(raw)
    const center = centerWorld()
    let placedId = ''
    mutate((s) => {
      const key = nodeKey(chain, raw)
      if (s.nodes.some((n) => n.kind === 'address' && nodeKey(n.chain, n.ref) === key)) return s
      placedId = uid('n')
      return {
        ...s,
        nodes: [...s.nodes, {
          id: placedId, kind: 'address', ref: raw, chain, label: short(raw), caption: '',
          note: '', x: center.x, y: center.y, color: chainColor(chain), shape: 'circle',
        }],
      }
    })
    setBusy(t('tools:boardCanvas.busy.autoConnecting'))
    try {
      const t = await holisticTrace({ subject: raw, chain, max_hops: 1, max_nodes: 30 })
      importTrace(t.graph.nodes, t.graph.edges, { anchor: center, onlyConnectExisting: true })
    } catch { /* best-effort */ }
    setBusy('')
  }

  function addEntity(kind: NodeKind) {
    const meta = ENTITY_META[kind]
    if (!meta) return
    const c = centerWorld()
    const nid = uid('n')
    mutate((s) => ({
      ...s,
      nodes: [...s.nodes, {
        id: nid, kind, ref: '', chain: '', label: `New ${meta.label.toLowerCase()}`, caption: '',
        note: '', x: c.x + (Math.random() - 0.5) * 60, y: c.y + (Math.random() - 0.5) * 60,
        color: meta.color, shape: 'square', lead: 'none',
      }],
    }))
    setSelection(new Set([nid]))
    setShowEntityMenu(false)
  }

  function createRelationship(a: string, b: string) {
    if (!a || !b || a === b) return
    mutate((s) => {
      if (s.edges.some((e) => e.kind === 'relationship'
        && ((e.source === a && e.target === b) || (e.source === b && e.target === a)))) return s
      return {
        ...s,
        edges: [...s.edges, {
          id: uid('e'), source: a, target: b, asset: '', value: 0, valueUsd: null,
          txHash: '', ts: 0, kind: 'relationship', relationship: 'associates',
          confidence: 60, label: '', color: THEME.edgeRelationship,
        }],
      }
    })
  }

  async function expandNode(nodeId: string) {
    const n = nodeById.get(nodeId)
    if (!n || n.kind !== 'address') return
    setMenu(null)
    setBusy(t('tools:boardCanvas.busy.expanding', { addr: short(n.ref) }))
    try {
      const t = await holisticTrace({ subject: n.ref, chain: n.chain, max_hops: 1, max_nodes: 40 })
      importTrace(t.graph.nodes, t.graph.edges, { anchor: { x: n.x, y: n.y }, limit: 12 })
    } catch { /* best-effort */ }
    setBusy('')
  }

  /** UTXO / EVM / Tron transaction split: render the tx as its own node. */
  async function addTxNode(hash: string, replaceEdgeId?: string, chainHint?: string) {
    setMenu(null)
    setBusy(t('tools:boardCanvas.busy.fetchingTx', { hash: short(hash) }))
    try {
      const tx = await lookupTx(hash, chainHint)
      const chain = (tx.chain || chainHint || 'eth').toLowerCase()
      const isBtc = chain === 'btc' || (tx.inputs?.length || 0) > 0
      const anchorEdge = replaceEdgeId ? st.edges.find((e) => e.id === replaceEdgeId) : undefined
      const anchorNode = anchorEdge ? nodeById.get(anchorEdge.source) : undefined
      const ax = anchorNode ? anchorNode.x + 120 : 340
      const ay = anchorNode ? anchorNode.y : 260

      const inputs: Array<{ address: string; value: number }> = []
      const outputs: Array<{ address: string; value: number }> = []
      let asset = tx.native_unit || chain.toUpperCase()
      if (isBtc) {
        for (const i of tx.inputs || []) if (i.address) inputs.push({ address: i.address, value: i.value_btc })
        for (const o of tx.outputs || []) if (o.address) outputs.push({ address: o.address, value: o.value_btc })
        asset = 'BTC'
      } else {
        if (tx.from) inputs.push({ address: tx.from, value: tx.value })
        if (tx.to) outputs.push({ address: tx.to, value: tx.value })
        for (const tt of tx.token_transfers || []) {
          const dec = tt.decimals ?? 18
          const v = Number(tt.value_raw) / 10 ** dec
          if (tt.from) inputs.push({ address: tt.from, value: v })
          if (tt.to) outputs.push({ address: tt.to, value: v })
        }
        for (const it of tx.internal_txs || []) {
          if (it.from) inputs.push({ address: it.from, value: it.value_eth })
          if (it.to) outputs.push({ address: it.to, value: it.value_eth })
        }
      }

      const ts = tx.timestamp ? Math.floor(new Date(tx.timestamp).getTime() / 1000) : 0
      mutate((s) => {
        const refs = new Map<string, string>()
        for (const n of s.nodes) if (n.kind === 'address') refs.set(nodeKey(n.chain, n.ref), n.id)
        const nodes = [...s.nodes]
        let edges = replaceEdgeId ? s.edges.filter((e) => e.id !== replaceEdgeId) : [...s.edges]
        const txId = uid('tx')
        nodes.push({
          id: txId, kind: 'tx', ref: hash, chain, label: `TX ${short(hash)}`, caption: '',
          note: '', x: ax, y: ay, color: '#ffd60a', shape: 'square',
          txMeta: { inputs: inputs.slice(0, 12), outputs: outputs.slice(0, 12), asset },
        })
        let ai = 0
        const ensure = (address: string, side: -1 | 1): string => {
          const key = nodeKey(chain, address)
          const ex = refs.get(key)
          if (ex) return ex
          const nid = uid('n')
          ai++
          nodes.push({
            id: nid, kind: 'address', ref: address, chain, label: short(address), caption: '',
            note: '', x: ax + side * 200, y: ay + ((ai % 6) - 2.5) * 62,
            color: chainColor(chain), shape: 'circle',
          })
          refs.set(key, nid)
          return nid
        }
        for (const i of inputs.slice(0, 12)) {
          const nid = ensure(i.address, -1)
          edges = [...edges, { id: uid('e'), source: nid, target: txId, asset, value: i.value, txHash: hash, ts, kind: isBtc ? 'utxo_in' : 'tx_in', label: '', valueUsd: null }]
        }
        for (const o of outputs.slice(0, 12)) {
          const nid = ensure(o.address, 1)
          edges = [...edges, { id: uid('e'), source: txId, target: nid, asset, value: o.value, txHash: hash, ts, kind: isBtc ? 'utxo_out' : 'tx_out', label: '', valueUsd: null }]
        }
        return { ...s, nodes, edges }
      })
    } catch { /* surfaced via busy reset */ }
    setBusy('')
  }

  function deleteSelection() {
    if (selection.size === 0) return
    mutate((s) => ({
      ...s,
      nodes: s.nodes.filter((n) => !selection.has(n.id)),
      edges: s.edges.filter((e) => !selection.has(e.source) && !selection.has(e.target) && !selection.has(e.id)),
      clusters: s.clusters
        .map((c) => ({ ...c, members: c.members.filter((m) => !selection.has(m)) }))
        .filter((c) => c.members.length > 0 && !selection.has(c.id)),
      zones: (s.zones || []).filter((z) => !selection.has(z.id)),
    }))
    setSelection(new Set())
  }

  function groupSelection(name: string) {
    const members = [...selection].filter((sid) => {
      const n = nodeById.get(sid)
      return n && n.kind === 'address'
    })
    if (members.length < 2) return
    const cx = members.reduce((a, m) => a + (nodeById.get(m)?.x || 0), 0) / members.length
    const cy = members.reduce((a, m) => a + (nodeById.get(m)?.y || 0), 0) / members.length
    const cid = uid('cl')
    mutate((s) => ({
      ...s,
      nodes: [...s.nodes, {
        id: cid, kind: 'cluster', ref: name, chain: '', label: name, caption: `${members.length} addresses`,
        note: '', x: cx, y: cy, color: THEME.edgeCrossChain, shape: 'square', members, collapsed: true,
      }],
      clusters: [...s.clusters, { id: cid, name, members, collapsed: true, color: THEME.edgeCrossChain }],
    }))
    setSelection(new Set([cid]))
    setNamingCluster(false)
    setClusterName('')
  }

  function toggleCluster(cid: string) {
    mutate((s) => ({
      ...s,
      clusters: s.clusters.map((c) => (c.id === cid ? { ...c, collapsed: !c.collapsed } : c)),
      nodes: s.nodes.map((n) => (n.id === cid ? { ...n, collapsed: !n.collapsed } : n)),
    }))
  }

  function ungroup(cid: string) {
    mutate((s) => ({
      ...s,
      clusters: s.clusters.filter((c) => c.id !== cid),
      nodes: s.nodes.filter((n) => n.id !== cid),
      edges: s.edges.filter((e) => e.source !== cid && e.target !== cid),
    }))
    setMenu(null)
  }

  function addStickyNote() {
    const c = toWorld(
      (svgRef.current?.getBoundingClientRect()?.left || 0) + 200,
      (svgRef.current?.getBoundingClientRect()?.top || 0) + 160,
    )
    const nid = uid('note')
    mutate((s) => ({
      ...s,
      nodes: [...s.nodes, {
        id: nid, kind: 'note', ref: '', chain: '', label: 'Annotation', caption: '',
        note: 'Double-click to edit in the inspector →', x: c.x, y: c.y, color: '#ffd60a', shape: 'square',
      }],
    }))
    setSelection(new Set([nid]))
  }

  function patchNode(nid: string, patch: Partial<BoardNode>) {
    mutate((s) => ({ ...s, nodes: s.nodes.map((n) => (n.id === nid ? { ...n, ...patch } : n)) }))
  }

  function patchEdge(eid: string, patch: Partial<BoardEdge>) {
    mutate((s) => ({ ...s, edges: s.edges.map((e) => (e.id === eid ? { ...e, ...patch } : e)) }))
  }

  function patchZone(zid: string, patch: Partial<BoardZone>) {
    mutate((s) => ({ ...s, zones: (s.zones || []).map((z) => (z.id === zid ? { ...z, ...patch } : z)) }))
  }

  // ── fiat pricing (lazy fill, untracked by undo) ─────────────────────────────
  const pricingRef = useRef(false)
  useEffect(() => {
    if (!st.preferences.fiat || pricingRef.current) return
    const unpriced = st.edges.filter((e) => e.valueUsd == null && e.value > 0 && e.asset).slice(0, 60)
    if (unpriced.length === 0) return
    pricingRef.current = true
    convertBatch(unpriced.map((e) => ({ id: e.id, asset: e.asset, amount: e.value, ts: e.ts || undefined })))
      .then((items) => {
        const byId = new Map(items.map((i) => [i.id, i]))
        mutateQuiet((s) => ({
          ...s,
          edges: s.edges.map((e) => {
            const q = byId.get(e.id)
            return q && q.usd_at_time != null ? { ...e, valueUsd: q.usd_at_time, usdBasis: q.basis } : e
          }),
        }))
      })
      .catch(() => undefined)
      .finally(() => { pricingRef.current = false })
  }, [st.preferences.fiat, st.edges, mutateQuiet])

  // ── share & comments ────────────────────────────────────────────────────────
  useEffect(() => { if (showShare) listShares(id).then(setShares).catch(() => undefined) }, [showShare, id])
  useEffect(() => { if (showComments) listComments(id).then(setComments).catch(() => undefined) }, [showComments, id])

  async function makeShare() {
    try {
      const s = await createShare(id, { mode: shareMode, password: sharePassword, live: shareLive, expires_hours: shareExpiry })
      setNewShare(s)
      setShares(await listShares(id))
      setSharePassword('')
    } catch { /* validation shown by disabled state */ }
  }

  function copyLink(token: string) {
    const url = `${window.location.origin}/board-share/${token}`
    navigator.clipboard?.writeText(url)
    setCopied(token)
    window.setTimeout(() => setCopied(''), 1500)
  }

  // ── pointer interactions ────────────────────────────────────────────────────

  function onNodeMouseDown(e: React.MouseEvent, nid: string) {
    e.stopPropagation()
    setMenu(null)
    if (mode === 'link') {
      if (!linkFrom) { setLinkFrom(nid); return }
      createRelationship(linkFrom, nid)
      setLinkFrom('')
      return
    }
    let sel = selection
    if (e.shiftKey) {
      sel = new Set(selection)
      sel.has(nid) ? sel.delete(nid) : sel.add(nid)
      setSelection(sel)
    } else if (!selection.has(nid)) {
      sel = new Set([nid])
      setSelection(sel)
    }
    const orig = new Map<string, { x: number; y: number }>()
    for (const sid of sel.has(nid) ? sel : new Set([nid])) {
      const n = nodeById.get(sid)
      if (n) orig.set(sid, { x: n.x, y: n.y })
    }
    pushHistory()
    setDrag({ type: 'node', id: nid, startX: e.clientX, startY: e.clientY, orig })
  }

  function onBgMouseDown(e: React.MouseEvent) {
    setMenu(null)
    if (mode === 'link') {
      setLinkFrom('')
      setDrag({ type: 'pan', startX: e.clientX, startY: e.clientY, origVx: view.x, origVy: view.y })
      return
    }
    if (mode === 'zone') {
      const w = toWorld(e.clientX, e.clientY)
      setDrag({ type: 'zoneDraw', startX: w.x, startY: w.y, curX: w.x, curY: w.y })
      return
    }
    if (e.shiftKey) {
      const w = toWorld(e.clientX, e.clientY)
      setDrag({ type: 'band', startX: w.x, startY: w.y, curX: w.x, curY: w.y })
    } else {
      setSelection(new Set())
      setDrag({ type: 'pan', startX: e.clientX, startY: e.clientY, origVx: view.x, origVy: view.y })
    }
  }

  function onZoneTitleMouseDown(e: React.MouseEvent, z: BoardZone) {
    e.stopPropagation()
    setMenu(null)
    setSelection(new Set([z.id]))
    pushHistory()
    setDrag({ type: 'zone', id: z.id, startX: e.clientX, startY: e.clientY, origX: z.x, origY: z.y })
  }

  function onZoneResizeMouseDown(e: React.MouseEvent, z: BoardZone) {
    e.stopPropagation()
    setSelection(new Set([z.id]))
    pushHistory()
    setDrag({ type: 'zoneResize', id: z.id, startX: e.clientX, startY: e.clientY, origW: z.w, origH: z.h })
  }

  function onMouseMove(e: React.MouseEvent) {
    if (mode === 'link' && linkFrom) setCursor(toWorld(e.clientX, e.clientY))
    if (!drag) return
    if (drag.type === 'node') {
      const dx = (e.clientX - drag.startX) / view.z
      const dy = (e.clientY - drag.startY) / view.z
      setSt((s) => ({
        ...s,
        nodes: s.nodes.map((n) => {
          const o = drag.orig.get(n.id)
          return o ? { ...n, x: o.x + dx, y: o.y + dy } : n
        }),
      }))
    } else if (drag.type === 'pan') {
      setSt((s) => ({
        ...s,
        viewport: { ...s.viewport, x: drag.origVx + (e.clientX - drag.startX), y: drag.origVy + (e.clientY - drag.startY) },
      }))
    } else if (drag.type === 'zone') {
      const dx = (e.clientX - drag.startX) / view.z
      const dy = (e.clientY - drag.startY) / view.z
      setSt((s) => ({
        ...s,
        zones: (s.zones || []).map((z) => (z.id === drag.id ? { ...z, x: drag.origX + dx, y: drag.origY + dy } : z)),
      }))
    } else if (drag.type === 'zoneResize') {
      const dx = (e.clientX - drag.startX) / view.z
      const dy = (e.clientY - drag.startY) / view.z
      setSt((s) => ({
        ...s,
        zones: (s.zones || []).map((z) => (z.id === drag.id
          ? { ...z, w: Math.max(120, drag.origW + dx), h: Math.max(80, drag.origH + dy) } : z)),
      }))
    } else {
      const w = toWorld(e.clientX, e.clientY)
      setDrag({ ...drag, curX: w.x, curY: w.y })
    }
  }

  function onMouseUp() {
    if (drag?.type === 'node' || drag?.type === 'pan' || drag?.type === 'zone' || drag?.type === 'zoneResize') scheduleSave()
    if (drag?.type === 'band') {
      const x1 = Math.min(drag.startX, drag.curX); const x2 = Math.max(drag.startX, drag.curX)
      const y1 = Math.min(drag.startY, drag.curY); const y2 = Math.max(drag.startY, drag.curY)
      const sel = new Set(selection)
      for (const n of visibleNodes) if (n.x >= x1 && n.x <= x2 && n.y >= y1 && n.y <= y2) sel.add(n.id)
      setSelection(sel)
    }
    if (drag?.type === 'zoneDraw') {
      const x = Math.min(drag.startX, drag.curX); const y = Math.min(drag.startY, drag.curY)
      const w = Math.abs(drag.curX - drag.startX); const h = Math.abs(drag.curY - drag.startY)
      if (w >= 100 && h >= 70) {
        const zid = uid('zn')
        const color = ZONE_COLORS[(stRef.current.zones || []).length % ZONE_COLORS.length]
        mutate((s) => ({
          ...s,
          zones: [...(s.zones || []), { id: zid, name: `Zone ${(s.zones || []).length + 1}`, x, y, w, h, color }],
        }))
        setSelection(new Set([zid]))
      }
      setMode('select')
    }
    setDrag(null)
  }

  function onWheel(e: React.WheelEvent) {
    const rect = svgRef.current?.getBoundingClientRect()
    if (!rect) return
    const mx = e.clientX - rect.left
    const my = e.clientY - rect.top
    const factor = e.deltaY < 0 ? 1.12 : 1 / 1.12
    setSt((s) => {
      const z = Math.max(0.15, Math.min(3.5, s.viewport.z * factor))
      const k = z / s.viewport.z
      return { ...s, viewport: { x: mx - (mx - s.viewport.x) * k, y: my - (my - s.viewport.y) * k, z } }
    })
    scheduleSave()
  }

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      const tag = (document.activeElement?.tagName || '').toLowerCase()
      if (tag === 'input' || tag === 'textarea' || tag === 'select') return
      if ((e.ctrlKey || e.metaKey) && !e.shiftKey && e.key.toLowerCase() === 'z') { e.preventDefault(); undo(); return }
      if ((e.ctrlKey || e.metaKey) && (e.key.toLowerCase() === 'y' || (e.shiftKey && e.key.toLowerCase() === 'z'))) { e.preventDefault(); redo(); return }
      if (e.key === 'Delete' || e.key === 'Backspace') deleteSelection()
      if (e.key === 'Escape') { setSelection(new Set()); setMenu(null); setLinkFrom(''); setMode('select') }
      if (e.key.toLowerCase() === 'f') fitView()
      if (e.key.toLowerCase() === 'l') { setMode((m) => (m === 'link' ? 'select' : 'link')); setLinkFrom('') }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  })

  // ── render helpers ──────────────────────────────────────────────────────────
  const fiat = st.preferences.fiat
  const selectedNode = selection.size === 1 ? nodeById.get([...selection][0]) : undefined
  const selectedEdge = selection.size === 1 && !selectedNode ? st.edges.find((e) => e.id === [...selection][0]) : undefined
  const selectedZone = selection.size === 1 && !selectedNode && !selectedEdge ? zones.find((z) => z.id === [...selection][0]) : undefined

  const nexusSubject = links.find((l) => l.kind === 'nexus_subject')?.ref
    || (selectedNode?.kind === 'address' ? selectedNode.ref : '')
    || st.nodes.find((n) => n.kind === 'address')?.ref
    || ''
  function openInNexus(addr: string) {
    if (!addr) return
    addBoardLink(id, 'nexus_subject', addr, selectedNode?.chain || '').catch(() => undefined)
    navigate(`/nexus/${encodeURIComponent(addr)}`)
  }

  function edgeLabel(e: BoardEdge): string {
    if (e.label) return e.label
    if (e.kind === 'relationship') {
      const rel = REL_LABEL[e.relationship || 'associates'] || 'linked'
      return e.confidence != null ? `${rel} · ${e.confidence}%` : rel
    }
    if (fiat && e.valueUsd != null) return `$${e.valueUsd >= 1000 ? e.valueUsd.toLocaleString(undefined, { maximumFractionDigits: 0 }) : e.valueUsd.toLocaleString(undefined, { maximumFractionDigits: 2 })}`
    return `${e.value < 0.0001 ? e.value.toExponential(1) : e.value.toLocaleString(undefined, { maximumFractionDigits: 4 })} ${e.asset}`
  }

  const linkFromNode = linkFrom ? nodeById.get(linkFrom) : undefined
  const canUndo = history.current.past.length > 0
  const canRedo = history.current.future.length > 0

  if (loadError) {
    return (
      <div className="p-8 text-center">
        <p className="text-red-400 text-sm">{loadError}</p>
          <button className="btn-ghost mt-4" onClick={() => navigate('/boards')}><ArrowLeft size={13} /> {t('tools:boardCanvas.backToBoards')}</button>
      </div>
    )
  }
  if (!board) {
    return <div className="p-10 flex items-center gap-2 text-text-muted text-xs"><Loader2 size={14} className="animate-spin" /> Loading board…</div>
  }

  return (
    <div className="h-[calc(100vh-64px)] flex flex-col page-enter">
      {/* ── Toolbar ── */}
      <div className="flex items-center gap-1.5 px-4 py-2 border-b border-bg-border bg-bg-elevated/60 flex-wrap">
          <button className="btn-ghost !px-2" onClick={() => navigate('/boards')} title={t('tools:boardCanvas.allBoards')}><ArrowLeft size={13} /></button>
        <input
          className="bg-transparent text-sm font-bold text-text-primary outline-none border-b border-transparent focus:border-bg-border max-w-[220px]"
          value={board.name}
          onChange={(e) => setBoard({ ...board, name: e.target.value })}
          onBlur={(e) => updateBoard(id, { name: e.target.value.trim() || board.name }).catch(() => undefined)}
        />
        <span className={`text-[10px] px-1.5 py-0.5 rounded ${saveState === 'saved' ? 'text-emerald-400' : saveState === 'error' ? 'text-red-400' : 'text-amber-400'}`}>
          {saveState === 'saved' ? t('tools:boardCanvas.saved', { version: board.version }) : saveState === 'saving' ? t('tools:boardCanvas.saving') : saveState === 'error' ? t('tools:boardCanvas.saveError') : t('tools:boardCanvas.unsaved')}
        </span>
        {busy && <span className="flex items-center gap-1 text-[10px] text-neon-cyan"><Loader2 size={11} className="animate-spin" />{busy}</span>}

        <div className="flex-1" />

        <div className="flex items-center gap-1">
          <input
            className="input !py-1.5 !text-xs w-[240px] font-mono"
            placeholder={t('tools:boardCanvas.addPlaceholder')}
            value={addValue}
            onChange={(e) => setAddValue(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter') handleAdd() }}
          />
          <button className="btn-primary !py-1.5" onClick={handleAdd} disabled={!addValue.trim()}><Plus size={13} /></button>
        </div>

        {/* entity palette */}
        <div className="relative">
          <button className={`btn-ghost !py-1.5 ${showEntityMenu ? '!text-neon-cyan' : ''}`} title={t('tools:boardCanvas.toolbar.entityPin')}
            onClick={() => { setShowEntityMenu(!showEntityMenu); setShowLayoutMenu(false) }}>
            <UserPlus size={13} /> Entity
          </button>
          {showEntityMenu && (
            <div className="absolute right-0 top-full mt-1 z-[140] w-52 rounded-lg border border-bg-border bg-bg-elevated shadow-2xl py-1 text-xs">
              {ENTITY_KINDS.map((k) => {
                const m = ENTITY_META[k]
                return (
                  <button key={k} className="w-full flex items-center gap-2 px-3 py-1.5 text-left text-text-secondary hover:text-text-primary hover:bg-bg-secondary"
                    onClick={() => addEntity(k)}>
                    <m.Icon size={12} color={m.color} /> {m.label}
                  </button>
                )
              })}
            </div>
          )}
        </div>

        {/* mode toggles */}
        <div className="flex items-center rounded-lg border border-bg-border overflow-hidden">
          <button className={`px-2 py-1.5 text-xs ${mode === 'select' ? 'bg-bg-secondary text-neon-cyan' : 'text-text-muted hover:text-text-primary'}`}
            title={t('tools:boardCanvas.toolbar.selectMode')} onClick={() => { setMode('select'); setLinkFrom('') }}><MousePointer2 size={13} /></button>
          <button className={`px-2 py-1.5 text-xs ${mode === 'link' ? 'bg-bg-secondary text-red-400' : 'text-text-muted hover:text-text-primary'}`}
            title={t('tools:boardCanvas.toolbar.linkMode')} onClick={() => { setMode(mode === 'link' ? 'select' : 'link'); setLinkFrom('') }}><Spline size={13} /></button>
          <button className={`px-2 py-1.5 text-xs ${mode === 'zone' ? 'bg-bg-secondary text-amber-400' : 'text-text-muted hover:text-text-primary'}`}
            title={t('tools:boardCanvas.toolbar.zoneMode')} onClick={() => { setMode(mode === 'zone' ? 'select' : 'zone'); setLinkFrom('') }}><BoxSelect size={13} /></button>
        </div>

        {/* layout menu */}
        <div className="relative">
<button className={`btn-ghost !py-1.5 ${showLayoutMenu ? '!text-neon-cyan' : ''}`} title={t('tools:boardCanvas.toolbar.autoLayout')}
onClick={() => { setShowLayoutMenu(!showLayoutMenu); setShowEntityMenu(false) }}>
<Waypoints size={13} />
</button>
{showLayoutMenu && (
<div className="absolute right-0 top-full mt-1 z-[140] w-52 rounded-lg border border-bg-border bg-bg-elevated shadow-2xl py-1 text-xs">
<button className="w-full flex items-center gap-2 px-3 py-1.5 text-left text-text-secondary hover:text-text-primary hover:bg-bg-secondary" onClick={runForceLayout}>
<Network size={12} /> {t('tools:boardCanvas.toolbar.forceLayout')}
</button>
<button className="w-full flex items-center gap-2 px-3 py-1.5 text-left text-text-secondary hover:text-text-primary hover:bg-bg-secondary" onClick={runTimelineLayout}>
<CalendarClock size={12} /> {t('tools:boardCanvas.toolbar.timelineLayout')}
</button>
<button className="w-full flex items-center gap-2 px-3 py-1.5 text-left text-text-secondary hover:text-text-primary hover:bg-bg-secondary" onClick={runGridLayout}>
<LayoutGrid size={12} /> {t('tools:boardCanvas.toolbar.gridLayout')}
</button>
<button className="w-full flex items-center gap-2 px-3 py-1.5 text-left text-text-secondary hover:text-text-primary hover:bg-bg-secondary" onClick={runHierarchicalLayout}>
<GitBranch size={12} /> {t('tools:boardCanvas.toolbar.hierarchicalLayout')}
</button>
<button className="w-full flex items-center gap-2 px-3 py-1.5 text-left text-text-secondary hover:text-text-primary hover:bg-bg-secondary" onClick={() => { fitView(); setShowLayoutMenu(false) }}>
<Maximize2 size={12} /> {t('tools:boardCanvas.toolbar.fitView')}
</button>
</div>
)}
</div>

<button className="btn-ghost !py-1.5 !px-2" title={t('tools:boardCanvas.toolbar.undo')} onClick={undo} disabled={!canUndo}
style={{ opacity: canUndo ? 1 : 0.35 }}><Undo2 size={13} /></button>
<button className="btn-ghost !py-1.5 !px-2" title={t('tools:boardCanvas.toolbar.redo')} onClick={redo} disabled={!canRedo}
style={{ opacity: canRedo ? 1 : 0.35 }}><Redo2 size={13} /></button>

<button className={`btn-ghost !py-1.5 ${fiat ? '!text-emerald-400' : ''}`} title={t('tools:boardCanvas.toolbar.fiatToggle')}
onClick={() => mutateQuiet((s) => ({ ...s, preferences: { ...s.preferences, fiat: !s.preferences.fiat } }))}>
{fiat ? <DollarSign size={13} /> : <Coins size={13} />}
</button>
<button className="btn-ghost !py-1.5 !px-2" onClick={addStickyNote} title={t('tools:boardCanvas.toolbar.addNote')}><StickyNote size={13} /></button>
<button className={`btn-ghost !py-1.5 !px-2 ${showLegend ? '!text-neon-cyan' : ''}`} onClick={() => setShowLegend(!showLegend)} title={t('tools:boardCanvas.toolbar.legend')}><Flag size={13} /></button>
<button className="btn-ghost !py-1.5 !px-2" onClick={exportPng} title={t('tools:boardCanvas.toolbar.exportPng')}><Camera size={13} /></button>
{nexusSubject && (
<button className="btn-ghost !py-1.5" onClick={() => openInNexus(nexusSubject)}
title={t('tools:boardCanvas.toolbar.nexus', { subject: short(nexusSubject) })}
            style={{ color: '#4aa3ff' }}>
            <Network size={13} />
          </button>
        )}
        <button className="btn-ghost !py-1.5" onClick={() => { setShowComments(false); setShowShare(!showShare) }} title={t('tools:boardCanvas.toolbar.share')}>
          <Share2 size={13} />
        </button>
        <button className="btn-ghost !py-1.5" onClick={() => { setShowShare(false); setShowComments(!showComments) }} title={t('tools:boardCanvas.toolbar.comments')}>
          <MessageSquare size={13} /> {comments.filter((c) => !c.resolved).length || ''}
        </button>
      </div>

      {/* ── Mode hint bar ── */}
      {mode !== 'select' && (
        <div className="px-4 py-1 text-[10px] border-b border-bg-border"
          style={{ background: mode === 'link' ? 'rgba(255,69,58,0.08)' : 'rgba(255,159,10,0.08)', color: mode === 'link' ? '#ff6961' : '#ffb340' }}>
            {mode === 'link'
          ? t('tools:boardCanvas.mode.link')
          : t('tools:boardCanvas.mode.zone')}
        </div>
      )}

      {/* ── Multi-select action bar ── */}
      {selection.size > 1 && (
        <div className="flex items-center gap-3 px-4 py-1.5 bg-bg-secondary/80 border-b border-bg-border text-xs">
          <span className="text-text-secondary">{selection.size} selected</span>
          {namingCluster ? (
            <span className="flex items-center gap-1">
              <input className="input !py-0.5 !text-xs w-56" placeholder={t('tools:boardCanvas.cluster.namePh')}
                value={clusterName} onChange={(e) => setClusterName(e.target.value)} autoFocus
                onKeyDown={(e) => { if (e.key === 'Enter' && clusterName.trim()) groupSelection(clusterName.trim()) }} />
              <button className="btn-primary !py-0.5 !px-2" disabled={!clusterName.trim()} onClick={() => groupSelection(clusterName.trim())}><Check size={11} /></button>
              <button className="btn-ghost !py-0.5 !px-2" onClick={() => setNamingCluster(false)}><X size={11} /></button>
            </span>
          ) : (
            <button className="btn-ghost !py-0.5" onClick={() => setNamingCluster(true)}><Boxes size={12} /> Group into cluster</button>
          )}
          <button className="btn-ghost !py-0.5" onClick={() => { [...selection].slice(0, 3).forEach((sid) => expandNode(sid)) }}>
            <Expand size={12} /> Expand (max 3)
          </button>
          <button className="btn-ghost !py-0.5 !text-red-400" onClick={deleteSelection}><Trash2 size={12} /> Remove</button>
        </div>
      )}

      <div className="flex-1 relative flex min-h-0">
        {/* ── Canvas ── */}
        <svg
          ref={svgRef}
          className="flex-1 select-none"
          style={{
            background: 'radial-gradient(1200px 600px at 50% 0%, rgba(10,132,255,0.05), transparent), #05070d',
            cursor: drag?.type === 'pan' ? 'grabbing' : mode === 'zone' ? 'crosshair' : mode === 'link' ? 'alias' : 'default',
          }}
          onMouseDown={onBgMouseDown}
          onMouseMove={onMouseMove}
          onMouseUp={onMouseUp}
          onMouseLeave={onMouseUp}
          onWheel={onWheel}
          onContextMenu={(e) => e.preventDefault()}
        >
          <defs>
            {/* Professional themed arrowheads — one per edge color */}
            <marker id="brd-arrow-emerald" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
              <path d="M 0 1 L 9 5 L 0 9 z" fill={THEME.edgeInflow} />
            </marker>
            <marker id="brd-arrow-amber" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
              <path d="M 0 1 L 9 5 L 0 9 z" fill={THEME.edgeOutflow} />
            </marker>
            <marker id="brd-arrow-sky" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
              <path d="M 0 1 L 9 5 L 0 9 z" fill={THEME.edgeCrossChain} />
            </marker>
            <marker id="brd-arrow-crimson" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
              <path d="M 0 1 L 9 5 L 0 9 z" fill={THEME.edgeRelationship} />
            </marker>
            <marker id="brd-arrow-graphite" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
              <path d="M 0 1 L 9 5 L 0 9 z" fill={THEME.edgeDefault} />
            </marker>
          </defs>
          <g transform={`translate(${view.x},${view.y}) scale(${view.z})`}>
            {/* zones (behind everything) */}
            {zones.map((z) => {
              const sel = selection.has(z.id)
              return (
                <g key={z.id}>
                  <rect x={z.x} y={z.y} width={z.w} height={z.h} rx={12}
                    fill={`${z.color}0a`} stroke={sel ? THEME.selected : `${z.color}55`}
                    strokeWidth={sel ? 1.8 : 1} strokeDasharray="6 4" style={{ pointerEvents: 'none' }} />
                  {/* title bar — draggable / selectable */}
                  <g style={{ cursor: 'move' }}
                    onMouseDown={(ev) => onZoneTitleMouseDown(ev, z)}
                    onContextMenu={(ev) => { ev.preventDefault(); ev.stopPropagation(); setSelection(new Set([z.id])); setMenu({ x: ev.clientX, y: ev.clientY, zoneId: z.id }) }}>
                    <rect x={z.x} y={z.y - 22} width={Math.min(z.w, Math.max(90, z.name.length * 8 + 26))} height={20} rx={5}
                      fill={`${z.color}33`} stroke={`${z.color}88`} strokeWidth={1} />
                    <text x={z.x + 10} y={z.y - 8} fontSize={11} fontWeight={700} fill={z.color}>{z.name}</text>
                  </g>
                  {/* resize handle */}
                  <rect x={z.x + z.w - 12} y={z.y + z.h - 12} width={12} height={12} rx={2}
                    fill={`${z.color}55`} style={{ cursor: 'nwse-resize' }}
                    onMouseDown={(ev) => onZoneResizeMouseDown(ev, z)} />
                </g>
              )
            })}

            {/* edges */}
            {visibleEdges.map((e) => {
              const s = nodeById.get(e.source) || st.nodes.find((n) => n.id === e.source)
              const t = nodeById.get(e.target) || st.nodes.find((n) => n.id === e.target)
              if (!s || !t) return null
              const mx = (s.x + t.x) / 2
              const my = (s.y + t.y) / 2
              const sel = selection.has(e.id)
              const isRel = e.kind === 'relationship'
              const relColor = e.color || THEME.edgeRelationship
              const conf = e.confidence ?? 60
              return (
                <g key={e.id} onMouseDown={(ev) => { ev.stopPropagation(); setSelection(new Set([e.id])); setMenu(null) }}
                  onContextMenu={(ev) => { ev.preventDefault(); ev.stopPropagation(); setMenu({ x: ev.clientX, y: ev.clientY, edgeId: e.id }) }}
                  style={{ cursor: 'pointer' }}>
                  {isRel ? (
                    <>
                      {/* Relationship "red string" — refined crimson with confidence-based opacity */}
                      <path d={`M ${s.x} ${s.y} Q ${mx + (e.curve ?? 0)} ${my + 26 + (e.curve ?? 0)} ${t.x} ${t.y}`}
                        fill="none" stroke={sel ? THEME.selected : relColor}
                        strokeWidth={sel ? 2.4 : 1.6} opacity={0.35 + 0.65 * (conf / 100)} />
                      <g transform={`translate(${mx},${my + 14})`} style={{ pointerEvents: 'none' }}>
                        <rect x={-48} y={-9} width={96} height={17} rx={8.5} fill={THEME.pillBgCrimson} stroke={relColor} strokeWidth={0.7} opacity={0.96} />
                        <text x={0} y={3.5} textAnchor="middle" fontSize={7.5} fontWeight={600} letterSpacing="0.5"
                          fill={relColor === '#ef4444' || relColor === '#ff453a' ? '#fca5a5' : relColor}>
                          {edgeLabel(e).slice(0, 22).toUpperCase()}
                        </text>
                      </g>
                    </>
                  ) : (
                    <>
                      {/* Fund-flow edges with corporate directional palette */}
                      {(() => {
                        const pairKey = `${e.source}->${e.target}`
                        const reverseKey = `${e.target}->${e.source}`
                        const parallels = visibleEdges.filter(x => `${x.source}->${x.target}` === pairKey)
                        const idxAmong = parallels.findIndex(x => x.id === e.id)
                        const count = Math.max(1, parallels.length)
                        const reverseCount = visibleEdges.filter(x => `${x.source}->${x.target}` === reverseKey).length
                        const spread = count + reverseCount > 1 ? ((idxAmong - (count - 1) / 2) * 26) + (reverseCount ? 14 : 0) : (e.curve ?? 0)
                        const dx = t.x - s.x, dy = t.y - s.y
                        const len = Math.max(1, Math.sqrt(dx * dx + dy * dy))
                        const px = -dy / len, py = dx / len
                        const cx = mx + px * spread, cy = my + py * spread
                        const d = spread !== 0
                          ? `M ${s.x} ${s.y} Q ${cx} ${cy} ${t.x} ${t.y}`
                          : `M ${s.x} ${s.y} L ${t.x} ${t.y}`
                        // Corporate edge color + matching arrowhead.
                        const isCrossChain = !!e.crossChain
                        const isManual = e.kind === 'manual'
                        const edgeColor = sel ? THEME.selected
                          : isCrossChain ? THEME.edgeCrossChain
                          : isManual ? THEME.edgeManual
                          : e.color || THEME.edgeDefault
                        const arrowId = isCrossChain ? 'brd-arrow-sky'
                          : sel ? 'brd-arrow-graphite'
                          : 'brd-arrow-graphite'
                        const label = edgeLabel(e)
                        const labelColor = fiat && e.valueUsd != null ? THEME.edgeInflow : THEME.textSecondary
                        return <>
                          <path d={d} fill="none"
                            stroke={edgeColor}
                            strokeWidth={sel ? 2.2 : 1.5}
                            strokeLinecap="round"
                            strokeDasharray={isCrossChain ? '6 4' : isManual ? '3 3' : undefined}
                            markerEnd={`url(#${arrowId})`} />
                          {/* Value label in a professional pill chip */}
                          {label && (
                            <g transform={`translate(${cx},${cy - 6})`} style={{ pointerEvents: 'none' }}>
                              <rect x={-(label.length * 3.2 + 8)} y={-8} width={label.length * 6.4 + 16} height={16} rx={4}
                                fill={THEME.pillBg} stroke={edgeColor} strokeWidth={0.5} opacity={0.95} />
                              <text x={0} y={3.5} textAnchor="middle" fontSize={8.5} fontWeight={500} fill={labelColor}>
                                {label}
                              </text>
                            </g>
                          )}
                        </>
                      })()}
                      {st.preferences.showGlyphs && e.crossChain && (
                        <g transform={`translate(${mx},${my + 8})`} style={{ pointerEvents: 'none' }}>
                          <rect x={-30} y={-8} width={60} height={16} rx={8} fill={THEME.pillBgSky} stroke={THEME.edgeCrossChain} strokeWidth={0.7} />
                          <text x={0} y={3.5} textAnchor="middle" fontSize={8} fontWeight={600} fill={THEME.edgeCrossChain}>
                            ⛓ {(s.chain || '?').toUpperCase()}→{(t.chain || '?').toUpperCase()}
                          </text>
                        </g>
                      )}
                    </>
                  )}
                </g>
              )
            })}

            {/* red-string preview while linking */}
            {mode === 'link' && linkFromNode && cursor && (
              <line x1={linkFromNode.x} y1={linkFromNode.y} x2={cursor.x} y2={cursor.y}
                stroke={THEME.edgeRelationship} strokeWidth={1.6} strokeDasharray="5 4" style={{ pointerEvents: 'none' }} />
            )}

            {/* nodes */}
            {visibleNodes.map((n) => {
              const sel = selection.has(n.id)
              const isMatch = matchIds.has(n.id)
              const stroke = sel ? THEME.selected : n.color
              const lead = n.lead && n.lead !== 'none' ? LEAD_META[n.lead] : null
              const entity = ENTITY_META[n.kind]
              return (
                <g key={n.id} transform={`translate(${n.x},${n.y})`}
                  onMouseDown={(ev) => onNodeMouseDown(ev, n.id)}
                  onDoubleClick={(ev) => { ev.stopPropagation(); if (n.kind === 'cluster') toggleCluster(n.id) }}
                  onContextMenu={(ev) => { ev.preventDefault(); ev.stopPropagation(); setSelection(new Set([n.id])); setMenu({ x: ev.clientX, y: ev.clientY, nodeId: n.id }) }}
                  style={{ cursor: mode === 'link' ? 'alias' : 'grab' }}>
                  {isMatch && <circle r={entity ? 62 : NODE_R + 10} fill="none" stroke="#5b9fd6" strokeWidth={1.5} strokeDasharray="3 3" opacity={0.7} style={{ pointerEvents: 'none' }} />}
                  {n.kind === 'note' ? (() => {
                    const layout = computeNoteLayout(n.label || 'Annotation', n.note || '')
                    const w = layout.width, h = layout.height
                    const left = -w / 2, top = -h / 2
                    return (
                      <>
                        {/* Annotation note — responsive to text content */}
                        <rect x={left} y={top} width={w} height={h} rx={8} fill="rgba(245,158,11,0.06)" stroke={sel ? THEME.selected : '#a07d2a'} strokeWidth={sel ? 1.8 : 1} />
                        <rect x={left} y={top} width={w} height={3} rx={1.5} fill="rgba(245,158,11,0.25)" style={{ pointerEvents: 'none' }} />
                        <text x={0} y={top + 16} textAnchor="middle" fontSize={10} fontWeight={700} fill="#d4a843">
                          {(n.label || 'Annotation').slice(0, Math.floor(w / NOTE_CHAR_W))}
                        </text>
                        {layout.lines.map((line, i) => (
                          <text key={i} x={0} y={top + NOTE_PAD_TOP + i * NOTE_LINE_H} textAnchor="middle" fontSize={9} fill={THEME.textSecondary}>
                            {line}
                          </text>
                        ))}
                      </>
                    )
                  })() : n.kind === 'tx' ? (
                    <>
                      {/* Transaction chip — refined amber treatment */}
                      <rect x={-34} y={-22} width={68} height={44} rx={6} fill="rgba(245,158,11,0.05)" stroke={sel ? THEME.selected : '#8a6d1d'} strokeWidth={sel ? 1.8 : 1.2} />
                      <line x1={0} y1={-22} x2={0} y2={22} stroke="#8a6d1d" strokeWidth={0.6} strokeDasharray="3 2" />
                      <text x={-17} y={-9} textAnchor="middle" fontSize={7.5} fill={THEME.textSecondary}>IN {n.txMeta?.inputs.length ?? 0}</text>
                      <text x={17} y={-9} textAnchor="middle" fontSize={7.5} fill={THEME.textSecondary}>OUT {n.txMeta?.outputs.length ?? 0}</text>
                      <text x={0} y={6} textAnchor="middle" fontSize={9} fontWeight={700} fill="#d4a843">TX</text>
                      <text x={0} y={17} textAnchor="middle" fontSize={7} fill={THEME.textMuted}>{short(n.ref)}</text>
                    </>
                  ) : n.kind === 'cluster' ? (
                    <>
                      {/* Cluster card — refined indigo-graphite */}
                      <rect x={-46} y={-28} width={92} height={56} rx={10} fill="rgba(99,102,241,0.06)" stroke={sel ? THEME.selected : n.color || '#5b6b8e'} strokeWidth={sel ? 2.2 : 1.4} />
                      <rect x={-40} y={-34} width={80} height={10} rx={4} fill="rgba(99,102,241,0.18)" style={{ pointerEvents: 'none' }} />
                      <text x={0} y={-2} textAnchor="middle" fontSize={10} fontWeight={700} fill="#8b95d4">{n.label.slice(0, 14)}</text>
                      <text x={0} y={11} textAnchor="middle" fontSize={8} fill={THEME.textMuted}>{(st.clusters.find((c) => c.id === n.id)?.members.length ?? 0)} addrs · {n.collapsed ? 'collapsed' : 'expanded'}</text>
                      <g transform="translate(36,-22)">{n.collapsed ? <ChevronDown size={11} color="#8b95b0" /> : <ChevronUp size={11} color="#8b95b0" />}</g>
                    </>
                  ) : entity ? (
                    <>
                      {/* Crimewall entity card — professional graphite, theme-aware */}
                      {lead && (
                        <rect x={-58} y={-27} width={116} height={54} rx={12} fill="none"
                          stroke={lead.color} strokeWidth={1.3} strokeDasharray="4 3" opacity={0.85} style={{ pointerEvents: 'none' }} />
                      )}
                      <rect x={-52} y={-21} width={104} height={42} rx={10}
                        fill={THEME.cardFill} stroke={sel ? THEME.selected : stroke} strokeWidth={sel ? 2.2 : 1.4} />
                      {(() => {
                        const plat = n.kind === 'social' ? SOCIAL_PLATFORMS.find((p) => p.name === n.attrs?.platform) : undefined
                        const ringColor = plat ? plat.hex : entity.color
                        return (
                          <>
                            <circle cx={-34} cy={0} r={12} fill={`${ringColor}22`} stroke={ringColor} strokeWidth={1} style={{ pointerEvents: 'none' }} />
                            {plat ? (
                              <g transform="translate(-41,-7) scale(0.5833)" style={{ pointerEvents: 'none' }}>
                                <path d={plat.path} fill={glyphColor(plat.hex)} />
                              </g>
                            ) : (
                              <g transform="translate(-41,-7)" style={{ pointerEvents: 'none' }}>
                                <entity.Icon size={14} color={entity.color} />
                              </g>
                            )}
                          </>
                        )
                      })()}
                      <text x={-16} y={-3} fontSize={9} fontWeight={700} fill={THEME.textPrimary} style={{ pointerEvents: 'none' }}>{n.label.slice(0, 13)}</text>
                      <text x={-16} y={9} fontSize={7.5} fill={THEME.textMuted} style={{ pointerEvents: 'none' }}>{(n.ref || entity.label).slice(0, 16)}</text>
                      {lead && (
                        <text x={0} y={38} textAnchor="middle" fontSize={7.5} fontWeight={700} letterSpacing="0.5" fill={lead.color} style={{ pointerEvents: 'none' }}>
                          ● {lead.label.toUpperCase()}
                        </text>
                      )}
                      {n.caption && <text x={0} y={lead ? 49 : 38} textAnchor="middle" fontSize={8.5} fill={THEME.textSecondary} style={{ pointerEvents: 'none' }}>{n.caption.slice(0, 24)}</text>}
                      {n.priority && (
                        <g transform="translate(-52,-27)" style={{ pointerEvents: 'none' }}>
                          <circle r={8} fill={THEME.edgeRelationship} opacity={0.9} />
                          <circle r={10} fill="none" stroke={THEME.edgeRelationship} strokeWidth={0.6} opacity={0.4} />
                          <g transform="translate(-6,-6)"><Pin size={12} color="#fff" /></g>
                        </g>
                      )}
                    </>
                  ) : (
                    <>
                      {lead && (
                        <circle r={NODE_R + 2} fill="none" stroke={lead.color} strokeWidth={1.4} strokeDasharray="4 3" opacity={0.9} style={{ pointerEvents: 'none' }} />
                      )}
                      {/* GraphNodeKit body — type-aware shape (auto-classified from
                          label/caption/vasp) + unified risk ring + chain glyph +
                          type badge. Replaces the 3 hardcoded dark shapes so board
                          address nodes match the Nexus/Trace graphs and render
                          correctly in light mode (no more rgba(10,14,24) dark fill). */}
                      <GraphNodeKit
                        r={NODE_R - 2}
                        entity={{ roleHint: n.label, category: n.nodeType, labels: [n.label, n.caption].filter(Boolean) as string[] }}
                        riskScore={n.risk ?? 0}
                        chain={n.chain}
                        label={(n.caption || n.label).slice(0, 22)}
                        selected={sel}
                        showLabel
                        showTypeBadge
                      />
                      {n.priority && (
                        <g transform={`translate(${-NODE_R + 2},${-NODE_R - 4})`} style={{ pointerEvents: 'none' }}>
                          <circle r={8} fill={THEME.edgeRelationship} opacity={0.9} />
                          <circle r={10} fill="none" stroke={THEME.edgeRelationship} strokeWidth={0.6} opacity={0.4} />
                          <g transform="translate(-6,-6)"><Pin size={12} color="#fff" /></g>
                        </g>
                      )}
                      {n.vasp && (
                        <text x={0} y={NODE_R + 21} textAnchor="middle" fontSize={8} fontWeight={500} fill={THEME.edgeInflow} style={{ pointerEvents: 'none' }}>◈ {String(n.vasp).slice(0, 18)}</text>
                      )}
                      {lead && (
                        <text x={0} y={NODE_R + (n.vasp ? 32 : 21)} textAnchor="middle" fontSize={7.5} fontWeight={700} letterSpacing="0.5" fill={lead.color} style={{ pointerEvents: 'none' }}>
                          ● {lead.label.toUpperCase()}
                        </text>
                      )}
                    </>
                  )}
                </g>
              )
            })}

            {/* rubber band */}
            {drag?.type === 'band' && (
              <rect
                x={Math.min(drag.startX, drag.curX)} y={Math.min(drag.startY, drag.curY)}
                width={Math.abs(drag.curX - drag.startX)} height={Math.abs(drag.curY - drag.startY)}
                fill="rgba(150,161,181,0.06)" stroke={THEME.selected} strokeDasharray="4 3" strokeWidth={1}
              />
            )}
            {/* zone draw preview */}
            {drag?.type === 'zoneDraw' && (
              <rect
                x={Math.min(drag.startX, drag.curX)} y={Math.min(drag.startY, drag.curY)}
                width={Math.abs(drag.curX - drag.startX)} height={Math.abs(drag.curY - drag.startY)}
                fill="rgba(245,158,11,0.04)" stroke={THEME.edgeOutflow} strokeDasharray="6 4" strokeWidth={1.2} rx={12}
              />
            )}
          </g>
        </svg>

        {/* ── Canvas search (floating) ── */}
        <div className="absolute top-3 left-3 z-[120] flex items-center gap-1 rounded-lg border border-bg-border bg-bg-elevated/90 px-2 py-1 shadow-xl">
          <Search size={12} className="text-text-muted" />
          <input className="bg-transparent outline-none text-xs text-text-primary w-40"
            placeholder={t('tools:boardCanvas.search.placeholder')} value={searchQ}
            onChange={(e) => { setSearchQ(e.target.value); setMatchIdx(0) }}
            onKeyDown={(e) => { if (e.key === 'Enter') jumpToMatch(e.shiftKey ? matchIdx - 1 : matchIdx + (searchQ && matches.length ? 1 : 0)) }} />
          {searchQ && (
            <>
              <span className="text-[9px] text-text-muted whitespace-nowrap">{matches.length ? `${(matchIdx % matches.length) + 1}/${matches.length}` : '0'}</span>
              <button className="text-text-muted hover:text-text-primary" onClick={() => jumpToMatch(matchIdx - 1)} title={t('tools:boardCanvas.search.previous')}><ChevronUp size={11} /></button>
              <button className="text-text-muted hover:text-text-primary" onClick={() => jumpToMatch(matchIdx + 1)} title={t('tools:boardCanvas.search.next')}><ChevronDown size={11} /></button>
              <button className="text-text-muted hover:text-red-400" onClick={() => setSearchQ('')}><X size={11} /></button>
            </>
          )}
        </div>

        {/* ── Legend (floating) ── */}
        {showLegend && (
          <div className="absolute bottom-3 left-3 z-[120] w-56 rounded-lg border border-bg-border bg-bg-elevated/95 p-3 shadow-xl text-[10px] space-y-2">
            <p className="uppercase tracking-widest text-text-muted text-[9px]">{t('tools:boardCanvas.legend.title')}</p>
            <div className="grid grid-cols-2 gap-x-2 gap-y-1">
              {ENTITY_KINDS.map((k) => {
                const m = ENTITY_META[k]
                return <span key={k} className="flex items-center gap-1.5 text-text-secondary"><m.Icon size={10} color={m.color} />{m.label}</span>
              })}
            </div>
            <div className="pt-1 border-t border-bg-border/60 space-y-1">
              {(Object.keys(LEAD_META) as LeadStatus[]).filter((k) => k !== 'none').map((k) => (
                <span key={k} className="flex items-center gap-1.5 text-text-secondary">
                  <span className="w-2 h-2 rounded-full" style={{ background: LEAD_META[k].color }} />{LEAD_META[k].label}
                </span>
              ))}
            </div>
            <div className="pt-1 border-t border-bg-border/60 space-y-1 text-text-secondary">
              <span className="flex items-center gap-1.5"><span className="w-5 border-t" style={{ borderColor: THEME.edgeRelationship }} /> Red string (relationship)</span>
              <span className="flex items-center gap-1.5"><span className="w-5 border-t border-dashed" style={{ borderColor: THEME.edgeCrossChain }} /> Cross-chain hop</span>
              <span className="flex items-center gap-1.5"><span className="w-5 border-t" style={{ borderColor: '#33415c' }} /> Fund flow</span>
            </div>
          </div>
        )}

        {/* ── Minimap (floating) ── */}
        <Minimap nodes={st.nodes} zones={zones} view={view} svgRef={svgRef} onJump={centerOn} />

        {/* ── Inspector (single selection) ── */}
        {selectedNode && (
          <div className="w-[280px] border-l border-bg-border bg-bg-elevated/70 p-3 space-y-3 overflow-y-auto">
            <div className="flex items-center justify-between">
              <span className="text-[10px] uppercase tracking-widest text-text-muted">
                {selectedNode.kind === 'note' ? 'Annotation' : selectedNode.kind === 'tx' ? 'Transaction node'
                  : selectedNode.kind === 'cluster' ? 'Custom cluster'
                    : ENTITY_META[selectedNode.kind] ? `${ENTITY_META[selectedNode.kind].label} pin` : 'Address node'}
              </span>
              <button className="text-text-muted hover:text-red-400" onClick={deleteSelection} title="Remove"><Trash2 size={12} /></button>
            </div>
            {selectedNode.kind === 'address' && selectedNode.ref && <p className="font-mono text-[10px] text-text-secondary break-all">{selectedNode.ref}</p>}

            {ENTITY_META[selectedNode.kind] && (
              <>
                <label className="block text-[10px] text-text-muted">Name / label
                  <input className="input !py-1 !text-xs mt-1" value={selectedNode.label}
                    onChange={(e) => patchNode(selectedNode.id, { label: e.target.value })} autoFocus />
                </label>
                <label className="block text-[10px] text-text-muted">Identifier
                  <input className="input !py-1 !text-xs mt-1" value={selectedNode.ref}
                    onChange={(e) => patchNode(selectedNode.id, { ref: e.target.value })}
                    placeholder={selectedNode.kind === 'social' ? '@handle / profile URL' : ENTITY_META[selectedNode.kind].refHint} />
                </label>
              </>
            )}

            {/* social-handle platform picker */}
            {selectedNode.kind === 'social' && (
              <div>
                <span className="text-[10px] text-text-muted">Platform</span>
                <div className="grid grid-cols-4 gap-1 mt-1 max-h-[176px] overflow-y-auto pr-0.5">
                  {SOCIAL_PLATFORMS.map((p) => {
                    const active = (selectedNode.attrs?.platform || '') === p.name
                    return (
                      <button key={p.name} title={p.name} type="button"
                        className="flex flex-col items-center gap-1 px-1 py-1.5 rounded border transition-colors"
                        style={{
                          borderColor: active ? p.hex : 'rgba(255,255,255,0.08)',
                          background: active ? `${p.hex}22` : 'rgba(255,255,255,0.03)',
                          color: active ? '#fff' : '#8a94a6',
                        }}
                        onClick={() => patchNode(selectedNode.id, { attrs: { ...selectedNode.attrs, platform: p.name } })}>
                        <BrandGlyph path={p.path} color={glyphColor(p.hex)} size={16} />
                        <span className="w-full text-center truncate text-[8px] leading-none">{p.name}</span>
                      </button>
                    )
                  })}
                </div>
                {selectedNode.attrs?.platform && (
                  <button type="button" className="mt-1 text-[9px] text-text-muted hover:text-red-400"
                    onClick={() => { const a = { ...selectedNode.attrs }; delete a.platform; patchNode(selectedNode.id, { attrs: a }) }}>
                    Clear platform
                  </button>
                )}
              </div>
            )}

            <label className="block text-[10px] text-text-muted">Caption (shown on canvas)
              <input className="input !py-1 !text-xs mt-1" value={selectedNode.caption}
                onChange={(e) => patchNode(selectedNode.id, { caption: e.target.value })}
                placeholder="e.g. Victim deposit wallet" />
            </label>
            <label className="block text-[10px] text-text-muted">Notes (court-exhibit annotation)
              <textarea className="input !py-1 !text-xs mt-1 resize-none" rows={4} value={selectedNode.note}
                onChange={(e) => patchNode(selectedNode.id, { note: e.target.value })}
                placeholder="Free-text analyst note…" />
            </label>

            {/* lead status & priority — for addresses + entities */}
            {(selectedNode.kind === 'address' || ENTITY_META[selectedNode.kind]) && (
              <div>
                <span className="text-[10px] text-text-muted">Lead status</span>
                <div className="flex flex-wrap gap-1 mt-1">
                  {(Object.keys(LEAD_META) as LeadStatus[]).map((k) => (
                    <button key={k}
                      className="px-1.5 py-0.5 rounded text-[9px] border"
                      style={{
                        borderColor: (selectedNode.lead || 'none') === k ? LEAD_META[k].color : 'transparent',
                        color: LEAD_META[k].color,
                        background: (selectedNode.lead || 'none') === k ? `${LEAD_META[k].color}1a` : 'transparent',
                      }}
                      onClick={() => patchNode(selectedNode.id, { lead: k })}>
                      {k === 'none' ? 'unassessed' : LEAD_META[k].label}
                    </button>
                  ))}
                </div>
                <label className="flex items-center gap-2 mt-2 text-[10px] text-text-secondary">
                  <input type="checkbox" checked={!!selectedNode.priority}
                    onChange={(e) => patchNode(selectedNode.id, { priority: e.target.checked })} />
                  <Pin size={10} className="text-red-400" /> Priority pin
                </label>
              </div>
            )}

            {/* entity attributes */}
            {ENTITY_META[selectedNode.kind] && (
              <div className="pt-2 border-t border-bg-border">
                <span className="text-[10px] text-text-muted">Attributes</span>
                {Object.entries(selectedNode.attrs || {}).map(([k, v]) => (
                  <div key={k} className="flex items-center gap-1 mt-1">
                    <span className="text-[9px] text-text-muted w-20 truncate" title={k}>{k}</span>
                    <input className="input !py-0.5 !text-[10px] flex-1" value={v}
                      onChange={(e) => patchNode(selectedNode.id, { attrs: { ...selectedNode.attrs, [k]: e.target.value } })} />
                    <button className="text-text-muted hover:text-red-400"
                      onClick={() => {
                        const a = { ...selectedNode.attrs }
                        delete a[k]
                        patchNode(selectedNode.id, { attrs: a })
                      }}><X size={10} /></button>
                  </div>
                ))}
                <div className="flex items-center gap-1 mt-1.5">
                  <input className="input !py-0.5 !text-[10px] w-20" placeholder="key" value={attrK} onChange={(e) => setAttrK(e.target.value)} />
                  <input className="input !py-0.5 !text-[10px] flex-1" placeholder="value" value={attrV} onChange={(e) => setAttrV(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' && attrK.trim()) {
                        patchNode(selectedNode.id, { attrs: { ...selectedNode.attrs, [attrK.trim()]: attrV } })
                        setAttrK(''); setAttrV('')
                      }
                    }} />
                  <button className="btn-ghost !p-1" disabled={!attrK.trim()}
                    onClick={() => { patchNode(selectedNode.id, { attrs: { ...selectedNode.attrs, [attrK.trim()]: attrV } }); setAttrK(''); setAttrV('') }}>
                    <Plus size={10} />
                  </button>
                </div>
              </div>
            )}

            <div>
              <span className="text-[10px] text-text-muted">Color</span>
              <div className="flex gap-1.5 mt-1">
                {PALETTE.map((c) => (
                  <button key={c} className="w-5 h-5 rounded-full border"
                    style={{ background: c, borderColor: selectedNode.color === c ? '#fff' : 'transparent' }}
                    onClick={() => patchNode(selectedNode.id, { color: c })} />
                ))}
              </div>
            </div>
            {selectedNode.kind === 'address' && (
              <div>
                <span className="text-[10px] text-text-muted">Shape</span>
                <div className="flex gap-1.5 mt-1">
                  {(['circle', 'square', 'diamond'] as NodeShape[]).map((sh) => (
                    <button key={sh} className={`btn-ghost !py-0.5 !px-2 !text-[10px] ${selectedNode.shape === sh ? '!text-neon-cyan' : ''}`}
                      onClick={() => patchNode(selectedNode.id, { shape: sh })}>{sh}</button>
                  ))}
                </div>
              </div>
            )}

            <div className="pt-2 border-t border-bg-border space-y-1.5">
              <button className="btn-ghost w-full !py-1 !text-xs" style={{ color: '#ff6961' }}
                onClick={() => { setMode('link'); setLinkFrom(selectedNode.id) }}>
                <Spline size={12} /> Red string from here
              </button>
              {selectedNode.kind === 'address' && (
                <>
                  <button className="btn-ghost w-full !py-1 !text-xs" onClick={() => expandNode(selectedNode.id)}><Expand size={12} /> Expand 1 hop</button>
                  <button className="btn-ghost w-full !py-1 !text-xs" onClick={() => navigate(`/intel/${selectedNode.ref}`)}><Globe size={12} /> Open Address Intel</button>
                  <button className="btn-ghost w-full !py-1 !text-xs" onClick={() => openInNexus(selectedNode.ref)}><GitMerge size={12} /> Open in Nexus</button>
                </>
              )}
            </div>
            {selectedNode.kind === 'cluster' && (
              <div className="pt-2 border-t border-bg-border space-y-1.5">
                <button className="btn-ghost w-full !py-1 !text-xs" onClick={() => toggleCluster(selectedNode.id)}>
                  {selectedNode.collapsed ? <ChevronDown size={12} /> : <ChevronUp size={12} />} {selectedNode.collapsed ? 'Expand members' : 'Collapse members'}
                </button>
                <button className="btn-ghost w-full !py-1 !text-xs !text-red-400" onClick={() => ungroup(selectedNode.id)}><X size={12} /> Ungroup</button>
              </div>
            )}
            {selectedNode.kind === 'tx' && selectedNode.txMeta && (
              <div className="pt-2 border-t border-bg-border text-[10px] text-text-secondary space-y-1">
                <p><b>{selectedNode.txMeta.inputs.length}</b> inputs → <b>{selectedNode.txMeta.outputs.length}</b> outputs ({selectedNode.txMeta.asset})</p>
                <button className="btn-ghost w-full !py-1 !text-xs" onClick={() => navigate(`/tx-lens/AUTO/${encodeURIComponent(selectedNode.ref)}`)}><Split size={12} /> Full decode in TX Lens</button>
              </div>
            )}
          </div>
        )}

        {/* ── Edge inspector ── */}
        {selectedEdge && (
          <div className="w-[280px] border-l border-bg-border bg-bg-elevated/70 p-3 space-y-3 overflow-y-auto">
            <div className="flex items-center justify-between">
              <span className="text-[10px] uppercase tracking-widest text-text-muted">
                {selectedEdge.kind === 'relationship' ? 'Red string link' : 'Fund-flow edge'}
              </span>
              <button className="text-text-muted hover:text-red-400" title="Remove edge"
                onClick={() => { mutate((s) => ({ ...s, edges: s.edges.filter((x) => x.id !== selectedEdge.id) })); setSelection(new Set()) }}>
                <Trash2 size={12} />
              </button>
            </div>
            <p className="text-[10px] text-text-secondary">
              {nodeById.get(selectedEdge.source)?.label || '?'} → {nodeById.get(selectedEdge.target)?.label || '?'}
            </p>

            {selectedEdge.kind === 'relationship' ? (
              <>
                <label className="block text-[10px] text-text-muted">Relationship
                  <select className="input !py-1 !text-xs mt-1" value={selectedEdge.relationship || 'associates'}
                    onChange={(e) => patchEdge(selectedEdge.id, { relationship: e.target.value as RelationshipKind })}>
                    {RELATIONSHIP_KINDS.map((r) => <option key={r} value={r}>{REL_LABEL[r] || r}</option>)}
                  </select>
                </label>
                <label className="block text-[10px] text-text-muted">Confidence: <b style={{ color: THEME.edgeRelationship }}>{selectedEdge.confidence ?? 60}%</b>
                  <input type="range" min={0} max={100} step={5} className="w-full mt-1"
                    value={selectedEdge.confidence ?? 60}
                    onChange={(e) => patchEdge(selectedEdge.id, { confidence: Number(e.target.value) })} />
                </label>
                <label className="block text-[10px] text-text-muted">Custom label (overrides relationship text)
                  <input className="input !py-1 !text-xs mt-1" value={selectedEdge.label}
                    onChange={(e) => patchEdge(selectedEdge.id, { label: e.target.value })}
                    placeholder="e.g. shared KYC selfie" />
                </label>
                <div>
                  <span className="text-[10px] text-text-muted">String color</span>
                  <div className="flex gap-1.5 mt-1">
                    {['#ef4444', '#f59e0b', '#5b9fd6', '#10b981', '#8b80d4', '#8e9db5'].map((c) => (
                      <button key={c} className="w-5 h-5 rounded-full border"
                        style={{ background: c, borderColor: (selectedEdge.color || THEME.edgeRelationship) === c ? '#fff' : 'transparent' }}
                        onClick={() => patchEdge(selectedEdge.id, { color: c })} />
                    ))}
                  </div>
                </div>
              </>
            ) : (
              <>
                <div className="text-[10px] text-text-secondary space-y-1">
                  {selectedEdge.value > 0 && <p>Value: <b>{selectedEdge.value.toLocaleString(undefined, { maximumFractionDigits: 6 })} {selectedEdge.asset}</b></p>}
                  {selectedEdge.valueUsd != null && <p>USD at tx time: <b className="text-emerald-400">${selectedEdge.valueUsd.toLocaleString(undefined, { maximumFractionDigits: 2 })}</b></p>}
                  {selectedEdge.ts > 0 && <p>Time: {new Date(selectedEdge.ts * 1000).toISOString().slice(0, 16).replace('T', ' ')} UTC</p>}
                  {selectedEdge.txHash && <p className="font-mono break-all">{selectedEdge.txHash}</p>}
                </div>
                <label className="block text-[10px] text-text-muted">Label override
                  <input className="input !py-1 !text-xs mt-1" value={selectedEdge.label}
                    onChange={(e) => patchEdge(selectedEdge.id, { label: e.target.value })}
                    placeholder="e.g. ransom payment" />
                </label>
                {selectedEdge.txHash && (
                  <button className="btn-ghost w-full !py-1 !text-xs" onClick={() => navigate(`/tx-lens/AUTO/${encodeURIComponent(selectedEdge.txHash)}`)}><Globe size={12} /> Open TX detail</button>
                )}
              </>
            )}
          </div>
        )}

        {/* ── Zone inspector ── */}
        {selectedZone && (
          <div className="w-[280px] border-l border-bg-border bg-bg-elevated/70 p-3 space-y-3 overflow-y-auto">
            <div className="flex items-center justify-between">
              <span className="text-[10px] uppercase tracking-widest text-text-muted">Investigation zone</span>
              <button className="text-text-muted hover:text-red-400" title="Delete zone"
                onClick={() => { mutate((s) => ({ ...s, zones: (s.zones || []).filter((z) => z.id !== selectedZone.id) })); setSelection(new Set()) }}>
                <Trash2 size={12} />
              </button>
            </div>
            <label className="block text-[10px] text-text-muted">Zone name
              <input className="input !py-1 !text-xs mt-1" value={selectedZone.name} autoFocus
                onChange={(e) => patchZone(selectedZone.id, { name: e.target.value })}
                placeholder='e.g. "Layering", "Cash-out", "Victim funds"' />
            </label>
            <div>
              <span className="text-[10px] text-text-muted">Zone color</span>
              <div className="flex gap-1.5 mt-1">
                {ZONE_COLORS.map((c) => (
                  <button key={c} className="w-5 h-5 rounded-full border"
                    style={{ background: c, borderColor: selectedZone.color === c ? '#fff' : 'transparent' }}
                    onClick={() => patchZone(selectedZone.id, { color: c })} />
                ))}
              </div>
            </div>
            <p className="text-[9px] text-text-muted">Drag the title bar to move · drag the corner handle to resize.</p>
          </div>
        )}

        {/* ── Share drawer ── */}
        {showShare && (
          <div className="w-[320px] border-l border-bg-border bg-bg-elevated/80 p-4 space-y-4 overflow-y-auto">
            <div className="flex items-center justify-between">
              <h3 className="text-xs font-bold text-text-primary flex items-center gap-2"><Share2 size={13} /> {t('tools:boardCanvas.share.title')}</h3>
              <button onClick={() => setShowShare(false)} className="text-text-muted hover:text-text-primary"><X size={13} /></button>
            </div>
            <div className="space-y-2 text-xs">
              <div className="flex gap-2">
                <button className={`btn-ghost flex-1 !py-1 ${shareMode === 'public' ? '!text-neon-cyan' : ''}`} onClick={() => setShareMode('public')}><Link2 size={12} /> Public link</button>
                <button className={`btn-ghost flex-1 !py-1 ${shareMode === 'private' ? '!text-neon-cyan' : ''}`} onClick={() => setShareMode('private')}><Lock size={12} /> Password</button>
              </div>
              {shareMode === 'private' && (
                <input className="input !py-1.5 !text-xs" type="password" placeholder="Password for external party…"
                  value={sharePassword} onChange={(e) => setSharePassword(e.target.value)} />
              )}
              <label className="flex items-center gap-2 text-text-secondary">
                <input type="checkbox" checked={!shareLive} onChange={(e) => setShareLive(!e.target.checked)} />
                Frozen snapshot (court exhibit - SHA-256 sealed{shareMode === 'private' ? ', encrypted at rest' : ''})
              </label>
              <select className="input !py-1.5 !text-xs" value={shareExpiry} onChange={(e) => setShareExpiry(Number(e.target.value))}>
                <option value={0}>Never expires</option>
                <option value={24}>Expires in 24 hours</option>
                <option value={168}>Expires in 7 days</option>
                <option value={720}>Expires in 30 days</option>
              </select>
              <button className="btn-primary w-full !py-1.5" onClick={makeShare} disabled={shareMode === 'private' && !sharePassword}>
                <Users size={13} /> Create {shareMode} link
              </button>
              {newShare && (
                <div className="p-2 rounded border border-emerald-700/50 bg-emerald-900/20 space-y-1">
                  <p className="text-emerald-300 text-[10px]">Read-only link created{newShare.encrypted_at_rest ? ' · snapshot encrypted at rest' : ''}:</p>
                  <div className="flex items-center gap-1">
                    <code className="text-[9px] break-all flex-1 text-text-secondary">{window.location.origin}/board-share/{newShare.token}</code>
                    <button className="btn-ghost !p-1" onClick={() => copyLink(newShare.token)}>{copied === newShare.token ? <Check size={11} /> : <Copy size={11} />}</button>
                  </div>
                </div>
              )}
            </div>
            <div className="pt-2 border-t border-bg-border">
              <p className="text-[10px] uppercase tracking-widest text-text-muted mb-2">Active links</p>
              {shares.filter((s) => !s.revoked).length === 0 && <p className="text-[11px] text-text-muted">No active share links.</p>}
              {shares.filter((s) => !s.revoked).map((s) => (
                <div key={s.token} className="flex items-center gap-2 py-1.5 border-b border-bg-border/50 text-[10px]">
                  {s.mode === 'private' ? <Lock size={11} className="text-amber-400" /> : <Link2 size={11} className="text-neon-cyan" />}
                  <span className="flex-1 text-text-secondary">{s.mode} · {s.live ? 'live' : 'snapshot'} · {s.access_count} views{s.expires_at ? ` · exp ${s.expires_at.slice(0, 10)}` : ''}</span>
                  <button className="btn-ghost !p-1" title="Copy" onClick={() => copyLink(s.token)}>{copied === s.token ? <Check size={10} /> : <Copy size={10} />}</button>
                  <button className="btn-ghost !p-1 !text-red-400" title="Revoke"
                    onClick={() => revokeShare(s.token).then(() => listShares(id).then(setShares))}><X size={10} /></button>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* ── Comments drawer ── */}
        {showComments && (
          <div className="w-[320px] border-l border-bg-border bg-bg-elevated/80 p-4 space-y-3 overflow-y-auto">
            <div className="flex items-center justify-between">
              <h3 className="text-xs font-bold text-text-primary flex items-center gap-2"><MessageSquare size={13} /> {t('tools:boardCanvas.comments.title')}</h3>
              <button onClick={() => setShowComments(false)} className="text-text-muted hover:text-text-primary"><X size={13} /></button>
            </div>
            <div className="space-y-2">
              {comments.length === 0 && <p className="text-[11px] text-text-muted">No comments yet. Leave notes for the next investigator on this board.</p>}
              {comments.map((c) => {
                const anchor = c.node_ref ? nodeById.get(c.node_ref) : undefined
                const accentColor = anchor ? (ENTITY_META[anchor.kind]?.color || THEME.selected) : THEME.textMuted
                return (
                  <div key={c.id}
                    className={`relative overflow-hidden rounded-lg border text-[11px] ${c.resolved ? 'border-emerald-500/20 bg-emerald-500/3' : 'border-bg-border bg-bg-secondary/40'}`}
                    style={{ borderLeftWidth: 3, borderLeftColor: c.resolved ? '#22c55e' : accentColor }}>
                    <div className="flex items-center justify-between text-[9px] px-2 pt-1.5 pb-0.5">
                      <span className="font-semibold text-text-primary">{c.author || 'analyst'}</span>
                      <span className="text-text-muted">{String(c.created_at).slice(0, 16).replace('T', ' ')}</span>
                    </div>
                    {anchor && (
                      <div className="flex items-center gap-1 px-2 py-0.5">
                        <span className="inline-block w-1.5 h-1.5 rounded-full" style={{ backgroundColor: accentColor }} />
                        <span className="text-[9px] font-medium text-text-muted">
                          ↳ {anchor.caption || anchor.label}
                        </span>
                      </div>
                    )}
                    <p className={`px-2 pb-1.5 pt-0.5 whitespace-pre-wrap ${c.resolved ? 'text-text-muted line-through' : 'text-text-secondary'}`}>{c.body}</p>
                    <div className="flex items-center justify-between px-2 py-1 border-t border-bg-border/40">
                      {c.resolved ? (
                        <span className="text-[9px] font-semibold text-emerald-400 flex items-center gap-1">✓ Resolved</span>
                      ) : (
                        <span className="text-[9px] text-text-muted">Open</span>
                      )}
                      {!c.resolved && (
                        <button className="text-[9px] text-emerald-400 hover:text-emerald-300 hover:underline" onClick={() => resolveComment(c.id).then(() => listComments(id).then(setComments))}>Resolve</button>
                      )}
                    </div>
                  </div>
                )
              })}
            </div>
            <div className="pt-2 border-t border-bg-border space-y-2">
              {selectedNode && <p className="text-[9px] text-neon-cyan">Anchored to: {selectedNode.caption || selectedNode.label}</p>}
              <textarea className="input !text-xs resize-none" rows={3} placeholder="Handoff note for the team…"
                value={commentBody} onChange={(e) => setCommentBody(e.target.value)} />
              <button className="btn-primary w-full !py-1.5" disabled={!commentBody.trim()}
                onClick={() => addComment(id, commentBody.trim(), selectedNode?.id || '').then(() => { setCommentBody(''); listComments(id).then(setComments) })}>
                Post comment
              </button>
            </div>
          </div>
        )}
      </div>

      {/* ── Context menu ── */}
      {menu && (
        <div className="fixed z-[130] w-56 rounded-lg border border-bg-border bg-bg-elevated shadow-2xl py-1 text-xs"
          style={{ left: Math.min(menu.x, window.innerWidth - 240), top: Math.min(menu.y, window.innerHeight - 260) }}
          onMouseDown={(e) => e.stopPropagation()}>
          {menu.nodeId && (() => {
            const n = nodeById.get(menu.nodeId!)
            if (!n) return null
            return (
              <>
                <MenuBtn icon={<Spline size={12} />} label="Red string from here"
                  onClick={() => { setMode('link'); setLinkFrom(n.id); setMenu(null) }} />
                {n.kind === 'address' && (
                  <>
                    <MenuBtn icon={<Expand size={12} />} label="Expand 1 hop" onClick={() => expandNode(n.id)} />
                    <MenuBtn icon={<Globe size={12} />} label="Address Intel" onClick={() => navigate(`/intel/${n.ref}`)} />
                    <MenuBtn icon={<ShieldAlert size={12} />} label="OSINT sweep" onClick={() => navigate(`/osint/${n.ref}`)} />
                  </>
                )}
                {(n.kind === 'address' || ENTITY_META[n.kind]) && (
                  <MenuBtn icon={<Pin size={12} />} label={n.priority ? 'Unmark priority' : 'Mark as priority'}
                    onClick={() => { patchNode(n.id, { priority: !n.priority }); setMenu(null) }} />
                )}
                {n.kind === 'cluster' && (
                  <>
                    <MenuBtn icon={n.collapsed ? <ChevronDown size={12} /> : <ChevronUp size={12} />} label={n.collapsed ? 'Expand members' : 'Collapse members'} onClick={() => { toggleCluster(n.id); setMenu(null) }} />
                    <MenuBtn icon={<X size={12} />} label="Ungroup" onClick={() => ungroup(n.id)} danger />
                  </>
                )}
                {n.kind === 'tx' && <MenuBtn icon={<Split size={12} />} label="Full decode in TX Lens" onClick={() => navigate(`/tx-lens?hash=${n.ref}`)} />}
                <MenuBtn icon={<Trash2 size={12} />} label="Remove from board" danger onClick={() => { setSelection(new Set([n.id])); deleteSelection(); setMenu(null) }} />
              </>
            )
          })()}
          {menu.edgeId && (() => {
            const e = st.edges.find((x) => x.id === menu.edgeId)
            if (!e) return null
            const srcChain = nodeById.get(e.source)?.chain || nodeById.get(e.target)?.chain || 'eth'
            return (
              <>
                {e.txHash && (
                  <MenuBtn icon={<Split size={12} />} label={srcChain === 'btc' ? 'Split into UTXO tx node' : 'Split tx (internal transfers)'}
                    onClick={() => addTxNode(e.txHash, e.id, srcChain === 'btc' ? 'BTC' : undefined)} />
                )}
                {e.txHash && <MenuBtn icon={<Globe size={12} />} label="Open TX detail" onClick={() => navigate(`/tx-lens/AUTO/${encodeURIComponent(e.txHash)}`)} />}
                <MenuBtn icon={<Trash2 size={12} />} label="Remove edge" danger
                  onClick={() => { mutate((s) => ({ ...s, edges: s.edges.filter((x) => x.id !== e.id) })); setMenu(null) }} />
              </>
            )
          })()}
          {menu.zoneId && (
            <MenuBtn icon={<Trash2 size={12} />} label="Delete zone" danger
              onClick={() => { mutate((s) => ({ ...s, zones: (s.zones || []).filter((z) => z.id !== menu.zoneId) })); setMenu(null); setSelection(new Set()) }} />
          )}
        </div>
      )}
    </div>
  )
}

// ── Minimap ───────────────────────────────────────────────────────────────────

function Minimap({ nodes, zones, view, svgRef, onJump }: {
  nodes: BoardNode[]; zones: BoardZone[]; view: { x: number; y: number; z: number }
  svgRef: React.RefObject<SVGSVGElement>; onJump: (x: number, y: number) => void
}) {
  const W = 168; const H = 112
  if (nodes.length === 0) return null
  const xs = nodes.map((n) => n.x); const ys = nodes.map((n) => n.y)
  let minX = Math.min(...xs); let maxX = Math.max(...xs)
  let minY = Math.min(...ys); let maxY = Math.max(...ys)
  for (const z of zones) {
    minX = Math.min(minX, z.x); maxX = Math.max(maxX, z.x + z.w)
    minY = Math.min(minY, z.y); maxY = Math.max(maxY, z.y + z.h)
  }
  minX -= 120; maxX += 120; minY -= 100; maxY += 100
  const s = Math.min(W / (maxX - minX), H / (maxY - minY))
  const ox = (W - s * (maxX - minX)) / 2
  const oy = (H - s * (maxY - minY)) / 2
  const px = (wx: number) => ox + (wx - minX) * s
  const py = (wy: number) => oy + (wy - minY) * s

  const rect = svgRef.current?.getBoundingClientRect()
  const vp = rect ? {
    x: px((0 - view.x) / view.z), y: py((0 - view.y) / view.z),
    w: (rect.width / view.z) * s, h: (rect.height / view.z) * s,
  } : null

  return (
    <div className="absolute bottom-3 right-3 z-[120] rounded-lg border border-bg-border bg-bg-elevated/90 shadow-xl overflow-hidden"
      style={{ width: W, height: H }}>
      <svg width={W} height={H} style={{ cursor: 'pointer', display: 'block' }}
        onMouseDown={(e) => {
          const r = (e.currentTarget as SVGSVGElement).getBoundingClientRect()
          const mx = e.clientX - r.left; const my = e.clientY - r.top
          onJump(minX + (mx - ox) / s, minY + (my - oy) / s)
        }}>
        {zones.map((z) => (
          <rect key={z.id} x={px(z.x)} y={py(z.y)} width={z.w * s} height={z.h * s} rx={2}
            fill={`${z.color}22`} stroke={`${z.color}66`} strokeWidth={0.6} />
        ))}
        {nodes.map((n) => (
          <circle key={n.id} cx={px(n.x)} cy={py(n.y)} r={ENTITY_META[n.kind] ? 2.4 : 1.8}
            fill={n.color || '#8e9db5'} opacity={0.9} />
        ))}
        {vp && (
          <rect x={vp.x} y={vp.y} width={vp.w} height={vp.h}
            fill="rgba(150,161,181,0.10)" stroke={THEME.selected} strokeWidth={1} />
        )}
      </svg>
    </div>
  )
}

function MenuBtn({ icon, label, onClick, danger }: { icon: React.ReactNode; label: string; onClick: () => void; danger?: boolean }) {
  return (
    <button className={`w-full flex items-center gap-2 px-3 py-1.5 text-left hover:bg-bg-secondary ${danger ? 'text-red-400' : 'text-text-secondary hover:text-text-primary'}`}
      onClick={onClick}>
      {icon}{label}
    </button>
  )
}
