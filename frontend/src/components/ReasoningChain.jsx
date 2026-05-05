import { useEffect, useState, useMemo } from 'react'
import {
  ReactFlow, Background, Controls,
  useNodesState, useEdgesState,
  MarkerType, Position, Handle,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import { getRouters, getRouterChain } from '../utils/api'
import { NODE_COLOR, EDGE_COLOR, LAYERS } from '../utils/constants'
import NodeInspectorPanel from './NodeInspectorPanel'
import RelationshipExplorer from './RelationshipExplorer'

// Fixed X column per reasoning layer (left → right)
const LAYER_X = {
  RouterModel:            0,
  RouterFeature:          240,
  OperationalImplication: 480,
  InfraRequirement:       720,
  NodeProfile:            960,
  DeploymentPattern:      1200,
}

// ─── Custom node ──────────────────────────────────────────────────────────────

function ChainNode({ data }) {
  const color  = NODE_COLOR[data.type] || '#888'
  const dimmed = data.dimmed
  const active = data.active

  let sub = ''
  if (data.vcpu)               sub = `${data.vcpu} vCPU · ${data.ram_gb ?? '?'} GB RAM`
  else if (data.value != null) sub = `${data.value} ${data.unit ?? ''}`.trim()
  else if (data.min_value != null) sub = `min ${data.min_value} ${data.unit ?? ''}`.trim()
  else if (data.severity != null)  sub = `severity ${data.severity}`

  return (
    <div style={{
      padding: '10px 14px', borderRadius: 10, minWidth: 148, maxWidth: 176, cursor: 'pointer',
      background: dimmed ? 'rgba(255,255,255,0.02)' : `${color}14`,
      border: `1.5px solid ${dimmed ? 'rgba(255,255,255,0.07)' : active ? color : `${color}55`}`,
      boxShadow: active ? `0 0 18px ${color}50` : 'none',
      opacity: dimmed ? 0.25 : 1,
      transition: 'opacity 0.15s, box-shadow 0.15s',
    }}>
      <Handle type="target" position={Position.Left}
        style={{ background: color, width: 7, height: 7, border: 'none' }} />
      <div style={{ fontSize: 8, fontWeight: 700, letterSpacing: '1.2px', textTransform: 'uppercase',
        color: dimmed ? 'rgba(255,255,255,0.25)' : color, marginBottom: 4 }}>
        {data.type.replace(/([A-Z])/g, ' $1').trim()}
      </div>
      <div style={{ fontSize: 12, fontWeight: 600, lineHeight: 1.35,
        color: dimmed ? 'rgba(255,255,255,0.25)' : 'var(--text-primary)' }}>
        {data.label}
      </div>
      {sub && (
        <div style={{ fontSize: 10, marginTop: 3,
          color: dimmed ? 'rgba(255,255,255,0.15)' : 'var(--text-muted)' }}>
          {sub}
        </div>
      )}
      <Handle type="source" position={Position.Right}
        style={{ background: color, width: 7, height: 7, border: 'none' }} />
    </div>
  )
}

const NODE_TYPES = { chain: ChainNode }

// ─── Layout builder ───────────────────────────────────────────────────────────

function buildGraph(chainData, highlightSet, activeId) {
  if (!chainData) return { nodes: [], edges: [] }

  const { nodes: raw, edges: rawEdges } = chainData
  const hasHighlight = highlightSet.size > 0
  const byType = {}
  raw.forEach(n => { (byType[n.type] ??= []).push(n) })

  const nodes = raw.map(n => {
    const group   = byType[n.type]
    const idx     = group.indexOf(n)
    const yOffset = (idx - (group.length - 1) / 2) * 120
    return {
      id:       n.id,
      type:     'chain',
      position: { x: LAYER_X[n.type] ?? 0, y: 200 + yOffset },
      data: {
        ...n,
        active: n.id === activeId || (hasHighlight && highlightSet.has(n.id)),
        dimmed: hasHighlight && !highlightSet.has(n.id),
      },
    }
  })

  const edges = rawEdges.map((e, i) => {
    const color  = EDGE_COLOR[e.type] || 'rgba(255,255,255,0.2)'
    const lit    = !hasHighlight || (highlightSet.has(e.source) && highlightSet.has(e.target))
    const weight = e.base_weight ?? e.fit_score ?? 0.5
    return {
      id: `e${i}`, source: e.source, target: e.target,
      type: 'smoothstep', animated: lit, label: e.type,
      markerEnd: { type: MarkerType.ArrowClosed, color: lit ? color : 'rgba(255,255,255,0.06)' },
      style:  { stroke: lit ? color : 'rgba(255,255,255,0.05)', strokeWidth: lit ? 1 + weight * 2 : 0.5 },
      labelStyle:   { fill: lit ? color : 'rgba(255,255,255,0.1)', fontSize: 9, fontWeight: 700 },
      labelBgStyle: { fill: 'rgba(5,8,16,0.85)', rx: 3 },
      data: e,
    }
  })

  return { nodes, edges }
}

// BFS: all ancestors + descendants of a node
function tracePathFrom(nodeId, rawEdges) {
  const fwd = {}, bwd = {}
  rawEdges.forEach(e => {
    ;(fwd[e.source] ??= []).push(e.target)
    ;(bwd[e.target] ??= []).push(e.source)
  })
  const visited = new Set()
  const q = [nodeId]
  while (q.length) {
    const cur = q.shift()
    if (visited.has(cur)) continue
    visited.add(cur)
    ;(fwd[cur] ?? []).forEach(t => q.push(t))
    ;(bwd[cur] ?? []).forEach(s => q.push(s))
  }
  return visited
}

// ─── Sub-components ───────────────────────────────────────────────────────────

function LayerBar() {
  return (
    <div style={{ display: 'flex', alignItems: 'center', marginBottom: 10, paddingBottom: 10, borderBottom: '1px solid var(--border)' }}>
      {LAYERS.map((l, i) => (
        <div key={l.type} style={{ display: 'flex', alignItems: 'center', flex: 1 }}>
          <div style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 4 }}>
            <div style={{ width: 8, height: 8, borderRadius: '50%',
              background: NODE_COLOR[l.type], boxShadow: `0 0 6px ${NODE_COLOR[l.type]}` }} />
            <span style={{ fontSize: 10, color: 'var(--text-muted)', fontWeight: 600 }}>{l.label}</span>
          </div>
          {i < LAYERS.length - 1 && (
            <span style={{ color: 'rgba(255,255,255,0.15)', fontSize: 12, flexShrink: 0 }}>›</span>
          )}
        </div>
      ))}
    </div>
  )
}

function RouterPicker({ routers, selectedId, onSelect, newestRouterId }) {
  return (
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, alignItems: 'center',
      paddingBottom: 14, marginBottom: 14, borderBottom: '1px solid var(--border)' }}>
      <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>Router:</span>
      {routers.map(r => {
        const active  = r.id === selectedId
        const isNew   = r.id === newestRouterId
        return (
          <button key={r.id} onClick={() => onSelect(r)} style={{
            padding: '5px 14px', borderRadius: 20, cursor: 'pointer',
            fontSize: 11, fontWeight: 500, position: 'relative',
            background: active ? 'linear-gradient(135deg, var(--accent), var(--purple))' : 'var(--bg-card)',
            color:     active ? '#fff' : 'var(--text-muted)',
            border:    `1px solid ${active ? 'transparent' : isNew ? 'var(--accent)' : 'var(--border)'}`,
            boxShadow: active ? '0 0 10px var(--accent-glow)' : 'none',
          }}>
            {r.name || r.id}
            {isNew && (
              <span style={{
                position: 'absolute', top: -7, right: -6,
                background: 'var(--accent)', color: '#000',
                fontSize: 8, fontWeight: 800, letterSpacing: '0.5px',
                padding: '1px 5px', borderRadius: 10,
                lineHeight: '14px', textTransform: 'uppercase',
                boxShadow: '0 0 8px var(--accent-glow)',
                animation: 'newBadgePulse 2s ease-in-out 3',
              }}>
                new
              </span>
            )}
          </button>
        )
      })}
    </div>
  )
}

// ─── Main ─────────────────────────────────────────────────────────────────────

export default function ReasoningChain({ newestRouterId }) {
  const [routers,        setRouters]        = useState([])
  const [selectedRouter, setSelectedRouter] = useState(null)
  const [chainData,      setChainData]      = useState(null)
  const [loading,        setLoading]        = useState(false)
  const [fetchError,     setFetchError]     = useState(false)
  const [activeNode,     setActiveNode]     = useState(null)
  const [highlightSet,   setHighlightSet]   = useState(new Set())
  const [pendingNode,    setPendingNode]    = useState(null)

  const [nodes, setNodes, onNodesChange] = useNodesState([])
  const [edges, setEdges, onEdgesChange] = useEdgesState([])

  useEffect(() => {
    getRouters()
      .then(data => { setRouters(data); if (data.length > 0) loadChain(data[0]) })
      .catch(() => setFetchError(true))
  }, [])

  const { nodes: flowNodes, edges: flowEdges } = useMemo(
    () => buildGraph(chainData, highlightSet, activeNode?.id),
    [chainData, highlightSet, activeNode?.id],
  )

  useEffect(() => {
    setNodes(flowNodes)
    setEdges(flowEdges)
  }, [flowNodes, flowEdges])

  function loadChain(router) {
    setSelectedRouter(router)
    setActiveNode(null)
    setHighlightSet(new Set())
    setLoading(true)
    getRouterChain(router.id)
      .then(setChainData)
      .catch(() => setChainData(null))
      .finally(() => setLoading(false))
  }

  function onNodeClick(_, node) {
    setActiveNode(node.data)
    setPendingNode(node.data)
  }

  function highlight(nodeId) {
    if (chainData) setHighlightSet(tracePathFrom(nodeId, chainData.edges))
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 0 }}>
        <RouterPicker routers={routers} selectedId={selectedRouter?.id} onSelect={loadChain} newestRouterId={newestRouterId} />
      {fetchError && (
        <div style={{ fontSize: 12, color: 'var(--red)', padding: '8px 0' }}>
          Could not load routers. Is the API running?
        </div>
      )}
      <LayerBar />

      <div style={{ display: 'flex', gap: 16, alignItems: 'flex-start' }}>
        {/* React Flow canvas */}
        <div style={{ flex: 1, height: 560, borderRadius: 12, overflow: 'hidden',
          background: 'var(--bg-card)', border: '1px solid var(--border)', position: 'relative' }}>

          {loading && (
            <div style={{ position: 'absolute', inset: 0, zIndex: 10, display: 'flex',
              alignItems: 'center', justifyContent: 'center', gap: 10,
              background: 'rgba(5,8,16,0.85)' }}>
              <div style={{ width: 22, height: 22, borderRadius: '50%',
                border: '2px solid var(--border)', borderTopColor: 'var(--accent)',
                animation: 'spin 0.8s linear infinite' }} />
              <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>Loading chain…</span>
            </div>
          )}

          {!loading && !chainData && (
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center',
              height: '100%', fontSize: 13, color: 'var(--text-muted)' }}>
              Select a router above
            </div>
          )}

          {highlightSet.size > 0 && (
            <button onClick={() => setHighlightSet(new Set())} style={{
              position: 'absolute', top: 10, left: 10, zIndex: 10,
              padding: '4px 10px', borderRadius: 6, cursor: 'pointer',
              background: 'var(--bg-secondary)', border: '1px solid var(--border)',
              fontSize: 11, color: 'var(--text-muted)',
            }}>
              ✕ Clear highlight
            </button>
          )}

          <ReactFlow
            nodes={nodes} edges={edges}
            onNodesChange={onNodesChange} onEdgesChange={onEdgesChange}
            onNodeClick={onNodeClick}
            nodeTypes={NODE_TYPES}
            fitView fitViewOptions={{ padding: 0.25 }}
            minZoom={0.2} maxZoom={2}
            proOptions={{ hideAttribution: true }}
            style={{ background: '#050810' }}
          >
            <Background color="rgba(0,212,255,0.04)" gap={28} size={1} />
            <Controls />
          </ReactFlow>
        </div>

        {/* Inspector panel */}
        {activeNode && (
          <NodeInspectorPanel
            node={activeNode}
            edges={chainData?.edges ?? []}
            onClose={() => setActiveNode(null)}
            onHighlight={highlight}
          />
        )}
      </div>

      <RelationshipExplorer
        chainData={chainData}
        pendingNode={pendingNode}
        onConsumed={() => setPendingNode(null)}
      />
    </div>
  )
}
