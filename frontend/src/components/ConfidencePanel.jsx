import { motion } from 'framer-motion'

const LABEL_COLORS = {
  HIGH: 'var(--green)',
  MEDIUM: 'var(--yellow)',
  LOW: '#ff8c42',
  'VERY LOW': 'var(--red)',
}

function RadialGauge({ score, label }) {
  const color = LABEL_COLORS[label] || 'var(--accent)'
  const r = 54
  const circ = 2 * Math.PI * r
  const dash = circ * score

  return (
    <div style={{ position: 'relative', width: 140, height: 140, margin: '0 auto' }}>
      <svg width="140" height="140" style={{ transform: 'rotate(-90deg)' }}>
        <circle cx="70" cy="70" r={r} fill="none" stroke="var(--border)" strokeWidth="8" />
        <motion.circle
          cx="70" cy="70" r={r} fill="none"
          stroke={color} strokeWidth="8"
          strokeLinecap="round"
          strokeDasharray={circ}
          initial={{ strokeDashoffset: circ }}
          animate={{ strokeDashoffset: circ - dash }}
          transition={{ duration: 1.2, ease: 'easeOut', delay: 0.3 }}
          style={{ filter: `drop-shadow(0 0 8px ${color})` }}
        />
      </svg>
      <div style={{
        position: 'absolute', inset: 0,
        display: 'flex', flexDirection: 'column',
        alignItems: 'center', justifyContent: 'center',
      }}>
        <motion.div
          initial={{ opacity: 0, scale: 0.5 }}
          animate={{ opacity: 1, scale: 1 }}
          transition={{ delay: 0.5 }}
          style={{ fontSize: 28, fontWeight: 700, color, fontFamily: 'var(--font-mono)' }}
        >
          {Math.round(score * 100)}
        </motion.div>
        <div style={{ fontSize: 10, color, fontWeight: 600, letterSpacing: '1px' }}>{label}</div>
      </div>
    </div>
  )
}

function Bar({ label, value, color }) {
  return (
    <div style={{ marginBottom: 10 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
        <span style={{ fontSize: 11, color: 'var(--text-secondary)' }}>{label}</span>
        <span style={{ fontSize: 11, color, fontFamily: 'var(--font-mono)', fontWeight: 600 }}>
          {Math.round(value * 100)}%
        </span>
      </div>
      <div style={{ height: 4, background: 'var(--bg-secondary)', borderRadius: 2, overflow: 'hidden' }}>
        <motion.div
          initial={{ width: 0 }}
          animate={{ width: `${value * 100}%` }}
          transition={{ duration: 0.8, ease: 'easeOut', delay: 0.2 }}
          style={{ height: '100%', background: color, borderRadius: 2, boxShadow: `0 0 6px ${color}` }}
        />
      </div>
    </div>
  )
}

export default function ConfidencePanel({ confidence }) {
  if (!confidence) return null
  const color = LABEL_COLORS[confidence.label] || 'var(--accent)'

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      style={{
        background: 'var(--bg-card)', border: '1px solid var(--border)',
        borderRadius: 16, padding: 24,
      }}
    >
      <div style={{ fontSize: 11, color: 'var(--text-muted)', letterSpacing: '1px', textTransform: 'uppercase', marginBottom: 20 }}>
        Confidence Score
      </div>

      <RadialGauge score={confidence.score} label={confidence.label} />

      <div style={{ marginTop: 24 }}>
        <Bar label="Signal Strength"  value={confidence.signal_strength}  color="var(--accent)" />
        <Bar label="Graph Match"      value={confidence.graph_match}      color="var(--purple)" />
        <Bar label="Constraint Clean" value={confidence.constraint_clean} color="var(--green)" />
        <Bar label="Profile Fit"      value={confidence.profile_fit}      color="var(--yellow)" />
        <Bar label="Feature Coverage" value={confidence.feature_coverage} color="#ff8c42" />
      </div>

      <div style={{
        marginTop: 16, padding: 12,
        background: `${color}10`, border: `1px solid ${color}30`,
        borderRadius: 10,
      }}>
        <div style={{ fontSize: 11, color, fontWeight: 600, marginBottom: 6 }}>
          Confidence: {confidence.label}
        </div>
        <div style={{ fontSize: 11, color: 'var(--text-secondary)', lineHeight: 1.6 }}>
          {confidence.label === 'HIGH' && 'Known router with strong signals. Plan is highly reliable.'}
          {confidence.label === 'MEDIUM' && 'Reasonable confidence. Verify plan before production deployment.'}
          {confidence.label === 'LOW' && 'Unknown router or weak signals. Use as a starting estimate.'}
          {confidence.label === 'VERY LOW' && 'Very low confidence. Manual review strongly recommended.'}
        </div>
      </div>
    </motion.div>
  )
}
