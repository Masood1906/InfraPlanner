import { useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { ChevronDown, ChevronUp, Brain } from 'lucide-react'

const STEP_COLORS = {
  '[Target]':  { color: 'var(--accent)',  bg: 'var(--accent-glow)' },
  '[Select]':  { color: 'var(--green)',   bg: 'var(--green-dim)' },
  '[Pattern]': { color: 'var(--purple)',  bg: 'var(--purple-dim)' },
  '[Plan]':    { color: 'var(--yellow)',  bg: 'var(--yellow-dim)' },
}

function getStepStyle(line) {
  for (const [prefix, style] of Object.entries(STEP_COLORS)) {
    if (line.startsWith(prefix)) return { ...style, prefix, rest: line.slice(prefix.length) }
  }
  return { color: 'var(--text-muted)', bg: 'transparent', prefix: '', rest: line }
}

export default function ReasoningTrace({ reasoning }) {
  const [open, setOpen] = useState(false)
  if (!reasoning?.length) return null

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      style={{
        background: 'var(--bg-card)', border: '1px solid var(--border)',
        borderRadius: 16, overflow: 'hidden',
      }}
    >
      <button
        onClick={() => setOpen(o => !o)}
        style={{
          width: '100%', padding: '16px 20px',
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          background: 'none', border: 'none', cursor: 'pointer',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <Brain size={15} color="var(--accent)" />
          <span style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-primary)' }}>
            Reasoning Trace
          </span>
          <span style={{
            fontSize: 11, padding: '2px 8px', borderRadius: 10,
            background: 'var(--accent-glow)', color: 'var(--accent)',
          }}>
            {reasoning.length} steps
          </span>
        </div>
        {open ? <ChevronUp size={15} color="var(--text-muted)" /> : <ChevronDown size={15} color="var(--text-muted)" />}
      </button>

      <AnimatePresence>
        {open && (
          <motion.div
            initial={{ height: 0 }} animate={{ height: 'auto' }} exit={{ height: 0 }}
            style={{ overflow: 'hidden' }}
          >
            <div style={{ padding: '0 20px 20px', maxHeight: 400, overflowY: 'auto' }}>
              {reasoning.map((line, i) => {
                const s = getStepStyle(line)
                return (
                  <motion.div
                    key={i}
                    initial={{ opacity: 0, x: -10 }}
                    animate={{ opacity: 1, x: 0 }}
                    transition={{ delay: i * 0.03 }}
                    style={{
                      display: 'flex', gap: 10, padding: '8px 10px',
                      borderRadius: 8, marginBottom: 4,
                      background: s.bg,
                    }}
                  >
                    <span style={{
                      fontSize: 10, fontWeight: 700, color: s.color,
                      fontFamily: 'var(--font-mono)', whiteSpace: 'nowrap',
                      minWidth: 70,
                    }}>
                      {s.prefix || `#${i + 1}`}
                    </span>
                    <span style={{
                      fontSize: 11, color: 'var(--text-secondary)',
                      fontFamily: 'var(--font-mono)', lineHeight: 1.5,
                      wordBreak: 'break-all',
                    }}>
                      {s.rest}
                    </span>
                  </motion.div>
                )
              })}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  )
}
