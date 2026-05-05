import { useState, useEffect } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import Header from './components/Header'
import RouterForm from './components/RouterForm'
import PlanSummary from './components/PlanSummary'
import ClusterView from './components/ClusterView'
import ConfidencePanel from './components/ConfidencePanel'
import ReasoningTrace from './components/ReasoningTrace'
import ExplanationPanel from './components/ExplanationPanel'
import GraphViewer from './components/GraphViewer'
import { generatePlan } from './utils/api'
import { LayoutDashboard, GitBranch } from 'lucide-react'

function useIsMobile() {
  const [mobile, setMobile] = useState(() => window.innerWidth < 768)
  useEffect(() => {
    const fn = () => setMobile(window.innerWidth < 768)
    window.addEventListener('resize', fn)
    return () => window.removeEventListener('resize', fn)
  }, [])
  return mobile
}

function Background() {
  return (
    <div style={{ position: 'fixed', inset: 0, pointerEvents: 'none', zIndex: 0 }}>
      <div style={{
        position: 'absolute', inset: 0,
        backgroundImage: `
          linear-gradient(rgba(0,212,255,0.03) 1px, transparent 1px),
          linear-gradient(90deg, rgba(0,212,255,0.03) 1px, transparent 1px)
        `,
        backgroundSize: '60px 60px',
      }} />
      <div style={{
        position: 'absolute', top: '10%', left: '15%',
        width: 600, height: 600, borderRadius: '50%',
        background: 'radial-gradient(circle, rgba(0,212,255,0.04), transparent 70%)',
      }} />
      <div style={{
        position: 'absolute', bottom: '10%', right: '10%',
        width: 500, height: 500, borderRadius: '50%',
        background: 'radial-gradient(circle, rgba(168,85,247,0.04), transparent 70%)',
      }} />
    </div>
  )
}

function EmptyState() {
  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      style={{
        display: 'flex', flexDirection: 'column',
        alignItems: 'center', justifyContent: 'center',
        height: '60vh', textAlign: 'center',
      }}
    >
      <motion.div
        animate={{ y: [0, -10, 0] }}
        transition={{ duration: 3, repeat: Infinity, ease: 'easeInOut' }}
        style={{
          width: 80, height: 80, borderRadius: 20, marginBottom: 24,
          background: 'linear-gradient(135deg, var(--accent-glow), var(--purple-dim))',
          border: '1px solid var(--border-bright)',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          fontSize: 32,
        }}
      >
        🧠
      </motion.div>
      <div style={{ fontSize: 20, fontWeight: 700, color: 'var(--text-primary)', marginBottom: 10 }}>
        Ready to Plan
      </div>
      <div style={{ fontSize: 13, color: 'var(--text-muted)', maxWidth: 320, lineHeight: 1.7 }}>
        Enter your router specifications on the left and click{' '}
        <span style={{ color: 'var(--accent)' }}>Generate Plan</span> to get an
        AI-powered Kubernetes infrastructure recommendation.
      </div>
      <div style={{ display: 'flex', gap: 16, marginTop: 32 }}>
        {['GraphRAG', 'Knowledge Graph', 'LLM Reasoning'].map(tag => (
          <div key={tag} style={{
            padding: '6px 14px', borderRadius: 20,
            border: '1px solid var(--border)',
            fontSize: 11, color: 'var(--text-muted)',
          }}>
            {tag}
          </div>
        ))}
      </div>
    </motion.div>
  )
}

const TABS = [
  { id: 'plan',  label: 'Deployment Plan',   icon: LayoutDashboard },
  { id: 'graph', label: 'Knowledge Graph',   icon: GitBranch },
]

export default function App() {
  const [plan, setPlan]             = useState(null)
  const [loading, setLoading]       = useState(false)
  const [error, setError]           = useState(null)
  const [lastSpec, setLastSpec]     = useState(null)
  const [activeTab, setActiveTab]   = useState('plan')
  const [newestRouterId, setNewestRouterId] = useState(null)
  const [highlightIds, setHighlightIds]     = useState(null)

  const handleSubmit = async (spec) => {
    setLoading(true)
    setError(null)
    setPlan(null)
    setLastSpec(spec)
    setActiveTab('plan')
    setNewestRouterId(null)
    try {
      const result = await generatePlan(spec)
      setPlan(result)
      setHighlightIds(result.graph_ids ?? null)
    } catch (e) {
      setError(e.response?.data?.detail || e.message || 'Request failed')
    } finally {
      setLoading(false)
    }
  }

  const isMobile = useIsMobile()

  return (
    <div style={{ minHeight: '100vh', position: 'relative' }}>
      <Background />
      <Header />

      <div style={{
        position: 'relative', zIndex: 1,
        maxWidth: 1400, margin: '0 auto',
        padding: isMobile ? '76px 12px 40px' : '88px 24px 40px',
        display: 'grid',
        gridTemplateColumns: (activeTab === 'graph' || isMobile) ? '1fr' : '380px 1fr',
        gap: 24,
        alignItems: 'start',
      }}>

        {/* Left panel — only on plan tab */}
        {activeTab === 'plan' && (
          <div style={{ position: isMobile ? 'static' : 'sticky', top: 80 }}>
            <motion.div
              initial={{ opacity: 0, x: -30 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ duration: 0.5 }}
            >
              <div style={{ fontSize: 11, color: 'var(--text-muted)', letterSpacing: '1px', textTransform: 'uppercase', marginBottom: 12 }}>
                Router Specification
              </div>
              <RouterForm onSubmit={handleSubmit} loading={loading} />
            </motion.div>
          </div>
        )}

        {/* Right / Main panel */}
        <div>
          {/* Tab bar */}
          <div style={{
            display: 'flex', gap: 4, marginBottom: 24,
            background: 'var(--bg-card)', border: '1px solid var(--border)',
            borderRadius: 12, padding: 4, width: isMobile ? '100%' : 'fit-content',
          }}>
            {TABS.map(tab => {
              const Icon = tab.icon
              const active = activeTab === tab.id
              return (
                <motion.button
                  key={tab.id}
                  onClick={() => setActiveTab(tab.id)}
                  whileHover={{ scale: 1.02 }}
                  whileTap={{ scale: 0.98 }}
                  style={{
                    display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8,
                    padding: '8px 18px', borderRadius: 9, flex: isMobile ? 1 : undefined,
                    cursor: 'pointer', fontSize: 13, fontWeight: 500,
                    border: 'none', transition: 'all 0.2s',
                    background: active
                      ? 'linear-gradient(135deg, var(--accent), var(--purple))'
                      : 'transparent',
                    color: active ? '#fff' : 'var(--text-muted)',
                    boxShadow: active ? '0 0 20px var(--accent-glow)' : 'none',
                  }}
                >
                  <Icon size={14} />
                  {tab.label}
                </motion.button>
              )
            })}
          </div>

          {/* Tab content */}
          <AnimatePresence mode="wait">
            {activeTab === 'graph' && (
              <motion.div
                key="graph"
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0 }}
              >
                <GraphViewer
                  highlightIds={highlightIds}
                  newestRouterId={newestRouterId}
                  onBack={() => setActiveTab('plan')}
                  onClearHighlight={() => setHighlightIds(null)}
                />
              </motion.div>
            )}

            {activeTab === 'plan' && (
              <motion.div key="plan" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
                <AnimatePresence mode="wait">
                  {error && (
                    <motion.div
                      key="error"
                      initial={{ opacity: 0, y: -10 }}
                      animate={{ opacity: 1, y: 0 }}
                      exit={{ opacity: 0 }}
                      style={{
                        padding: 16, borderRadius: 12, marginBottom: 20,
                        background: 'var(--red-dim)', border: '1px solid var(--red)',
                        fontSize: 13, color: 'var(--red)',
                      }}
                    >
                      ✗ {error}
                    </motion.div>
                  )}

                  {loading && (
                    <motion.div
                      key="loading"
                      initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
                      style={{
                        display: 'flex', flexDirection: 'column',
                        alignItems: 'center', justifyContent: 'center',
                        height: '50vh', gap: 20,
                      }}
                    >
                      <div style={{ position: 'relative', width: 80, height: 80 }}>
                        {[0, 1, 2].map(i => (
                          <motion.div
                            key={i}
                            animate={{ rotate: 360 }}
                            transition={{ duration: 1.5 + i * 0.5, repeat: Infinity, ease: 'linear' }}
                            style={{
                              position: 'absolute', inset: i * 12,
                              borderRadius: '50%',
                              border: '2px solid transparent',
                              borderTopColor: i === 0 ? 'var(--accent)' : i === 1 ? 'var(--purple)' : 'var(--green)',
                            }}
                          />
                        ))}
                      </div>
                      <div style={{ textAlign: 'center' }}>
                        <div style={{ fontSize: 15, fontWeight: 600, color: 'var(--text-primary)', marginBottom: 6 }}>
                          Analyzing Router Specifications
                        </div>
                        <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>
                          Traversing knowledge graph · Computing inference · Generating plan
                        </div>
                      </div>
                    </motion.div>
                  )}

                  {!loading && !plan && !error && <EmptyState key="empty" />}

                  {!loading && plan && (
                    <motion.div
                      key="plan"
                      initial={{ opacity: 0 }}
                      animate={{ opacity: 1 }}
                      style={{ display: 'flex', flexDirection: 'column', gap: 20 }}
                    >
                      <PlanSummary plan={plan} originalSpec={lastSpec} onSaved={id => setNewestRouterId(id)} />

                      {/* Rejection panel — shown when data quality gate fired */}
                      {plan.plan_status === 'needs_review' && (
                        <motion.div
                          initial={{ opacity: 0, y: 10 }}
                          animate={{ opacity: 1, y: 0 }}
                          style={{
                            padding: 28, borderRadius: 16,
                            background: 'var(--red-dim)',
                            border: '1px solid var(--red)',
                            display: 'flex', flexDirection: 'column', gap: 14,
                          }}
                        >
                          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                            <div style={{
                              width: 36, height: 36, borderRadius: 10, flexShrink: 0,
                              background: 'rgba(255,68,102,0.15)',
                              border: '1px solid var(--red)',
                              display: 'flex', alignItems: 'center', justifyContent: 'center',
                              fontSize: 18,
                            }}>⚠</div>
                            <div>
                              <div style={{ fontSize: 15, fontWeight: 700, color: 'var(--red)', marginBottom: 2 }}>
                                Cannot generate a reliable deployment plan
                              </div>
                              <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>
                                Data quality score: {Math.round((plan.data_quality_score ?? 0) * 100)}%
                                {plan.similarity_score !== undefined && (
                                  <> &middot; Graph similarity: {Math.round(plan.similarity_score * 100)}%</>
                                )}
                              </div>
                            </div>
                          </div>
                          {plan.plan_status_reason && (
                            <div style={{
                              fontSize: 13, color: 'var(--text-secondary)',
                              lineHeight: 1.7, padding: '12px 16px',
                              background: 'rgba(255,68,102,0.06)',
                              borderRadius: 10, border: '1px solid rgba(255,68,102,0.2)',
                            }}>
                              {plan.plan_status_reason}
                            </div>
                          )}
                          <div style={{ fontSize: 12, color: 'var(--text-muted)', lineHeight: 1.6 }}>
                            Please enter specifications for a real network router
                            (e.g. Cisco 9300X, Juniper MX480) with realistic values
                            for Switching Capacity, Forwarding Rate, IPv4 Routes, and DRAM.
                          </div>
                        </motion.div>
                      )}

                      {/* Full plan — only shown when data quality passed */}
                      {plan.plan_status !== 'needs_review' && (
                        <div style={{ display: 'grid', gridTemplateColumns: isMobile ? '1fr' : '1fr 280px', gap: 20, alignItems: 'start' }}>
                          <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
                            <div>
                              <div style={{ fontSize: 11, color: 'var(--text-muted)', letterSpacing: '1px', textTransform: 'uppercase', marginBottom: 14 }}>
                                Cluster Architecture
                              </div>
                              <ClusterView
                                clusters={plan.clusters}
                                topologyType={plan.topology_type}
                                patternName={plan.pattern_name}
                              />
                            </div>
                            <ExplanationPanel explanation={plan.explanation} simple_explanation={plan.simple_explanation} />
                            <ReasoningTrace reasoning={plan.reasoning} />
                          </div>
                          <ConfidencePanel confidence={plan.confidence} />
                        </div>
                      )}
                    </motion.div>
                  )}
                </AnimatePresence>
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      </div>
    </div>
  )
}
