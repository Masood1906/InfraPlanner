import { useState, useEffect } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { Zap, Network, Database, MemoryStick, Hash, Layers, ChevronDown, ChevronUp, Send, RotateCcw } from 'lucide-react'

const PRESETS = {
  'Cisco 9300X': {
    model: 'Cisco 9300X', vendor: 'Cisco', series: '9300',
    switching_cap: { value: 640, unit: 'Gbps' },
    forwarding_rate: { value: 2232, unit: 'Mpps' },
    ipv4_routes: { value: 32000, unit: 'count' },
    dram_gb: { value: 8, unit: 'GB' },
    stacking_bw: { value: 1, unit: 'TBps' },
    vlan_ids: { value: 1200, unit: 'count' },
    mac_addresses: { value: 16000, unit: 'count' },
  },
  'Cisco 9200': {
    model: 'Cisco 9200', vendor: 'Cisco', series: '9200',
    switching_cap: { value: 176, unit: 'Gbps' },
    forwarding_rate: { value: 130, unit: 'Mpps' },
    ipv4_routes: { value: 8000, unit: 'count' },
    dram_gb: { value: 4, unit: 'GB' },
  },
  'Cisco ASR 1006-X': {
    model: 'Cisco ASR 1006-X', vendor: 'Cisco', series: 'ASR1000',
    switching_cap: { value: 200, unit: 'Gbps' },
    forwarding_rate: { value: 200, unit: 'Mpps' },
    ipv4_routes: { value: 4000000, unit: 'count' },
    dram_gb: { value: 64, unit: 'GB' },
  },
  'Juniper MX10008': {
    model: 'Juniper MX10008', vendor: 'Juniper', series: 'MX10000',
    switching_cap: { value: 192000, unit: 'Gbps' },
    forwarding_rate: { value: 12000, unit: 'Mpps' },
    ipv4_routes: { value: 8000000, unit: 'count' },
    dram_gb: { value: 512, unit: 'GB' },
  },
}

const EMPTY = {
  model: '', vendor: '', series: '',
  switching_cap: { value: '', unit: 'Gbps' },
  forwarding_rate: { value: '', unit: 'Mpps' },
  ipv4_routes: { value: '', unit: 'count' },
  dram_gb: { value: '', unit: 'GB' },
  stacking_bw: { value: '', unit: 'Gbps' },
  vlan_ids: { value: '', unit: 'count' },
  mac_addresses: { value: '', unit: 'count' },
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

function FieldGroup({ icon: Icon, label, color, children, isMobile }) {
  return (
    <div style={{ marginBottom: 20 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12 }}>
        <div style={{
          width: 28, height: 28, borderRadius: 8,
          background: `${color}18`,
          border: `1px solid ${color}40`,
          display: 'flex', alignItems: 'center', justifyContent: 'center',
        }}>
          <Icon size={13} color={color} />
        </div>
        <span style={{ fontSize: 11, fontWeight: 600, color, letterSpacing: '1px', textTransform: 'uppercase' }}>
          {label}
        </span>
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: isMobile ? '1fr' : '1fr 1fr', gap: 10 }}>
        {children}
      </div>
    </div>
  )
}

function Input({ label, value, onChange, unit, placeholder, required }) {
  return (
    <div style={{ minWidth: 0 }}>
      <label style={{ fontSize: 11, color: 'var(--text-muted)', display: 'block', marginBottom: 5 }}>
        {label} {required && <span style={{ color: 'var(--accent)' }}>*</span>}
      </label>
      <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
        <input
          value={value}
          onChange={e => onChange(e.target.value)}
          placeholder={placeholder || '0'}
          style={{
            flex: 1, minWidth: 0,
            background: 'var(--bg-secondary)',
            border: '1px solid var(--border)',
            borderRadius: 8, padding: '8px 10px',
            color: 'var(--text-primary)', fontSize: 13,
            fontFamily: 'var(--font-mono)',
            outline: 'none', transition: 'border-color 0.2s',
            width: '100%',
          }}
          onFocus={e => e.target.style.borderColor = 'var(--accent)'}
          onBlur={e => e.target.style.borderColor = 'var(--border)'}
        />
        {unit && (
          <div style={{
            flexShrink: 0, width: 48,
            padding: '8px 0', textAlign: 'center',
            background: 'var(--bg-primary)',
            border: '1px solid var(--border)', borderRadius: 8,
            fontSize: 10, color: 'var(--text-muted)', fontFamily: 'var(--font-mono)',
          }}>
            {unit}
          </div>
        )}
      </div>
    </div>
  )
}

function TextInput({ label, value, onChange, placeholder }) {
  return (
    <div>
      <label style={{ fontSize: 11, color: 'var(--text-muted)', display: 'block', marginBottom: 5 }}>
        {label}
      </label>
      <input
        value={value}
        onChange={e => onChange(e.target.value)}
        placeholder={placeholder}
        style={{
          width: '100%', background: 'var(--bg-secondary)',
          border: '1px solid var(--border)',
          borderRadius: 8, padding: '8px 12px',
          color: 'var(--text-primary)', fontSize: 13,
          outline: 'none', transition: 'border-color 0.2s',
        }}
        onFocus={e => e.target.style.borderColor = 'var(--accent)'}
        onBlur={e => e.target.style.borderColor = 'var(--border)'}
      />
    </div>
  )
}

// Known non-networking brands — mirrors parser/validator.py _NON_ROUTER_BRANDS.
// Huawei and Nokia are NOT in this list — they make real routers.
const NON_ROUTER_BRANDS = new Set([
  // Consumer electronics & phones
  'samsung', 'apple', 'sony', 'lg', 'xiaomi', 'oppo', 'vivo',
  'motorola', 'oneplus', 'realme', 'honor', 'blackberry',
  // PC / laptop brands
  'lenovo', 'dell', 'asus', 'acer', 'toshiba', 'razer', 'msi',
  // Consumer appliances
  'panasonic', 'philips', 'bosch', 'siemens', 'whirlpool', 'dyson',
  // Internet / social media
  'amazon', 'facebook', 'meta', 'twitter', 'netflix', 'spotify',
  'google', 'microsoft',
  // Automotive
  'toyota', 'honda', 'bmw', 'ford', 'tesla', 'volkswagen', 'mercedes',
  // Apparel
  'nike', 'adidas', 'puma', 'gucci',
  // Junk / test strings
  'test', 'testing', 'asdf', 'qwerty', 'hello', 'world', 'foo', 'bar',
  'baz', 'lorem', 'ipsum', 'random', 'unknown', 'example', 'sample',
  'dummy', 'fake', 'junk', 'garbage', 'invalid', 'none', 'null',
  'namio', 'xyz', 'abc', 'aaa', 'bbb',
])


// These are intentionally very permissive (well below any real router)
// so we only block clearly impossible inputs, not edge cases.
const FIELD_FLOORS = {
  switching_cap:   { min: 0.1,  hint: 'Smallest real switches start at ~24 Gbps' },
  forwarding_rate: { min: 0.1,  hint: 'Smallest real routers start at ~15 Mpps' },
  ipv4_routes:     { min: 10,   hint: 'Smallest real routers support at least 8,000 routes' },
  dram_gb:         { min: 0.5,  hint: 'Smallest real routers have at least 4 GB DRAM' },
}

function validateForm(form) {
  // 1. All required fields must be positive numbers
  const requiredNumeric = ['switching_cap', 'forwarding_rate', 'ipv4_routes', 'dram_gb']
  for (const key of requiredNumeric) {
    const v = parseFloat(form[key].value)
    if (!form[key].value || isNaN(v) || v <= 0)
      return 'All required fields must be positive numbers.'
  }

  // 2. Hard floor check — catches values like 1, 2, 5, 6
  for (const [key, { min, hint }] of Object.entries(FIELD_FLOORS)) {
    const v = parseFloat(form[key].value)
    if (!isNaN(v) && v < min)
      return `${key.replace('_', ' ')} = ${v} is too low to be a real device. ${hint}.`
  }

  // 3. Model name must not be purely numeric or a non-router brand
  const name = (form.model || '').trim()
  if (name.length > 0) {
    const digits = (name.match(/\d/g) || []).length
    const nonSpace = name.replace(/\s/g, '').length
    if (nonSpace > 0 && digits / nonSpace >= 0.8)
      return `Model name "${name}" looks like a number, not a router model. Please enter a real model name (e.g. Cisco 9300X).`
    const brand = name.toLowerCase().split(/\s+/)[0]
    if (NON_ROUTER_BRANDS.has(brand))
      return `"${name}" is not a network router. "${brand.charAt(0).toUpperCase() + brand.slice(1)}" is not a networking vendor. Please enter a real router model (e.g. Cisco 9300X, Juniper MX480).`
  }

  // 4. Forwarding/switching ratio sanity check
  const fwd  = parseFloat(form.forwarding_rate.value)
  const swit = parseFloat(form.switching_cap.value)
  if (!isNaN(fwd) && !isNaN(swit) && swit > 0) {
    const ratio = fwd / swit
    if (ratio > 500)
      return `Forwarding Rate (${fwd} Mpps) is ${ratio.toFixed(0)}× the Switching Capacity (${swit} Gbps). This is physically impossible. Real routers have ~0.3–2 Mpps per Gbps.`
  }

  return null  // all checks passed
}

export default function RouterForm({ onSubmit, loading }) {
  const [form, setForm] = useState(EMPTY)
  const [showOptional, setShowOptional] = useState(false)
  const [activePreset, setActivePreset] = useState(null)
  const [validationError, setValidationError] = useState(null)
  const isMobile = useIsMobile()

  const setField = (key, val) => setForm(f => ({ ...f, [key]: val }))
  const setFeature = (key, val) => setForm(f => ({ ...f, [key]: { ...f[key], value: val } }))

  const loadPreset = (name) => {
    setForm({ ...EMPTY, ...PRESETS[name] })
    setActivePreset(name)
    setShowOptional(true)
  }

  const reset = () => { setForm(EMPTY); setActivePreset(null); setValidationError(null) }

  const handleSubmit = (e) => {
    e.preventDefault()
    setValidationError(null)
    const error = validateForm(form)
    if (error) {
      setValidationError(error)
      return
    }
    const payload = {
      model: form.model, vendor: form.vendor || 'Unknown', series: form.series || '',
      switching_cap: { value: parseFloat(form.switching_cap.value), unit: form.switching_cap.unit },
      forwarding_rate: { value: parseFloat(form.forwarding_rate.value), unit: form.forwarding_rate.unit },
      ipv4_routes: { value: parseFloat(form.ipv4_routes.value), unit: form.ipv4_routes.unit },
      dram_gb: { value: parseFloat(form.dram_gb.value), unit: form.dram_gb.unit },
    }
    if (form.stacking_bw.value) payload.stacking_bw = { value: parseFloat(form.stacking_bw.value), unit: form.stacking_bw.unit }
    if (form.vlan_ids.value) payload.vlan_ids = { value: parseFloat(form.vlan_ids.value), unit: form.vlan_ids.unit }
    if (form.mac_addresses.value) payload.mac_addresses = { value: parseFloat(form.mac_addresses.value), unit: form.mac_addresses.unit }
    onSubmit(payload)
  }

  return (
    <div style={{
      background: 'var(--bg-card)',
      border: '1px solid var(--border)',
      borderRadius: 16, padding: 24,
    }}>
      {/* Presets */}
      <div style={{ marginBottom: 24 }}>
        <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 10, letterSpacing: '1px', textTransform: 'uppercase' }}>
          Quick Load — Example Routers
        </div>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
          {Object.keys(PRESETS).map(name => (
            <motion.button
              key={name}
              whileHover={{ scale: 1.03 }}
              whileTap={{ scale: 0.97 }}
              onClick={() => loadPreset(name)}
              style={{
                padding: '6px 14px', borderRadius: 20, fontSize: 12, fontWeight: 500,
                cursor: 'pointer', transition: 'all 0.2s',
                background: activePreset === name ? 'var(--accent-glow)' : 'var(--bg-secondary)',
                border: `1px solid ${activePreset === name ? 'var(--accent)' : 'var(--border)'}`,
                color: activePreset === name ? 'var(--accent)' : 'var(--text-secondary)',
              }}
            >
              {name}
            </motion.button>
          ))}
        </div>
      </div>

      <form onSubmit={handleSubmit}>
        {/* Identity */}
        <FieldGroup icon={Layers} label="Router Identity" color="var(--accent)" isMobile={isMobile}>
          <div style={{ gridColumn: '1 / -1' }}>
            <TextInput label="Model Name *" value={form.model} onChange={v => setField('model', v)} placeholder="e.g. Cisco 9300X" />
          </div>
          <TextInput label="Vendor" value={form.vendor} onChange={v => setField('vendor', v)} placeholder="e.g. Cisco" />
          <TextInput label="Series" value={form.series} onChange={v => setField('series', v)} placeholder="e.g. 9300" />
        </FieldGroup>

        {/* Required specs */}
        <FieldGroup icon={Network} label="Switching & Forwarding" color="var(--purple)" isMobile={isMobile}>
          <Input label="Switching Capacity" required value={form.switching_cap.value} onChange={v => setFeature('switching_cap', v)} unit="Gbps" />
          <Input label="Forwarding Rate" required value={form.forwarding_rate.value} onChange={v => setFeature('forwarding_rate', v)} unit="Mpps" />
        </FieldGroup>

        <FieldGroup icon={Database} label="Routing Scale" color="var(--green)" isMobile={isMobile}>
          <Input label="IPv4 Routes" required value={form.ipv4_routes.value} onChange={v => setFeature('ipv4_routes', v)} unit="count" />
          <Input label="DRAM" required value={form.dram_gb.value} onChange={v => setFeature('dram_gb', v)} unit="GB" />
        </FieldGroup>

        {/* Optional */}
        <motion.button
          type="button"
          onClick={() => setShowOptional(s => !s)}
          style={{
            width: '100%', padding: '10px', marginBottom: 16,
            background: 'var(--bg-secondary)', border: '1px solid var(--border)',
            borderRadius: 10, cursor: 'pointer', color: 'var(--text-secondary)',
            fontSize: 12, display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 6,
          }}
        >
          {showOptional ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
          Optional Specifications
        </motion.button>

        <AnimatePresence>
          {showOptional && (
            <motion.div
              initial={{ height: 0, opacity: 0 }}
              animate={{ height: 'auto', opacity: 1 }}
              exit={{ height: 0, opacity: 0 }}
              style={{ overflow: 'hidden' }}
            >
              <FieldGroup icon={Zap} label="Stacking & VLANs" color="var(--yellow)" isMobile={isMobile}>
                <Input label="Stacking Bandwidth" value={form.stacking_bw.value} onChange={v => setFeature('stacking_bw', v)} unit="Gbps" />
                <Input label="VLAN IDs" value={form.vlan_ids.value} onChange={v => setFeature('vlan_ids', v)} unit="count" />
              </FieldGroup>
              <FieldGroup icon={Hash} label="MAC Addresses" color="var(--accent)" isMobile={isMobile}>
                <Input label="MAC Addresses" value={form.mac_addresses.value} onChange={v => setFeature('mac_addresses', v)} unit="count" />
              </FieldGroup>
            </motion.div>
          )}
        </AnimatePresence>

        {validationError && (
          <div style={{ fontSize: 12, color: 'var(--red)', marginBottom: 10,
            padding: '8px 12px', borderRadius: 8,
            background: 'var(--red-dim)', border: '1px solid var(--red)' }}>
            {validationError}
          </div>
        )}
        {/* Actions */}
        <div style={{ display: 'flex', gap: 10, marginTop: 8 }}>
          <motion.button
            type="button" onClick={reset}
            whileHover={{ scale: 1.02 }} whileTap={{ scale: 0.98 }}
            style={{
              padding: '12px 16px', borderRadius: 10, cursor: 'pointer',
              background: 'var(--bg-secondary)', border: '1px solid var(--border)',
              color: 'var(--text-muted)',
            }}
          >
            <RotateCcw size={15} />
          </motion.button>

          <motion.button
            type="submit" disabled={loading || !form.model}
            whileHover={{ scale: loading ? 1 : 1.02 }}
            whileTap={{ scale: loading ? 1 : 0.98 }}
            style={{
              flex: 1, padding: '12px 20px', borderRadius: 10,
              cursor: loading || !form.model ? 'not-allowed' : 'pointer',
              background: loading || !form.model
                ? 'var(--bg-secondary)'
                : 'linear-gradient(135deg, var(--accent), var(--purple))',
              border: 'none', color: '#fff', fontSize: 14, fontWeight: 600,
              display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8,
              boxShadow: loading || !form.model ? 'none' : '0 0 30px var(--accent-glow)',
              opacity: !form.model ? 0.5 : 1,
            }}
          >
            {loading ? (
              <>
                <motion.div
                  animate={{ rotate: 360 }}
                  transition={{ duration: 1, repeat: Infinity, ease: 'linear' }}
                  style={{ width: 16, height: 16, border: '2px solid rgba(255,255,255,0.3)', borderTopColor: '#fff', borderRadius: '50%' }}
                />
                Analyzing...
              </>
            ) : (
              <><Send size={15} /> Generate Plan</>
            )}
          </motion.button>
        </div>
      </form>
    </div>
  )
}
