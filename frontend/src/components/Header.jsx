import { motion } from 'framer-motion'
import { Activity, Cpu, GitBranch } from 'lucide-react'
import { useEffect, useState } from 'react'
import { getHealth } from '../utils/api'

function useIsMobile() {
  const [mobile, setMobile] = useState(() => window.innerWidth < 768)
  useEffect(() => {
    const fn = () => setMobile(window.innerWidth < 768)
    window.addEventListener('resize', fn)
    return () => window.removeEventListener('resize', fn)
  }, [])
  return mobile
}

export default function Header() {
  const [health, setHealth] = useState(null)
  const isMobile = useIsMobile()

  useEffect(() => {
    let mounted = true
    const fetch = () =>
      getHealth()
        .then(d  => { if (mounted) setHealth(d) })
        .catch(() => { if (mounted) setHealth(null) })
    fetch()
    const t = setInterval(fetch, 10000)
    return () => { mounted = false; clearInterval(t) }
  }, [])

  return (
    <motion.header
      initial={{ y: -60, opacity: 0 }}
      animate={{ y: 0, opacity: 1 }}
      transition={{ duration: 0.6, ease: 'easeOut' }}
      style={{
        position: 'fixed', top: 0, left: 0, right: 0, zIndex: 100,
        background: 'rgba(5, 8, 16, 0.85)',
        backdropFilter: 'blur(20px)',
        borderBottom: '1px solid var(--border)',
        padding: isMobile ? '0 1rem' : '0 2rem',
        height: '64px',
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
      }}
    >
      {/* Logo */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
        <div style={{
          width: 36, height: 36, borderRadius: 10,
          background: 'linear-gradient(135deg, var(--accent), var(--purple))',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          boxShadow: '0 0 20px var(--accent-glow)',
        }}>
          <GitBranch size={18} color="#fff" />
        </div>
        <div>
          <div style={{ fontSize: 15, fontWeight: 700, letterSpacing: '-0.3px', color: 'var(--text-primary)' }}>
            InfraPlanner <span style={{ color: 'var(--accent)' }}>AI</span>
          </div>
          <div style={{ fontSize: 10, color: 'var(--text-muted)', letterSpacing: '1.5px', textTransform: 'uppercase' }}>
            Kubernetes Infrastructure Intelligence
          </div>
        </div>
      </div>

      {/* Status */}
      <div style={{ display: 'flex', alignItems: 'center', gap: isMobile ? '12px' : '24px' }}>
        {health && !isMobile && (
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <Cpu size={13} color="var(--text-muted)" />
            <span style={{ fontSize: 12, color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>
              {health.graph_nodes} graph nodes
            </span>
          </div>
        )}
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <motion.div
            animate={{ opacity: [1, 0.3, 1] }}
            transition={{ duration: 2, repeat: Infinity }}
            style={{
              width: 8, height: 8, borderRadius: '50%',
              background: health ? 'var(--green)' : 'var(--red)',
              boxShadow: health ? '0 0 8px var(--green)' : '0 0 8px var(--red)',
            }}
          />
          <span style={{ fontSize: 12, color: health ? 'var(--green)' : 'var(--red)', fontWeight: 500 }}>
            {health ? 'System Online' : 'Offline'}
          </span>
        </div>
        {!isMobile && (
          <div style={{
            display: 'flex', alignItems: 'center', gap: '6px',
            padding: '4px 12px', borderRadius: 20,
            border: '1px solid var(--border)',
            background: 'var(--bg-card)',
          }}>
            <Activity size={12} color="var(--accent)" />
            <span style={{ fontSize: 11, color: 'var(--accent)', fontWeight: 600, letterSpacing: '0.5px' }}>
              GraphRAG
            </span>
          </div>
        )}
      </div>
    </motion.header>
  )
}
