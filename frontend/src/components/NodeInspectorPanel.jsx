import { X } from 'lucide-react'
import { NODE_COLOR, EDGE_COLOR } from '../utils/constants'

const DESC = {
  RouterModel:            'Physical router — the starting point of the reasoning chain.',
  RouterFeature:          'A measurable capability of the router (e.g. forwarding rate).',
  OperationalImplication: 'Infrastructure demand implied by the router\'s features.',
  InfraRequirement:       'Specific resource that must be provisioned.',
  NodeProfile:            'Kubernetes node hardware profile that satisfies the requirement.',
  DeploymentPattern:      'Recommended Kubernetes deployment topology.',
}

function Row({ label, value }) {
  if (value == null || value === '') return null
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, padding: '4px 0', borderBottom: '1px solid rgba(255,255,255,0.05)' }}>
      <span style={{ fontSize: 11, color: 'var(--text-muted)', flexShrink: 0 }}>{label}</span>
      <span style={{ fontSize: 11, color: 'var(--text-secondary)', fontFamily: 'var(--font-mono)', textAlign: 'right' }}>{value}</span>
    </div>
  )
}

export default function NodeInspectorPanel({ node, edges, onClose, onHighlight }) {
  if (!node) return null

  const color = NODE_COLOR[node.type] || '#888'
  const connectedEdges = (edges || []).filter(e => e.source === node.id || e.target === node.id)

  return (
    <div style={{
      width: 256, flexShrink: 0,
      background: 'var(--bg-secondary)',
      border: `1px solid ${color}40`,
      borderRadius: 12, padding: 16,
      display: 'flex', flexDirection: 'column', gap: 14,
      maxHeight: '75vh', overflowY: 'auto',
    }}>
      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
        <div>
          <div style={{
            display: 'inline-block', fontSize: 9, fontWeight: 700,
            letterSpacing: '1.5px', textTransform: 'uppercase',
            color, background: `${color}18`, borderRadius: 4, padding: '2px 6px', marginBottom: 6,
          }}>
            {node.type}
          </div>
          <div style={{ fontSize: 14, fontWeight: 700, color: 'var(--text-primary)', lineHeight: 1.3 }}>
            {node.label}
          </div>
        </div>
        <button onClick={onClose} style={{ background: 'none', border: 'none', cursor: 'pointer', padding: 2 }}>
          <X size={13} color="var(--text-muted)" />
        </button>
      </div>

      {/* Description */}
      {DESC[node.type] && (
        <p style={{ margin: 0, fontSize: 11, color: 'var(--text-muted)', lineHeight: 1.6, background: 'rgba(255,255,255,0.03)', borderRadius: 6, padding: '6px 8px' }}>
          {DESC[node.type]}
        </p>
      )}

      {/* Properties */}
      <div>
        <div style={{ fontSize: 9, color: 'var(--text-muted)', letterSpacing: '1px', textTransform: 'uppercase', marginBottom: 8 }}>Properties</div>
        <Row label="Vendor"        value={node.vendor} />
        <Row label="Series"        value={node.series} />
        <Row label="Category"      value={node.category} />
        <Row label="Value"         value={node.value != null ? `${node.value} ${node.unit || ''}`.trim() : null} />
        <Row label="Severity"      value={node.severity} />
        <Row label="Resource type" value={node.resource_type} />
        <Row label="Min value"     value={node.min_value != null ? `${node.min_value} ${node.unit || ''}`.trim() : null} />
        <Row label="vCPU"          value={node.vcpu} />
        <Row label="RAM"           value={node.ram_gb != null ? `${node.ram_gb} GB` : null} />
        <Row label="Ports"         value={node.ports} />
        <Row label="Storage"       value={node.storage_gb != null ? `${node.storage_gb} GB` : null} />
        <Row label="Role"          value={node.role} />
        <Row label="Topology"      value={node.topology_label} />
      </div>

      {/* Connected edges */}
      {connectedEdges.length > 0 && (
        <div>
          <div style={{ fontSize: 9, color: 'var(--text-muted)', letterSpacing: '1px', textTransform: 'uppercase', marginBottom: 8 }}>
            Edges ({connectedEdges.length})
          </div>
          {connectedEdges.map((e, i) => {
            const ec = EDGE_COLOR[e.type] || '#888'
            return (
              <div key={i} style={{
                display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                padding: '4px 8px', borderRadius: 6, marginBottom: 4,
                background: `${ec}10`, border: `1px solid ${ec}30`,
              }}>
                <span style={{ fontSize: 10, color: ec, fontWeight: 700 }}>{e.type}</span>
                <span style={{ fontSize: 10, color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>
                  {e.base_weight != null && `w:${Number(e.base_weight).toFixed(2)}`}
                  {e.fit_score   != null && ` fit:${Number(e.fit_score).toFixed(2)}`}
                  {e.priority    != null && ` p${e.priority}`}
                </span>
              </div>
            )
          })}
        </div>
      )}

      <button
        onClick={() => onHighlight(node.id)}
        style={{
          padding: '8px 0', borderRadius: 8, cursor: 'pointer', fontWeight: 600,
          fontSize: 11, background: `${color}18`, border: `1px solid ${color}40`, color,
        }}
      >
        Highlight reasoning path
      </button>
    </div>
  )
}
