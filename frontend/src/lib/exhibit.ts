/**
 * Court-presentable graph exhibits.
 *
 * Renders an investigation graph (SVG element) into a print-ready exhibit page
 * with case header, legend, UTC timestamp, and the SHA-256 of the underlying
 * graph data - then optionally registers the exhibit into the evidence vault's
 * tamper-evident custody chain.
 *
 * PDF: the exhibit opens in a print window (Ctrl+P → "Save as PDF").
 * PNG: rendered via canvas and downloaded directly.
 */
import { registerExport } from '../api/client'

export interface ExhibitMeta {
  title: string
  caseId?: string
  caseName?: string
  subject: string
  chain?: string
  analyst?: string
  tool?: string
  legend?: { color: string; label: string }[]
  /** The raw data the graph was drawn from - hashed for the exhibit. */
  data: unknown
}

export async function sha256Hex(text: string): Promise<string> {
  const buf = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(text))
  return Array.from(new Uint8Array(buf)).map(b => b.toString(16).padStart(2, '0')).join('')
}

function svgToDataUrl(svg: SVGSVGElement): string {
  const clone = svg.cloneNode(true) as SVGSVGElement
  clone.setAttribute('xmlns', 'http://www.w3.org/2000/svg')
  if (!clone.getAttribute('width')) {
    const vb = (clone.getAttribute('viewBox') || '0 0 900 480').split(/\s+/)
    clone.setAttribute('width', vb[2] || '900')
    clone.setAttribute('height', vb[3] || '480')
  }
  const xml = new XMLSerializer().serializeToString(clone)
  return `data:image/svg+xml;charset=utf-8,${encodeURIComponent(xml)}`
}

export async function downloadGraphPng(svg: SVGSVGElement, filename: string, scale = 2): Promise<void> {
  const url = svgToDataUrl(svg)
  const img = new Image()
  await new Promise<void>((resolve, reject) => {
    img.onload = () => resolve()
    img.onerror = () => reject(new Error('SVG rasterization failed'))
    img.src = url
  })
  const canvas = document.createElement('canvas')
  canvas.width = img.naturalWidth * scale
  canvas.height = img.naturalHeight * scale
  const ctx = canvas.getContext('2d')!
  ctx.fillStyle = '#0a0608'
  ctx.fillRect(0, 0, canvas.width, canvas.height)
  ctx.scale(scale, scale)
  ctx.drawImage(img, 0, 0)
  const a = document.createElement('a')
  a.href = canvas.toDataURL('image/png')
  a.download = filename
  a.click()
}

/**
 * Open a print-ready exhibit page (case header + graph + legend + hash) and
 * register the exhibit in the custody chain when a caseId is provided.
 * Returns the SHA-256 of the underlying data and custody info (if registered).
 */
export async function exportExhibit(
  svg: SVGSVGElement,
  meta: ExhibitMeta,
): Promise<{ dataSha256: string; custody?: { evidence_id?: string; chain_hash?: string } }> {
  const dataJson = JSON.stringify(meta.data ?? {})
  const dataSha256 = await sha256Hex(dataJson)
  const generatedAt = new Date().toISOString()
  const imgUrl = svgToDataUrl(svg)

  let custody: { evidence_id?: string; chain_hash?: string } | undefined
  if (meta.caseId) {
    try {
      const res = await registerExport(meta.caseId, {
        kind: 'graph_exhibit',
        title: meta.title,
        content: { data_sha256: dataSha256, subject: meta.subject, generated_at: generatedAt, tool: meta.tool || 'CrypTX' },
        subject: meta.subject,
        actor: meta.analyst || 'analyst',
      })
      custody = { evidence_id: res.evidence.id, chain_hash: (res.evidence as { chain_hash?: string }).chain_hash }
    } catch {
      custody = undefined
    }
  }

  const legendHtml = (meta.legend || [])
    .map(l => `<span class="lg"><i style="background:${l.color}"></i>${l.label}</span>`)
    .join('')

  const html = `<!doctype html>
<html><head><meta charset="utf-8"><title>${meta.title}</title>
<style>
  @page { size: A4 landscape; margin: 14mm; }
  body { font-family: Arial, Helvetica, sans-serif; color: #111827; margin: 0; }
  .head { display: flex; justify-content: space-between; border-bottom: 3px solid #111827; padding-bottom: 8px; }
  .head h1 { font-size: 17px; margin: 0; text-transform: uppercase; letter-spacing: .06em; }
  .head .case { text-align: right; font-size: 11px; color: #374151; }
  .meta { display: flex; gap: 18px; flex-wrap: wrap; font-size: 11px; color: #374151; margin: 8px 0; }
  .meta b { color: #111827; }
  img.graph { width: 100%; border: 1px solid #d1d5db; border-radius: 4px; background: #0a0608; }
  .legend { margin-top: 8px; font-size: 11px; display: flex; gap: 14px; flex-wrap: wrap; }
  .lg i { display: inline-block; width: 10px; height: 10px; border-radius: 50%; margin-right: 5px; }
  .hash { margin-top: 10px; font-family: 'Courier New', monospace; font-size: 10px; color: #374151;
          border: 1px solid #d1d5db; border-radius: 4px; padding: 7px 9px; word-break: break-all; }
  .foot { margin-top: 8px; font-size: 9.5px; color: #6b7280; }
  .print-hint { position: fixed; top: 8px; right: 8px; background: #111827; color: #fff; padding: 6px 12px;
                border-radius: 6px; font-size: 12px; cursor: pointer; }
  @media print { .print-hint { display: none } }
</style></head>
<body>
  <div class="print-hint" onclick="window.print()">Print / Save as PDF</div>
  <div class="head">
    <h1>${meta.title}</h1>
    <div class="case">
      ${meta.caseName || meta.caseId ? `<div><b>Case:</b> ${meta.caseName || meta.caseId}</div>` : ''}
      <div><b>Generated:</b> ${generatedAt}</div>
      <div><b>Analyst:</b> ${meta.analyst || 'unattributed'}</div>
    </div>
  </div>
  <div class="meta">
    <span><b>Subject:</b> <code>${meta.subject}</code></span>
    ${meta.chain ? `<span><b>Chain:</b> ${meta.chain}</span>` : ''}
    <span><b>Tool:</b> ${meta.tool || 'CrypTX'} (local evidence-first pipeline)</span>
  </div>
  <img class="graph" src="${imgUrl}" alt="investigation graph" />
  ${legendHtml ? `<div class="legend">${legendHtml}</div>` : ''}
  <div class="hash">
    <b>SHA-256 of underlying graph data:</b> ${dataSha256}<br/>
    ${custody?.chain_hash ? `<b>Custody chain hash:</b> ${custody.chain_hash} (registered in evidence vault${custody.evidence_id ? `, artifact ${custody.evidence_id}` : ''})` : '<i>Not registered in a case evidence vault (no case selected).</i>'}
  </div>
  <div class="foot">
    This exhibit was generated from on-chain data by deterministic local algorithms. Labels marked heuristic are
    investigative leads, not conclusions. Verify the data hash against the registered evidence artifact before relying
    on this exhibit.
  </div>
</body></html>`

  const win = window.open('', '_blank', 'width=1200,height=800')
  if (win) {
    win.document.write(html)
    win.document.close()
  }
  return { dataSha256, custody }
}
