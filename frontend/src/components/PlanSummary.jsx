import { useState, useEffect } from 'react'
import { motion } from 'framer-motion'
import { CheckCircle, XCircle, Shield, GitBranch, AlertTriangle, DatabaseZap, Check, Info } from 'lucide-react'
import { persistRouter } from '../utils/api'

function Stat({ label, value, color, delay }) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay }}
      style={{
        background: 'var(--bg-card)', border: '1px solid var(--border)',
        borderRadius: 14, padding: '20px 24px', textAlign: 'center',
        position: 'relative', overflow: 'hidden',
      }}
    >
      <div style={{
        position: 'absolute', inset: 0,
        background: `radial-gradient(circle at 50% 0%, ${color}08, transparent 70%)`,
      }} />
      <motion.div
        initial={{ scale: 0 }}
        animate={{ scale: 1 }}
        transition={{ delay: delay + 0.1, type: 'spring', stiffness: 200 }}
        style={{ fontSize: 36, fontWeight: 800, color, fontFamily: 'var(--font-mono)', lineHeight: 1 }}
      >
        {value}
      </motion.div>
      <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 6, textTransform: 'uppercase', letterSpacing: '1px' }}>
        {label}
      </div>
    </motion.div>
  )
}

function evaluateSaveEligibility(plan, originalSpec) {
  const similarity   = plan.similarity_score ?? 1.0
  const similarTo    = plan.similar_to
  const confidence   = plan.confidence?.score ?? 1.0
  const alreadyKnown = similarity === 1.0 && !similarTo

  if (alreadyKnown)
    return { canSave: false, blocked: false, alreadyInGraph: true, warning: null, reason: null }

  if (confidence < 0.50)
    return {
      canSave: false, blocked: true, alreadyInGraph: false, warning: null,
      reason: `Confidence ${Math.round(confidence * 100)}% is too low. Specs may be incomplete or incorrect. Verify before saving.`,
    }

  const submittedVendor = (originalSpec?.vendor || '').toLowerCase().trim()
  const matchedVendor   = (similarTo || '').split('_')[0].toLowerCase()
  const sameVendor      = submittedVendor && matchedVendor && submittedVendor.startsWith(matchedVendor)

  if (sameVendor && similarity >= 0.85)
    return {
      canSave: true, blocked: false, alreadyInGraph: false,
      warning: `${Math.round(similarity * 100)}% similar to ${similarTo} (same vendor). This router may be redundant in the graph. Save only if it has meaningfully different specs.`,
      reason: null,
    }

  if (!sameVendor && similarTo)
    return {
      canSave: true, blocked: false, alreadyInGraph: false,
      warning: null, reason: null,
      info: `Different vendor from ${similarTo}. Cross-vendor similarity is expected — this router is valid to save.`,
    }

  return { canSave: true, blocked: false, alreadyInGraph: false, warning: null, reason: null }
}

function useIsMobile() {
  const [mobile, setMobile] = useState(() => window.innerWidth < 768)
  useEffect(() => {
    const fn = () => setMobile(window.innerWidth < 768)
    window.addEventListener('resize', fn)
    return () => window.removeEventListener('resize', fn)
  }, [])
  return mobile
}

export default function PlanSummary({ plan, originalSpec, onSaved }) {
  const [saving, setSaving]       = useState(false)
  const [saved, setSaved]         = useState(false)
  const [saveError, setSaveError] = useState(null)
  const isMobile = useIsMobile()

  if (!plan) return null

  const needsReview = plan.plan_status === 'needs_review'
  const totalNodes  = plan.clusters.reduce((s, c) => s + c.node_count, 0)
  const totalVcpu   = plan.clusters.reduce((s, c) => s + c.total_vcpu, 0)
  const totalRam    = plan.clusters.reduce((s, c) => s + c.total_ram_gb, 0)
  const totalPorts  = plan.clusters.reduce((s, c) => s + c.total_ports, 0)

  const eligibility = evaluateSaveEligibility(plan, originalSpec)

  const handleSave = async () => {
    if (!originalSpec || saving || saved) return
    setSaving(true)
    setSaveError(null)
    try {
      await persistRouter(originalSpec)
      setSaved(true)
      onSaved?.(plan.router_id)
    } catch (e) {
      if (e.response?.status === 401) {
        setSaveError('Unauthorized. Set VITE_API_KEY in your .env to match API_SECRET_KEY.')
      } else {
        setSaveError(e.response?.data?.detail || 'Failed to save to graph')
      }
    } finally {
      setSaving(false)
    }
  }

  // Status badge — driven by plan_status first, then confidence
  function StatusBadge() {
    if (needsReview)
      return (
        <>
          <XCircle size={18} color="var(--red)" />
          <span style={{ fontSize: 13, fontWeight: 600, color: 'var(--red)' }}>Cannot plan — check inputs</span>
        </>
      )
    const conf  = plan.confidence?.score ?? 1.0
    const label = plan.confidence?.label
    if (!plan.valid)
      return (
        <>
          <XCircle size={18} color="var(--red)" />
          <span style={{ fontSize: 13, fontWeight: 600, color: 'var(--red)' }}>Invalid Plan</span>
        </>
      )
    if (label === 'VERY LOW' || conf < 0.35)
      return (
        <>
          <XCircle size={18} color="var(--red)" />
          <span style={{ fontSize: 13, fontWeight: 600, color: 'var(--red)' }}>Unreliable — check inputs</span>
        </>
      )
    if (label === 'LOW' || conf < 0.50)
      return (
        <>
          <AlertTriangle size={18} color="var(--yellow)" />
          <span style={{ fontSize: 13, fontWeight: 600, color: 'var(--yellow)' }}>Low Confidence</span>
        </>
      )
    return (
      <>
        <CheckCircle size={18} color="var(--green)" />
        <span style={{ fontSize: 13, fontWeight: 600, color: 'var(--green)' }}>Valid Plan</span>
      </>
    )
  }

  return (
    <motion.div
      initial={{ opacity: 0, y: -20 }}
      animate={{ opacity: 1, y: 0 }}
      style={{
        background: 'linear-gradient(135deg, var(--bg-card), var(--bg-secondary))',
        border: `1px solid ${needsReview ? 'var(--red)' : 'var(--border-bright)'}`,
        borderRadius: 20, padding: 28, marginBottom: 24,
        position: 'relative', overflow: 'hidden',
      }}
    >
      <div style={{
        position: 'absolute', top: -60, right: -60,
        width: 200, height: 200, borderRadius: '50%',
        background: needsReview
          ? 'radial-gradient(circle, rgba(255,68,102,0.12), transparent 70%)'
          : 'radial-gradient(circle, var(--accent-glow-strong), transparent 70%)',
        pointerEvents: 'none',
      }} />

      {/* Router identity + actions */}
      <div style={{ display: 'flex', flexDirection: isMobile ? 'column' : 'row', alignItems: isMobile ? 'stretch' : 'flex-start', justifyContent: 'space-between', marginBottom: 24, gap: 16 }}>
        <div>
          <div style={{ fontSize: 11, color: 'var(--text-muted)', letterSpacing: '1px', textTransform: 'uppercase', marginBottom: 6 }}>
            Deployment Plan For
          </div>
          <div style={{ fontSize: 26, fontWeight: 800, color: 'var(--text-primary)', letterSpacing: '-0.5px' }}>
            {plan.router_name || plan.router_id}
          </div>
          {plan.similar_to && !needsReview && (
            <div style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 4 }}>
              Reasoned via <span style={{ color: 'var(--accent)' }}>{plan.similar_to}</span>
              {' '}· {Math.round(plan.similarity_score * 100)}% similarity
              {eligibility.info && (
                <span style={{ color: 'var(--green)', marginLeft: 6 }}>· Different vendor ✓</span>
              )}
            </div>
          )}
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', alignItems: isMobile ? 'stretch' : 'flex-end', gap: 10 }}>
          {/* Status badge */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <StatusBadge />
          </div>

          {/* Topology badges — hidden when needs_review */}
          {!needsReview && (() => {
            const conf   = plan.confidence?.score ?? 1.0
            const dimmed = conf < 0.50
            return (
              <div style={{ display: 'flex', gap: 8, opacity: dimmed ? 0.4 : 1 }}>
                {plan.ha_enabled && (
                  <div style={{
                    display: 'flex', alignItems: 'center', gap: 5,
                    padding: '4px 10px', borderRadius: 20,
                    background: 'var(--green-dim)', border: '1px solid var(--green)',
                    fontSize: 11, color: 'var(--green)', fontWeight: 600,
                  }}>
                    <Shield size={11} /> HA Enabled
                  </div>
                )}
                <div style={{
                  display: 'flex', alignItems: 'center', gap: 5,
                  padding: '4px 10px', borderRadius: 20,
                  background: 'var(--accent-glow)', border: '1px solid var(--accent)',
                  fontSize: 11, color: 'var(--accent)', fontWeight: 600,
                }}>
                  <GitBranch size={11} /> {plan.topology_type?.replace(/_/g, ' ')}
                </div>
              </div>
            )
          })()}

          {/* Save section — hidden entirely when needs_review */}
          {!needsReview && (
            <>
              {eligibility.alreadyInGraph && (
                <div style={{
                  display: 'flex', alignItems: 'center', gap: 6,
                  padding: '8px 16px', borderRadius: 10,
                  background: 'var(--green-dim)', border: '1px solid var(--green)',
                  fontSize: 12, color: 'var(--green)', fontWeight: 600,
                }}>
                  <Check size={13} /> Already in Knowledge Graph
                </div>
              )}

              {eligibility.blocked && (
                <div style={{
                  display: 'flex', alignItems: 'center', gap: 6,
                  padding: '8px 16px', borderRadius: 10,
                  background: 'var(--red-dim)', border: '1px solid var(--red)',
                  fontSize: 12, color: 'var(--red)', fontWeight: 500, maxWidth: 260, textAlign: 'right',
                }}>
                  <XCircle size={13} style={{ flexShrink: 0 }} />
                  {eligibility.reason}
                </div>
              )}

              {eligibility.canSave && (
                saved ? (
                  <motion.div
                    initial={{ scale: 0.8, opacity: 0 }}
                    animate={{ scale: 1, opacity: 1 }}
                    style={{
                      display: 'flex', alignItems: 'center', gap: 6,
                      padding: '8px 16px', borderRadius: 10,
                      background: 'var(--green-dim)', border: '1px solid var(--green)',
                      fontSize: 12, color: 'var(--green)', fontWeight: 600,
                    }}
                  >
                    <Check size={13} /> Saved to Knowledge Graph ✓
                  </motion.div>
                ) : (
                  <motion.button
                    whileHover={{ scale: 1.03 }}
                    whileTap={{ scale: 0.97 }}
                    onClick={handleSave}
                    disabled={saving}
                    style={{
                      display: 'flex', alignItems: 'center', gap: 8,
                      padding: '8px 16px', borderRadius: 10,
                      cursor: saving ? 'wait' : 'pointer',
                      background: eligibility.warning
                        ? 'linear-gradient(135deg, #f59e0b, #d97706)'
                        : 'linear-gradient(135deg, var(--purple), var(--accent))',
                      border: 'none', color: '#fff', fontSize: 12, fontWeight: 600,
                      boxShadow: eligibility.warning
                        ? '0 0 20px rgba(245,158,11,0.3)'
                        : '0 0 20px rgba(168,85,247,0.3)',
                      opacity: saving ? 0.7 : 1,
                    }}
                  >
                    {saving ? (
                      <>
                        <motion.div
                          animate={{ rotate: 360 }}
                          transition={{ duration: 1, repeat: Infinity, ease: 'linear' }}
                          style={{ width: 13, height: 13, border: '2px solid rgba(255,255,255,0.3)', borderTopColor: '#fff', borderRadius: '50%' }}
                        />
                        Saving...
                      </>
                    ) : (
                      <><DatabaseZap size={13} /> Save to Knowledge Graph</>
                    )}
                  </motion.button>
                )
              )}

              {saveError && (
                <div style={{ fontSize: 11, color: 'var(--red)', maxWidth: 220, textAlign: 'right' }}>
                  {saveError}
                </div>
              )}
            </>
          )}
        </div>
      </div>

      {/* Vendor-aware warning */}
      {!needsReview && eligibility.warning && !saved && (
        <motion.div
          initial={{ opacity: 0, y: -8 }}
          animate={{ opacity: 1, y: 0 }}
          style={{
            display: 'flex', gap: 10, padding: '10px 14px',
            background: 'rgba(245,158,11,0.08)', border: '1px solid rgba(245,158,11,0.3)',
            borderRadius: 10, marginBottom: 20,
          }}
        >
          <Info size={14} color="#f59e0b" style={{ flexShrink: 0, marginTop: 1 }} />
          <span style={{ fontSize: 12, color: '#f59e0b', lineHeight: 1.6 }}>
            {eligibility.warning}
          </span>
        </motion.div>
      )}

      {/* Key metrics — always shown so user sees 0 clusters for needs_review */}
      <div style={{ display: 'grid', gridTemplateColumns: isMobile ? 'repeat(2, 1fr)' : 'repeat(5, 1fr)', gap: 12 }}>
        <Stat label="Clusters"   value={plan.cluster_count} color={needsReview ? 'var(--red)' : 'var(--accent)'}  delay={0.1} />
        <Stat label="Nodes"      value={totalNodes}          color={needsReview ? 'var(--red)' : 'var(--purple)'} delay={0.15} />
        <Stat label="Total vCPU" value={totalVcpu}           color={needsReview ? 'var(--red)' : 'var(--green)'}  delay={0.2} />
        <Stat label="RAM (GB)"   value={totalRam}            color={needsReview ? 'var(--red)' : 'var(--yellow)'} delay={0.25} />
        <Stat label="Ports"      value={totalPorts}          color={needsReview ? 'var(--red)' : '#ff8c42'}       delay={0.3} />
      </div>

      {/* Warnings */}
      {plan.warnings?.length > 0 && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ delay: 0.4 }}
          style={{ marginTop: 16 }}
        >
          {plan.warnings.map((w, i) => (
            <div key={i} style={{
              display: 'flex', gap: 8, padding: '8px 12px',
              background: 'var(--yellow-dim)', border: '1px solid rgba(255,215,0,0.2)',
              borderRadius: 8, marginBottom: 6,
            }}>
              <AlertTriangle size={13} color="var(--yellow)" style={{ flexShrink: 0, marginTop: 1 }} />
              <span style={{ fontSize: 11, color: 'var(--yellow)', lineHeight: 1.5 }}>{w}</span>
            </div>
          ))}
        </motion.div>
      )}
    </motion.div>
  )
}
