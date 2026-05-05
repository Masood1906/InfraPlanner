import { motion } from 'framer-motion'
import { Cpu, MemoryStick, Network, HardDrive, Server } from 'lucide-react'

const ROLE_CONFIG = {
  compute:  { color: 'var(--accent)',  icon: Cpu,         label: 'Compute'  },
  network:  { color: 'var(--purple)',  icon: Network,     label: 'Network'  },
  memory:   { color: 'var(--green)',   icon: MemoryStick, label: 'Memory'   },
  storage:  { color: 'var(--yellow)',  icon: HardDrive,   label: 'Storage'  },
  balanced: { color: '#ff8c42',        icon: Server,      label: 'Balanced' },
}

function NodeCard({ node, index }) {
  const cfg = ROLE_CONFIG[node.role] || ROLE_CONFIG.balanced
  const Icon = cfg.icon

  return (
    <motion.div
      initial={{ opacity: 0, scale: 0.8 }}
      animate={{ opacity: 1, scale: 1 }}
      transition={{ delay: index * 0.06, duration: 0.4 }}
      whileHover={{ scale: 1.03, borderColor: cfg.color }}
      style={{
        background: 'var(--bg-secondary)',
        border: '1px solid var(--border)',
        borderRadius: 12, padding: 14,
        cursor: 'default', transition: 'border-color 0.2s',
      }}
    >
      {/* Node header */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <div style={{
            width: 28, height: 28, borderRadius: 8,
            background: `${cfg.color}18`, border: `1px solid ${cfg.color}40`,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
          }}>
            <Icon size={13} color={cfg.color} />
          </div>
          <div>
            <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-primary)', fontFamily: 'var(--font-mono)' }}>
              {node.node_id}
            </div>
            <div style={{ fontSize: 10, color: cfg.color, fontWeight: 500 }}>{cfg.label}</div>
          </div>
        </div>
        <div style={{
          fontSize: 10, padding: '2px 8px', borderRadius: 10,
          background: `${cfg.color}15`, color: cfg.color, fontWeight: 600,
        }}>
          {node.profile_name}
        </div>
      </div>

      {/* Specs grid */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 6 }}>
        {[
          { label: 'vCPU', value: node.vcpu },
          { label: 'RAM', value: `${node.ram_gb}GB` },
          { label: 'Ports', value: node.ports },
          { label: 'Storage', value: `${node.storage_gb}GB` },
        ].map(({ label, value }) => (
          <div key={label} style={{
            background: 'var(--bg-primary)', borderRadius: 8, padding: '6px 10px',
          }}>
            <div style={{ fontSize: 9, color: 'var(--text-muted)', marginBottom: 2, textTransform: 'uppercase', letterSpacing: '0.5px' }}>
              {label}
            </div>
            <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text-primary)', fontFamily: 'var(--font-mono)' }}>
              {value}
            </div>
          </div>
        ))}
      </div>
    </motion.div>
  )
}

function StatBadge({ label, value, color }) {
  return (
    <div style={{ textAlign: 'center' }}>
      <div style={{ fontSize: 20, fontWeight: 700, color, fontFamily: 'var(--font-mono)' }}>{value}</div>
      <div style={{ fontSize: 10, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.5px' }}>{label}</div>
    </div>
  )
}

export default function ClusterView({ clusters, topologyType, patternName }) {
  if (!clusters?.length) return null

  return (
    <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }}>
      {/* Topology badge */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 20 }}>
        <div style={{
          padding: '6px 16px', borderRadius: 20,
          background: 'var(--accent-glow)', border: '1px solid var(--accent)',
          fontSize: 12, color: 'var(--accent)', fontWeight: 600, letterSpacing: '0.5px',
        }}>
          {topologyType?.replace(/_/g, ' ').toUpperCase()}
        </div>
        {patternName && (
          <div style={{
            padding: '6px 16px', borderRadius: 20,
            background: 'var(--purple-dim)', border: '1px solid var(--purple)',
            fontSize: 12, color: 'var(--purple)', fontWeight: 600,
          }}>
            {patternName}
          </div>
        )}
      </div>

      {clusters.map((cluster, ci) => (
        <motion.div
          key={cluster.cluster_id}
          initial={{ opacity: 0, y: 30 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: ci * 0.1 }}
          style={{
            background: 'var(--bg-card)', border: '1px solid var(--border)',
            borderRadius: 16, padding: 24, marginBottom: 16,
          }}
        >
          {/* Cluster header */}
          <div style={{
            display: 'flex', alignItems: 'center', justifyContent: 'space-between',
            marginBottom: 20, paddingBottom: 16, borderBottom: '1px solid var(--border)',
          }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
              <div style={{
                width: 36, height: 36, borderRadius: 10,
                background: 'linear-gradient(135deg, var(--accent), var(--purple))',
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                boxShadow: '0 0 16px var(--accent-glow)',
              }}>
                <Server size={16} color="#fff" />
              </div>
              <div>
                <div style={{ fontSize: 15, fontWeight: 700, color: 'var(--text-primary)', textTransform: 'uppercase', letterSpacing: '0.5px' }}>
                  {cluster.cluster_id}
                </div>
                <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>
                  {cluster.node_count} nodes · {cluster.topology_type}
                </div>
              </div>
            </div>

            {/* Aggregate stats */}
            <div style={{ display: 'flex', gap: 28 }}>
              <StatBadge label="vCPU" value={cluster.total_vcpu} color="var(--accent)" />
              <StatBadge label="RAM" value={`${cluster.total_ram_gb}GB`} color="var(--green)" />
              <StatBadge label="Ports" value={cluster.total_ports} color="var(--purple)" />
            </div>
          </div>

          {/* Node grid */}
          <div style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))',
            gap: 12,
          }}>
            {cluster.nodes.map((node, ni) => (
              <NodeCard key={node.node_id} node={node} index={ni} />
            ))}
          </div>
        </motion.div>
      ))}
    </motion.div>
  )
}
