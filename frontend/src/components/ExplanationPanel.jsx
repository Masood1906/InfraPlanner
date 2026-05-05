import { useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { Sparkles, Code2 } from 'lucide-react'

export default function ExplanationPanel({ explanation, simple_explanation }) {
  const [tab, setTab] = useState('simple')

  const hasSimple    = Boolean(simple_explanation)
  const hasTechnical = Boolean(explanation)
  if (!hasSimple && !hasTechnical) return null

  const activeText = tab === 'simple' ? simple_explanation : explanation
  const paragraphs = (activeText || '').split('\n\n').filter(Boolean)

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      style={{
        background: 'var(--bg-card)', border: '1px solid var(--border)',
        borderRadius: 16, padding: 24,
      }}
    >
      {/* Header row */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 20 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <div style={{
            width: 32, height: 32, borderRadius: 10,
            background: 'linear-gradient(135deg, var(--accent), var(--purple))',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            boxShadow: '0 0 16px var(--accent-glow)',
          }}>
            <Sparkles size={15} color="#fff" />
          </div>
          <div>
            <div style={{ fontSize: 14, fontWeight: 700, color: 'var(--text-primary)' }}>Explanation</div>
            <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 2 }}>
              {tab === 'simple'
                ? "Here's why this setup was chosen"
                : 'Technical reasoning chain for engineers'}
            </div>
          </div>
        </div>

        {/* Tab toggle */}
        <div style={{
          display: 'flex', gap: 2,
          background: 'var(--bg-secondary)', border: '1px solid var(--border)',
          borderRadius: 10, padding: 3,
        }}>
          {[
            { id: 'simple',    label: 'Simple',    icon: Sparkles },
            { id: 'technical', label: 'Technical', icon: Code2 },
          ].map(({ id, label, icon: Icon }) => {
            const active = tab === id
            return (
              <motion.button
                key={id}
                onClick={() => setTab(id)}
                whileTap={{ scale: 0.97 }}
                style={{
                  display: 'flex', alignItems: 'center', gap: 5,
                  padding: '5px 12px', borderRadius: 7,
                  border: 'none', cursor: 'pointer', fontSize: 11, fontWeight: 600,
                  transition: 'all 0.15s',
                  background: active
                    ? 'linear-gradient(135deg, var(--accent), var(--purple))'
                    : 'transparent',
                  color: active ? '#fff' : 'var(--text-muted)',
                  boxShadow: active ? '0 0 12px var(--accent-glow)' : 'none',
                }}
              >
                <Icon size={11} />
                {label}
              </motion.button>
            )
          })}
        </div>
      </div>

      {/* Content */}
      <AnimatePresence mode="wait">
        <motion.div
          key={tab}
          initial={{ opacity: 0, y: 6 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: -6 }}
          transition={{ duration: 0.18 }}
          style={{
            padding: 16, background: 'var(--bg-secondary)',
            borderRadius: 12, border: '1px solid var(--border)',
          }}
        >
          {paragraphs.map((para, i) => (
            <p
              key={i}
              style={{
                fontSize: tab === 'simple' ? 14 : 12,
                color: tab === 'simple' ? 'var(--text-primary)' : 'var(--text-secondary)',
                lineHeight: tab === 'simple' ? 1.9 : 1.75,
                marginBottom: i < paragraphs.length - 1 ? 14 : 0,
                fontFamily: tab === 'technical' ? 'var(--font-mono)' : 'inherit',
                whiteSpace: tab === 'technical' ? 'pre-wrap' : 'normal',
              }}
            >
              {para}
            </p>
          ))}
        </motion.div>
      </AnimatePresence>
    </motion.div>
  )
}
