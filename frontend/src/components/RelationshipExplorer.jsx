import { useState, useEffect, useRef } from 'react'
import { getGraphNodes, getGraphPath, explainRelationship } from '../utils/api'
import { NODE_COLOR, EDGE_COLOR } from '../utils/constants'

const LAYER_ORDER = [
  'RouterModel', 'RouterFeature', 'OperationalImplication',
  'InfraRequirement', 'NodeProfile', 'DeploymentPattern',
]

const SOURCE_LAYERS = [
  { type: 'RouterModel',   label: 'Routers' },
  { type: 'RouterFeature', label: 'Features' },
]

const TARGET_LAYERS = [
  { type: 'OperationalImplication', label: 'Implications' },
  { type: 'InfraRequirement',       label: 'Requirements' },
  { type: 'NodeProfile',            label: 'Node Profiles' },
  { type: 'DeploymentPattern',      label: 'Deployment Patterns' },
]

const SOURCE_TYPES = new Set(SOURCE_LAYERS.map(l => l.type))
const TARGET_TYPES = new Set(TARGET_LAYERS.map(l => l.type))

// ─── BFS ─────────────────────────────────────────────────────────────────────
function bfsPath(sourceId, targetId, edges) {
  if (sourceId === targetId) return [sourceId]
  const fwd = {}
  edges.forEach(e => { (fwd[e.source] ??= []).push(e.target) })
  const prev = { [sourceId]: null }
  const queue = [sourceId]
  while (queue.length) {
    const cur = queue.shift()
    for (const next of (fwd[cur] ?? [])) {
      if (next in prev) continue
      prev[next] = cur
      if (next === targetId) {
        const path = []
        let n = targetId
        while (n !== null) { path.unshift(n); n = prev[n] }
        return path
      }
      queue.push(next)
    }
  }
  return null
}

function normalize(s) {
  return s.toLowerCase().replace(/[\s\-_]+/g, ' ').trim()
}

// ─── Compact grouped dropdown ─────────────────────────────────────────────────
function NodeDropdown({ layers, allNodes, selected, onSelect, placeholder }) {
  const [open,  setOpen]  = useState(false)
  const [query, setQuery] = useState('')
  const ref = useRef(null)

  useEffect(() => {
    function handler(e) {
      if (ref.current && !ref.current.contains(e.target)) setOpen(false)
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [])

  const groups = layers.map(({ type, label }) => {
    const nodes = allNodes
      .filter(n => n.type === type)
      .filter(n =>
        query.trim() === '' ||
        normalize(n.label ?? '').includes(normalize(query)) ||
        n.id.toLowerCase().includes(query.toLowerCase())
      )
    return { type, label, nodes }
  }).filter(g => g.nodes.length > 0)

  const color = selected ? (NODE_COLOR[selected.type] || '#888') : null

  return (
    <div ref={ref} style={{ flex: 1, position: 'relative' }}>
      <button
        onClick={() => setOpen(v => !v)}
        style={{
          width: '100%', padding: '8px 12px', borderRadius: 8, cursor: 'pointer',
          background: selected ? `${color}12` : 'var(--bg-secondary)',
          border: `1px solid ${selected ? `${color}40` : 'var(--border)'}`,
          display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8,
          textAlign: 'left',
        }}
      >
        {selected ? (
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ fontSize: 9, color, fontWeight: 700, letterSpacing: '1px',
              textTransform: 'uppercase', marginBottom: 1 }}>
              {selected.type.replace(/([A-Z])/g, ' $1').trim()}
            </div>
            <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-primary)',
              overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
              {selected.label}
            </div>
          </div>
        ) : (
          <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>{placeholder}</span>
        )}
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexShrink: 0 }}>
          {selected && (
            <span onClick={e => { e.stopPropagation(); onSelect(null) }}
              style={{ fontSize: 14, color: 'var(--text-muted)', lineHeight: 1, cursor: 'pointer' }}>
              ×
            </span>
          )}
          <span style={{ fontSize: 10, color: 'var(--text-muted)' }}>{open ? '▲' : '▼'}</span>
        </div>
      </button>

      {open && (
        <div style={{
          position: 'absolute', top: 'calc(100% + 4px)', left: 0, right: 0, zIndex: 100,
          background: 'var(--bg-secondary)', border: '1px solid var(--border)',
          borderRadius: 8, boxShadow: '0 8px 32px rgba(0,0,0,0.5)',
          display: 'flex', flexDirection: 'column',
        }}>
          <div style={{ padding: '8px 8px 4px' }}>
            <input
              autoFocus
              value={query}
              onChange={e => setQuery(e.target.value)}
              placeholder="Search…"
              style={{
                width: '100%', padding: '6px 10px', borderRadius: 6, fontSize: 11,
                boxSizing: 'border-box', background: 'var(--bg-card)',
                border: '1px solid var(--border)', color: 'var(--text-primary)', outline: 'none',
              }}
            />
          </div>
          <div style={{ maxHeight: 260, overflowY: 'auto' }}>
            {groups.length === 0 ? (
              <div style={{ padding: '12px', fontSize: 11, color: 'var(--text-muted)', textAlign: 'center' }}>
                No results
              </div>
            ) : groups.map(({ type, label, nodes }) => {
              const gc = NODE_COLOR[type] || '#888'
              return (
                <div key={type}>
                  <div style={{
                    padding: '5px 12px', display: 'flex', alignItems: 'center', gap: 6,
                    background: 'rgba(255,255,255,0.03)',
                    borderTop: '1px solid rgba(255,255,255,0.05)', position: 'sticky', top: 0,
                  }}>
                    <div style={{ width: 6, height: 6, borderRadius: '50%', background: gc, boxShadow: `0 0 4px ${gc}` }} />
                    <span style={{ fontSize: 9, fontWeight: 700, letterSpacing: '1px', textTransform: 'uppercase', color: gc }}>
                      {label}
                    </span>
                    <span style={{ fontSize: 9, color: 'var(--text-muted)', marginLeft: 'auto' }}>{nodes.length}</span>
                  </div>
                  {nodes.map(n => {
                    const isSelected = selected?.id === n.id
                    return (
                      <div
                        key={n.id}
                        onClick={() => { onSelect(n); setOpen(false); setQuery('') }}
                        style={{
                          padding: '7px 12px', cursor: 'pointer',
                          display: 'flex', alignItems: 'center', gap: 8,
                          background: isSelected ? `${gc}18` : 'transparent',
                          borderLeft: `2px solid ${isSelected ? gc : 'transparent'}`,
                          borderBottom: '1px solid rgba(255,255,255,0.03)',
                        }}
                        onMouseEnter={e => { if (!isSelected) e.currentTarget.style.background = 'rgba(255,255,255,0.05)' }}
                        onMouseLeave={e => { if (!isSelected) e.currentTarget.style.background = 'transparent' }}
                      >
                        <div style={{ flex: 1, minWidth: 0 }}>
                          <div style={{ fontSize: 11, fontWeight: isSelected ? 600 : 400,
                            color: isSelected ? gc : 'var(--text-primary)',
                            overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                            {n.label}
                          </div>
                          <div style={{ fontSize: 9, color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', marginTop: 1 }}>
                            {n.id}
                          </div>
                        </div>
                        {isSelected && <div style={{ width: 6, height: 6, borderRadius: '50%', background: gc, flexShrink: 0 }} />}
                      </div>
                    )
                  })}
                </div>
              )
            })}
          </div>
        </div>
      )}
    </div>
  )
}

// ─── Path result ──────────────────────────────────────────────────────────────
function PathResult({ pathNodes, pathEdges, nodeMap, explanation, loadingExplanation }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      {/* Visual path */}
      <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 6 }}>
        {pathNodes.map((id, i) => {
          const n = nodeMap[id]
          if (!n) return null
          const color = NODE_COLOR[n.type] || '#888'
          return (
            <div key={id} style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              <div style={{ padding: '5px 10px', borderRadius: 6, background: `${color}14`, border: `1px solid ${color}45` }}>
                <div style={{ fontSize: 8, color, letterSpacing: '0.8px', textTransform: 'uppercase', marginBottom: 2 }}>
                  {n.type.replace(/([A-Z])/g, ' $1').trim()}
                </div>
                <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--text-primary)' }}>{n.label}</div>
              </div>
              {i < pathNodes.length - 1 && (
                <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 1 }}>
                  <span style={{ fontSize: 8, color: EDGE_COLOR[pathEdges[i]?.type] || '#888', fontWeight: 700 }}>
                    {pathEdges[i]?.type}
                  </span>
                  <span style={{ color: 'rgba(255,255,255,0.25)', fontSize: 13 }}>→</span>
                </div>
              )}
            </div>
          )
        })}
      </div>

      {/* Edge properties */}
      {pathEdges.length > 0 && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
          <div style={{ fontSize: 9, color: 'var(--text-muted)', letterSpacing: '1px', textTransform: 'uppercase', marginBottom: 2 }}>
            Edge Properties
          </div>
          {pathEdges.map((e, i) => {
            const ec  = EDGE_COLOR[e.type] || '#888'
            const src = nodeMap[e.source]
            const tgt = nodeMap[e.target]
            return (
              <div key={i} style={{
                display: 'flex', alignItems: 'center', gap: 10,
                padding: '5px 10px', borderRadius: 6,
                background: `${ec}08`, border: `1px solid ${ec}25`, fontSize: 11,
              }}>
                <span style={{ color: ec, fontWeight: 700, minWidth: 110 }}>{e.type}</span>
                <span style={{ color: 'var(--text-muted)', flex: 1 }}>{src?.label} → {tgt?.label}</span>
                <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10, display: 'flex', gap: 10 }}>
                  {e.base_weight != null && <span>weight: <span style={{ color: '#00ff88' }}>{Number(e.base_weight).toFixed(2)}</span></span>}
                  {e.fit_score   != null && <span>fit: <span style={{ color: '#ffd700' }}>{Number(e.fit_score).toFixed(2)}</span></span>}
                  {e.priority    != null && <span>priority: <span style={{ color: '#ff8c42' }}>{e.priority}</span></span>}
                </span>
              </div>
            )
          })}
        </div>
      )}

      {/* AI explanation */}
      <div style={{ padding: '10px 14px', borderRadius: 8,
        background: 'rgba(0,212,255,0.04)', border: '1px solid rgba(0,212,255,0.12)' }}>
        <div style={{ fontSize: 9, color: '#00d4ff', letterSpacing: '1px',
          textTransform: 'uppercase', marginBottom: 6, fontWeight: 700 }}>
          AI Explanation
        </div>
        {loadingExplanation ? (
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 12, color: 'var(--text-muted)' }}>
            <div style={{ width: 12, height: 12, borderRadius: '50%',
              border: '2px solid var(--border)', borderTopColor: '#00d4ff',
              animation: 'spin 0.8s linear infinite', flexShrink: 0 }} />
            Asking AI…
          </div>
        ) : (
          <div style={{ fontSize: 12, color: 'var(--text-secondary)', lineHeight: 1.8 }}>
            {explanation}
          </div>
        )}
      </div>
    </div>
  )
}

// ─── Main ─────────────────────────────────────────────────────────────────────
export default function RelationshipExplorer({ chainData, pendingNode, onConsumed }) {
  const [source,             setSource]             = useState(null)
  const [target,             setTarget]             = useState(null)
  const [result,             setResult]             = useState(null)
  const [error,              setError]              = useState(null)
  const [loading,            setLoading]            = useState(false)
  const [explanation,        setExplanation]        = useState(null)
  const [loadingExplanation, setLoadingExplanation] = useState(false)
  const [allNodes,           setAllNodes]           = useState([])

  function fetchNodes() {
    getGraphNodes().then(setAllNodes).catch(() => {})
  }

  useEffect(() => { fetchNodes() }, [])

  // Canvas click → assign to correct panel by type
  useEffect(() => {
    if (!pendingNode) return
    setResult(null); setError(null); setExplanation(null)
    if (SOURCE_TYPES.has(pendingNode.type))      setSource(pendingNode)
    else if (TARGET_TYPES.has(pendingNode.type)) setTarget(pendingNode)
    else setSource(prev => { if (!prev) return pendingNode; setTarget(pendingNode); return prev })
    onConsumed()
  }, [pendingNode])

  // Auto-find when both selected
  useEffect(() => {
    if (source && target) runFind(source.id, target.id)
  }, [source?.id, target?.id])

  function reset() {
    setSource(null); setTarget(null)
    setResult(null); setError(null); setExplanation(null)
  }

  function buildNodeMap(nodes) {
    const m = {}
    allNodes.forEach(n => { m[n.id] = n })          // seed with full graph
    nodes.forEach(n => { m[n.id] = n })              // override with richer data
    return m
  }

  function commitResult(obj) {
    setResult(obj)
    setExplanation(null)
    setLoadingExplanation(true)
    const resolved = obj.pathNodes.map(id => obj.nodeMap[id]).filter(Boolean)
    explainRelationship(resolved, obj.pathEdges)
      .then(d => setExplanation(d.explanation))
      .catch(() => setExplanation('Could not generate explanation.'))
      .finally(() => setLoadingExplanation(false))
  }

  function runFind(srcId, tgtId) {
    if (!srcId || !tgtId || srcId === tgtId) return

    // Direction guard
    const srcNode = allNodes.find(n => n.id === srcId)
    const tgtNode = allNodes.find(n => n.id === tgtId)
    if (srcNode && tgtNode) {
      const si = LAYER_ORDER.indexOf(srcNode.type)
      const ti = LAYER_ORDER.indexOf(tgtNode.type)
      if (si !== -1 && ti !== -1 && si >= ti) {
        setError(`"${srcNode.label}" is downstream of "${tgtNode.label}". Swap them — From must be a Router or Feature.`)
        return
      }
    }

    setError(null); setResult(null); setExplanation(null)

    // 1. Local BFS on loaded chain
    if (chainData) {
      const nodeMap = buildNodeMap(chainData.nodes)
      const direct = chainData.edges.find(e => e.source === srcId && e.target === tgtId)
      if (direct) {
        commitResult({ pathNodes: [srcId, tgtId], pathEdges: [direct], nodeMap, isDirect: true })
        return
      }
      const pathIds = bfsPath(srcId, tgtId, chainData.edges)
      if (pathIds) {
        const pathEdges = []
        for (let i = 0; i < pathIds.length - 1; i++) {
          const e = chainData.edges.find(e => e.source === pathIds[i] && e.target === pathIds[i + 1])
          if (e) pathEdges.push(e)
        }
        commitResult({ pathNodes: pathIds, pathEdges, nodeMap, isDirect: false })
        return
      }
    }

    // 2. Backend shortestPath fallback
    setLoading(true)
    getGraphPath(srcId, tgtId)
      .then(data => {
        if (!data.path?.length) {
          setError('No path found. Select a Router or Feature as source, and an Implication, Profile, or Pattern as target.')
          return
        }
        commitResult({ pathNodes: data.path, pathEdges: data.edges, nodeMap: buildNodeMap(data.nodes), isDirect: false })
      })
      .catch(() => setError('No path found between these two nodes.'))
      .finally(() => setLoading(false))
  }

  const canFind = source && target && source.id !== target.id

  return (
    <div style={{
      marginTop: 24, padding: 20, borderRadius: 12,
      background: 'var(--bg-card)', border: '1px solid var(--border)',
      display: 'flex', flexDirection: 'column', gap: 16,
    }}>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <div>
          <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text-primary)' }}>Relationship Explorer</div>
          <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 2 }}>
            Pick a source and target to trace the reasoning path between them
          </div>
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          <button onClick={fetchNodes} style={{
            padding: '4px 10px', borderRadius: 6, cursor: 'pointer', fontSize: 11,
            background: 'var(--bg-secondary)', border: '1px solid var(--border)', color: 'var(--text-muted)',
          }}>↻ Refresh</button>
          {(source || target || result) && (
            <button onClick={reset} style={{
              padding: '4px 10px', borderRadius: 6, cursor: 'pointer', fontSize: 11,
              background: 'var(--bg-secondary)', border: '1px solid var(--border)', color: 'var(--text-muted)',
            }}>Reset</button>
          )}
        </div>
      </div>

      {/* Dropdowns */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: 4 }}>
          <div style={{ fontSize: 9, fontWeight: 700, letterSpacing: '1.5px', textTransform: 'uppercase', color: 'var(--text-muted)' }}>From</div>
          <NodeDropdown layers={SOURCE_LAYERS} allNodes={allNodes} selected={source}
            onSelect={n => { setSource(n); setResult(null); setError(null); setExplanation(null) }}
            placeholder="Select router or feature…" />
        </div>

        <div style={{
          width: 32, height: 32, borderRadius: '50%', flexShrink: 0, marginTop: 18,
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          background: canFind ? 'linear-gradient(135deg, var(--accent), var(--purple))' : 'var(--bg-secondary)',
          border: `1px solid ${canFind ? 'transparent' : 'var(--border)'}`,
          boxShadow: canFind ? '0 0 12px var(--accent-glow)' : 'none',
          transition: 'all 0.2s',
        }}>
          <span style={{ color: canFind ? '#fff' : 'rgba(255,255,255,0.2)', fontSize: 14 }}>→</span>
        </div>

        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: 4 }}>
          <div style={{ fontSize: 9, fontWeight: 700, letterSpacing: '1.5px', textTransform: 'uppercase', color: 'var(--text-muted)' }}>To</div>
          <NodeDropdown layers={TARGET_LAYERS} allNodes={allNodes} selected={target}
            onSelect={n => { setTarget(n); setResult(null); setError(null); setExplanation(null) }}
            placeholder="Select implication, profile or pattern…" />
        </div>
      </div>

      {loading && (
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 12, color: 'var(--text-muted)' }}>
          <div style={{ width: 14, height: 14, borderRadius: '50%',
            border: '2px solid var(--border)', borderTopColor: 'var(--accent)',
            animation: 'spin 0.8s linear infinite' }} />
          Finding path…
        </div>
      )}

      {error && (
        <div style={{ fontSize: 12, color: '#ff4466', padding: '8px 12px', borderRadius: 7,
          background: 'rgba(255,68,102,0.08)', border: '1px solid rgba(255,68,102,0.2)' }}>
          {error}
        </div>
      )}

      {result && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>
            {result.isDirect
              ? '✓ Direct relationship'
              : `Shortest path · ${result.pathNodes.length} nodes · ${result.pathEdges.length} hops`}
          </div>
          <PathResult
            pathNodes={result.pathNodes} pathEdges={result.pathEdges}
            nodeMap={result.nodeMap} explanation={explanation}
            loadingExplanation={loadingExplanation}
          />
        </div>
      )}
    </div>
  )
}
