import { useEffect, useRef, useState, useCallback } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { RefreshCw, ZoomIn, ZoomOut, Maximize2, Wifi, WifiOff, Lock, Unlock, GitBranch, Network } from 'lucide-react'
import ForceGraph2D from 'react-force-graph-2d'
import ReasoningChain from './ReasoningChain'
import { NODE_COLOR, NODE_SIZE, LAYER_ORDER } from '../utils/constants'
import { getGraphData } from '../utils/api'

const LAYER_Y = Object.fromEntries(LAYER_ORDER.map((t, i) => [t, (i + 1) * 120]))

const GRAPH_MODES = [
  { id: 'reasoning', label: 'Reasoning Chain', icon: GitBranch },
  { id: 'all',       label: 'All Nodes',       icon: Network },
]

const FILTERS = [
  { id: 'all',      label: 'All Nodes' },
  { id: 'routers',  label: 'Routers Only' },
  { id: 'profiles', label: 'Node Profiles' },
]

const FILTER_TYPES = {
  all:      null,
  routers:  ['RouterModel', 'RouterFeature', 'OperationalImplication'],
  profiles: ['NodeProfile', 'DeploymentPattern', 'InfraRequirement'],
}

function edgeStyle(link) {
  const w = link.base_weight ?? link.fit_score ?? (link.priority ? 1 / link.priority : null)
  if (w == null) return { color: 'rgba(255,255,255,0.12)', width: 1 }
  return {
    color: `rgba(255,255,255,${(0.15 + w * 0.7).toFixed(2)})`,
    width: 0.8 + w * 2.5,
    weight: w,
  }
}

function weightBadge(w) {
  if (w >= 0.7) return { text: 'very strong', color: '#00ff88' }
  if (w >= 0.6) return { text: 'strong',      color: '#a8ff78' }
  if (w >= 0.4) return { text: 'moderate',    color: '#ffd700' }
  return              { text: 'weak',          color: '#ff8c42' }
}

function EdgeLegend() {
  return (
    <div style={{
      position: 'absolute', bottom: 56, left: 12, zIndex: 10,
      background: 'var(--bg-secondary)', border: '1px solid var(--border)',
      borderRadius: 10, padding: '10px 14px',
    }}>
      <div style={{ fontSize: 10, color: 'var(--text-muted)', marginBottom: 8, letterSpacing: '1px', textTransform: 'uppercase' }}>
        Edge Weight
      </div>
      {[
        { label: 'Very strong  ≥ 0.70', w: 0.75 },
        { label: 'Strong       ≥ 0.60', w: 0.62 },
        { label: 'Moderate     ≥ 0.40', w: 0.45 },
        { label: 'Weak         < 0.40', w: 0.20 },
      ].map(({ label, w }) => {
        const s = edgeStyle({ base_weight: w })
        return (
          <div key={label} style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 5 }}>
            <div style={{ width: 28, height: s.width + 1, background: s.color, borderRadius: 2 }} />
            <span style={{ fontSize: 10, color: 'var(--text-muted)' }}>{label}</span>
          </div>
        )
      })}
    </div>
  )
}

export default function GraphViewer({ highlightIds, newestRouterId, onBack, onClearHighlight }) {
  const fgRef                         = useRef()
  const [graphData, setGraphData]     = useState({ nodes: [], links: [] })
  const [loading,   setLoading]       = useState(false)   // false until All Nodes tab opened
  const [selected,  setSelected]      = useState(null)
  const [filter,    setFilter]        = useState('all')
  const [error,     setError]         = useState(false)
  const [frozen,    setFrozen]        = useState(false)
  const [hoveredLink, setHoveredLink] = useState(null)
  const [graphMode, setGraphMode]     = useState('reasoning')

  const fetchGraph = useCallback(async () => {
    setLoading(true)
    try {
      const raw   = await getGraphData()
      const nodes = raw.nodes.map(n => ({
        ...n,
        color:        NODE_COLOR[n.type] || '#888',
        size:         NODE_SIZE[n.type]  || 6,
        fy:           LAYER_Y[n.type] ?? null,
        displayLabel: (n.label?.length > 20 ? n.label.slice(0, 18) + '..' : n.label) || '',
      }))
      setGraphData({ nodes, links: raw.links })
      setError(false)
    } catch {
      setError(true)
    } finally {
      setLoading(false)
    }
  }, [])

  // Only fetch when user switches to All Nodes — not on mount
  useEffect(() => {
    if (graphMode === 'all' && !graphData.nodes.length) fetchGraph()
  }, [graphMode, fetchGraph])

  // Spread nodes horizontally within each layer
  useEffect(() => {
    if (!graphData.nodes.length) return
    const byLayer = {}
    graphData.nodes.forEach(n => {
      const y = LAYER_Y[n.type]
      if (y == null) return
      ;(byLayer[y] = byLayer[y] || []).push(n)
    })
    Object.values(byLayer).forEach(group => {
      const step = 900 / (group.length + 1)
      group.forEach((n, i) => { n.fx = (i + 1) * step - 450 })
    })
  }, [graphData])

  const toggleFreeze = useCallback(() => {
    setFrozen(prev => {
      if (prev) fgRef.current?.d3ReheatSimulation()
      return !prev
    })
  }, [])

  const filteredData = (() => {
    const types = FILTER_TYPES[filter]
    if (!types) return graphData
    const nodeIds = new Set(graphData.nodes.filter(n => types.includes(n.type)).map(n => n.id))
    return {
      nodes: graphData.nodes.filter(n => nodeIds.has(n.id)),
      links: graphData.links.filter(l =>
        nodeIds.has(typeof l.source === 'object' ? l.source.id : l.source) &&
        nodeIds.has(typeof l.target === 'object' ? l.target.id : l.target)
      ),
    }
  })()

  const highlightSet = new Set(highlightIds || [])

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>

      {/* Mode switcher */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 12 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          {/* Back button */}
          {onBack && (
            <button onClick={onBack} style={{
              display: 'flex', alignItems: 'center', gap: 6,
              padding: '6px 12px', borderRadius: 8, cursor: 'pointer',
              background: 'var(--bg-card)', border: '1px solid var(--border)',
              color: 'var(--text-muted)', fontSize: 12, fontWeight: 500,
            }}>
              ← Plan Generator
            </button>
          )}
          <div style={{ display: 'flex', gap: 4, background: 'var(--bg-card)', border: '1px solid var(--border)', borderRadius: 10, padding: 4 }}>
          {GRAPH_MODES.map(m => {
            const Icon = m.icon
            return (
              <motion.button key={m.id} whileTap={{ scale: 0.96 }} onClick={() => setGraphMode(m.id)} style={{
                display: 'flex', alignItems: 'center', gap: 6,
                padding: '6px 14px', borderRadius: 7, fontSize: 12,
                cursor: 'pointer', fontWeight: 500, border: 'none',
                background: graphMode === m.id ? 'linear-gradient(135deg, var(--accent), var(--purple))' : 'transparent',
                color: graphMode === m.id ? '#fff' : 'var(--text-muted)',
                boxShadow: graphMode === m.id ? '0 0 12px var(--accent-glow)' : 'none',
              }}>
                <Icon size={12} />{m.label}
              </motion.button>
            )
          })}
          </div>
        </div>

        {graphMode === 'all' && (
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              {error ? <WifiOff size={13} color="var(--red)" /> : <Wifi size={13} color="var(--green)" />}
              <span style={{ fontSize: 11, color: error ? 'var(--red)' : 'var(--green)' }}>
                {error ? 'Disconnected' : 'Live'}
              </span>
            </div>
            <div style={{ fontSize: 11, color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>
              {filteredData.nodes.length} nodes · {filteredData.links.length} edges
            </div>
            <motion.button whileHover={{ scale: 1.05 }} whileTap={{ scale: 0.95 }} onClick={toggleFreeze} style={{
              display: 'flex', alignItems: 'center', gap: 6, padding: '6px 12px', borderRadius: 8, cursor: 'pointer',
              background: frozen ? 'var(--accent)' : 'var(--bg-card)',
              border: `1px solid ${frozen ? 'var(--accent)' : 'var(--border)'}`,
              color: frozen ? '#fff' : 'var(--text-muted)', fontSize: 12,
            }}>
              {frozen ? <Lock size={12} /> : <Unlock size={12} />}
              {frozen ? 'Frozen' : 'Freeze'}
            </motion.button>
            <motion.button whileHover={{ scale: 1.05 }} whileTap={{ scale: 0.95 }} onClick={fetchGraph} style={{
              display: 'flex', alignItems: 'center', gap: 6, padding: '6px 12px', borderRadius: 8, cursor: 'pointer',
              background: 'var(--bg-card)', border: '1px solid var(--border)', color: 'var(--text-muted)', fontSize: 12,
            }}>
              <RefreshCw size={12} /> Refresh
            </motion.button>
          </div>
        )}
      </div>

      {/* Reasoning Chain mode */}
      {graphMode === 'reasoning' && (
        <div style={{ minHeight: 600 }}>
          <ReasoningChain newestRouterId={newestRouterId} />
        </div>
      )}

      {/* All Nodes force graph mode */}
      {graphMode === 'all' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          {/* Sub-filters */}
          <div style={{ display: 'flex', gap: 4 }}>
            {FILTERS.map(f => (
              <motion.button key={f.id} whileTap={{ scale: 0.96 }} onClick={() => setFilter(f.id)} style={{
                padding: '5px 12px', borderRadius: 6, fontSize: 11, cursor: 'pointer', fontWeight: 500, border: 'none',
                background: filter === f.id ? 'var(--bg-card)' : 'transparent',
                color: filter === f.id ? 'var(--text-primary)' : 'var(--text-muted)',
                outline: `1px solid ${filter === f.id ? 'var(--border-bright)' : 'transparent'}`,
              }}>
                {f.label}
              </motion.button>
            ))}
          </div>

          <div style={{ display: 'flex', gap: 16, alignItems: 'flex-start' }}>
            {/* Layer axis */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: 0, paddingTop: 8, flexShrink: 0, width: 160 }}>
              {LAYER_ORDER.filter(t => !FILTER_TYPES[filter] || FILTER_TYPES[filter].includes(t)).map(type => (
                <div key={type} style={{
                  height: 120, display: 'flex', alignItems: 'center', gap: 8, paddingLeft: 8,
                  borderLeft: `2px solid ${NODE_COLOR[type]}30`,
                }}>
                  <div style={{ width: 8, height: 8, borderRadius: '50%',
                    background: NODE_COLOR[type], boxShadow: `0 0 6px ${NODE_COLOR[type]}`, flexShrink: 0 }} />
                  <span style={{ fontSize: 11, color: 'var(--text-muted)', lineHeight: 1.3 }}>{type}</span>
                </div>
              ))}
            </div>

            {/* Graph canvas */}
            <div style={{
              flex: 1, background: 'var(--bg-card)', border: '1px solid var(--border)',
              borderRadius: 16, overflow: 'hidden', position: 'relative',
              height: LAYER_ORDER.length * 120 + 40,
            }}>
              <AnimatePresence>
                {loading && (
                  <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
                    style={{ position: 'absolute', inset: 0, zIndex: 10, display: 'flex', flexDirection: 'column',
                      alignItems: 'center', justifyContent: 'center', gap: 16, background: 'rgba(5,8,16,0.9)' }}>
                    <motion.div animate={{ rotate: 360 }} transition={{ duration: 1, repeat: Infinity, ease: 'linear' }}
                      style={{ width: 40, height: 40, borderRadius: '50%', border: '3px solid var(--border)', borderTopColor: 'var(--accent)' }} />
                    <span style={{ fontSize: 13, color: 'var(--text-muted)' }}>Loading knowledge graph...</span>
                  </motion.div>
                )}
              </AnimatePresence>

              {/* Hovered edge tooltip */}
              <AnimatePresence>
                {hoveredLink && (
                  <motion.div initial={{ opacity: 0, y: -4 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }}
                    style={{
                      position: 'absolute', top: 12, left: '50%', transform: 'translateX(-50%)',
                      zIndex: 20, background: 'var(--bg-secondary)', border: '1px solid var(--border)',
                      borderRadius: 8, padding: '6px 14px', fontSize: 11, color: 'var(--text-secondary)',
                      fontFamily: 'var(--font-mono)', pointerEvents: 'none',
                      display: 'flex', gap: 12, alignItems: 'center',
                    }}>
                    <span style={{ color: 'var(--accent)' }}>{hoveredLink.label}</span>
                    {hoveredLink.base_weight != null && (() => {
                      const b = weightBadge(hoveredLink.base_weight)
                      return (
                        <>
                          <span style={{ color: b.color, fontWeight: 700 }}>{hoveredLink.base_weight.toFixed(2)}</span>
                          <span style={{ color: b.color }}>({b.text})</span>
                        </>
                      )
                    })()}
                    {hoveredLink.fit_score != null && <span style={{ color: '#ffd700' }}>fit: {hoveredLink.fit_score.toFixed(2)}</span>}
                    {hoveredLink.priority  != null && <span style={{ color: '#ff8c42' }}>priority: {hoveredLink.priority}</span>}
                  </motion.div>
                )}
              </AnimatePresence>

              <ForceGraph2D
                ref={fgRef}
                graphData={filteredData}
                backgroundColor="#050810"
                nodeLabel={() => ''}
                linkColor={l => {
                  const s = edgeStyle(l)
                  if (highlightSet.size > 0) {
                    const sid = typeof l.source === 'object' ? l.source.id : l.source
                    const tid = typeof l.target === 'object' ? l.target.id : l.target
                    // Subtle dim — keep edges readable, just slightly faded
                    if (!highlightSet.has(sid) || !highlightSet.has(tid)) return 'rgba(255,255,255,0.08)'
                  }
                  return s.color
                }}
                linkWidth={l => {
                  if (highlightSet.size > 0) {
                    const sid = typeof l.source === 'object' ? l.source.id : l.source
                    const tid = typeof l.target === 'object' ? l.target.id : l.target
                    if (!highlightSet.has(sid) || !highlightSet.has(tid)) return 0.8
                  }
                  return edgeStyle(l).width
                }}
                linkDirectionalArrowLength={5}
                linkDirectionalArrowRelPos={1}
                onLinkHover={setHoveredLink}
                onNodeClick={node => setSelected(prev => prev?.id === node.id ? null : node)}
                cooldownTicks={200}
                onEngineStop={() => setFrozen(true)}
                nodeCanvasObject={(node, ctx, globalScale) => {
                  const r       = node.size || 6
                  const isNew   = newestRouterId && node.id === `RouterModel_${newestRouterId}`
                  // Subtle de-emphasis: opacity 0.45 instead of hard #333
                  const dimmed  = highlightSet.size > 0 && !highlightSet.has(node.id)
                  const color   = node.color || '#888'
                  const alpha   = dimmed ? 0.45 : 1

                  ctx.save()
                  ctx.globalAlpha = alpha

                  // Glow ring for NEW router
                  if (isNew) {
                    ctx.beginPath(); ctx.arc(node.x, node.y, r + 8, 0, 2 * Math.PI)
                    ctx.strokeStyle = '#00ff88'; ctx.lineWidth = 2
                    ctx.shadowColor = '#00ff88'; ctx.shadowBlur = 12
                    ctx.stroke()
                    ctx.shadowBlur = 0
                  }

                  // Outer glow
                  ctx.beginPath(); ctx.arc(node.x, node.y, r + 5, 0, 2 * Math.PI)
                  ctx.fillStyle = color + '18'; ctx.fill()

                  // Node body
                  ctx.beginPath(); ctx.arc(node.x, node.y, r, 0, 2 * Math.PI)
                  ctx.fillStyle = color; ctx.fill()

                  // Selected ring
                  if (selected?.id === node.id) {
                    ctx.beginPath(); ctx.arc(node.x, node.y, r + 3, 0, 2 * Math.PI)
                    ctx.strokeStyle = '#fff'; ctx.lineWidth = 1.5; ctx.stroke()
                  }

                  // Label
                  const fontSize = Math.max(7, 10 / globalScale)
                  ctx.font = `${fontSize}px Inter`
                  ctx.fillStyle = 'rgba(232,240,254,0.85)'
                  ctx.textAlign = 'center'
                  ctx.fillText(node.displayLabel, node.x, node.y + r + fontSize + 2)

                  // NEW badge
                  if (isNew) {
                    const badgeY = node.y - r - 4
                    ctx.font = `bold ${Math.max(6, 8 / globalScale)}px Inter`
                    ctx.fillStyle = '#00ff88'
                    ctx.textAlign = 'center'
                    ctx.fillText('NEW', node.x, badgeY)
                  }

                  ctx.restore()
                }}
              />

              {/* Zoom controls */}
              <div style={{ position: 'absolute', bottom: 16, right: 16, display: 'flex', flexDirection: 'column', gap: 6 }}>
                {[
                  { Icon: ZoomIn,    fn: () => fgRef.current?.zoom(1.5, 300) },
                  { Icon: ZoomOut,   fn: () => fgRef.current?.zoom(0.67, 300) },
                  { Icon: Maximize2, fn: () => fgRef.current?.zoomToFit(400, 40) },
                ].map(({ Icon, fn }, i) => (
                  <motion.button key={i} whileHover={{ scale: 1.1 }} whileTap={{ scale: 0.9 }} onClick={fn} style={{
                    width: 32, height: 32, borderRadius: 8, background: 'var(--bg-secondary)',
                    border: '1px solid var(--border)', cursor: 'pointer',
                    display: 'flex', alignItems: 'center', justifyContent: 'center',
                  }}>
                    <Icon size={13} color="var(--text-muted)" />
                  </motion.button>
                ))}
              </div>

              {!loading && !error && graphData.nodes.length === 0 && (
                <div style={{ position: 'absolute', inset: 0, display: 'flex',
                  alignItems: 'center', justifyContent: 'center',
                  fontSize: 13, color: 'var(--text-muted)', padding: 24, textAlign: 'center' }}>
                  Graph is empty — generate a plan first to populate the knowledge graph.
                </div>
              )}

              {/* Clear highlight button */}
              {highlightSet.size > 0 && (
                <button
                  onClick={onClearHighlight}
                  style={{
                    position: 'absolute', top: 12, left: 12, zIndex: 10,
                    padding: '5px 12px', borderRadius: 6, cursor: 'pointer',
                    background: 'var(--bg-secondary)', border: '1px solid var(--border)',
                    fontSize: 11, color: 'var(--text-muted)',
                  }}
                >
                  ✕ Clear Highlight
                </button>
              )}

              <EdgeLegend />

              {/* Status dot */}
              <div style={{ position: 'absolute', top: 12, right: 12, display: 'flex', alignItems: 'center', gap: 6 }}>
                <motion.div
                  animate={frozen ? { opacity: 1 } : { opacity: [1, 0.2, 1] }}
                  transition={{ duration: 2, repeat: frozen ? 0 : Infinity }}
                  style={{
                    width: 7, height: 7, borderRadius: '50%',
                    background: error ? 'var(--red)' : frozen ? 'var(--accent)' : 'var(--green)',
                    boxShadow: `0 0 8px ${error ? 'var(--red)' : frozen ? 'var(--accent)' : 'var(--green)'}`,
                  }}
                />
                <span style={{ fontSize: 10, color: 'var(--text-muted)' }}>
                  {error ? 'Disconnected' : frozen ? 'Frozen' : 'Settling...'}
                </span>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
