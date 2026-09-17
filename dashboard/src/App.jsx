import { useState, useEffect, useRef } from 'react'
import { AreaChart, Area, ResponsiveContainer } from 'recharts'

const WS_URL = 'ws://localhost:8000/ws/metrics'

// 10-color pool for up to 10 dynamic zones
const COLOR_POOL = [
  '#00ff88',
  '#4488ff',
  '#aa44ff',
  '#ff8844',
  '#ffaa00',
  '#00ffcc',
  '#ff44aa',
  '#88ffaa',
  '#ffcc44',
  '#44ccff',
]

const mono  = { fontFamily: "'Courier New', monospace" }
const panel = { background: '#111', border: '1px solid #222', padding: 16 }

function zoneColor(i) { return COLOR_POOL[i % COLOR_POOL.length] }

// ── TopBar ──────────────────────────────────────────────────────────────────
function TopBar({ connected, time }) {
  return (
    <div style={{
      height: 40, background: '#111111', borderBottom: '1px solid #1a1a1a',
      display: 'flex', alignItems: 'center', justifyContent: 'space-between',
      padding: '0 20px', flexShrink: 0,
    }}>
      <span style={{ ...mono, fontSize: 14, color: '#fff', letterSpacing: 1 }}>
        Line Analyser 2
      </span>
      <div style={{
        ...mono, fontSize: 12, padding: '3px 12px', borderRadius: 12,
        background: connected ? '#001a0d' : '#1a0000',
        border: `1px solid ${connected ? '#00ff88' : '#ff4444'}`,
        color: connected ? '#00ff88' : '#ff4444',
      }}>
        {connected ? '● LIVE' : '● DISCONNECTED'}
      </div>
      <span style={{ ...mono, fontSize: 12, color: '#444' }}>
        {time.toLocaleTimeString()}
      </span>
    </div>
  )
}

// ── KPI Cards ───────────────────────────────────────────────────────────────
function KPICard({ label, value, sub, subColor, dim }) {
  return (
    <div style={{
      flex: 1, background: '#111111', display: 'flex', flexDirection: 'column',
      alignItems: 'center', justifyContent: 'center', height: 140,
      borderRight: '1px solid #1a1a1a',
      opacity: dim ? 0.25 : 1, transition: 'opacity 0.4s',
    }}>
      <span style={{ ...mono, fontSize: 11, color: '#555', letterSpacing: 3, marginBottom: 10 }}>
        {label}
      </span>
      <span style={{ ...mono, fontSize: 36, color: '#fff', fontVariantNumeric: 'tabular-nums', lineHeight: 1 }}>
        {value}
      </span>
      <span style={{ ...mono, fontSize: 11, color: subColor, marginTop: 10 }}>
        {sub}
      </span>
    </div>
  )
}

function KPICards({ metrics }) {
  const dim = !metrics
  const ct  = metrics?.cycle_time
  return (
    <div style={{ display: 'flex', borderBottom: '1px solid #1a1a1a', flexShrink: 0 }}>
      <KPICard label="THROUGHPUT"
        value={metrics ? metrics.throughput_per_min.toFixed(1) : '—'}
        sub="items / min" subColor="#00ff88" dim={dim} />
      <KPICard label="ON BELT"
        value={metrics ? String(metrics.active_items) : '—'}
        sub="being tracked" subColor="#4488ff" dim={dim} />
      <KPICard label="CYCLE TIME"
        value={ct ? `${ct.mean.toFixed(1)}s` : '—'}
        sub={ct ? `p90: ${ct.p90.toFixed(1)}s` : '—'}
        subColor="#ffaa00" dim={dim} />
      <KPICard label="COMPLETED"
        value={metrics ? String(metrics.completed_items) : '—'}
        sub="this session" subColor="#888" dim={dim} />
    </div>
  )
}

// ── Conveyor Belt ────────────────────────────────────────────────────────────
const ITEM_W       = 48
const ITEM_H       = 32
const NORMAL_SPEED = 60
const SLOW_SPEED   = 15

function ConveyorBelt({ metrics }) {
  const containerRef = useRef(null)
  const svgSizeRef   = useRef({ w: 800, h: 500 })
  const [svgSize, setSvgSize] = useState({ w: 800, h: 500 })

  const animRef     = useRef(null)
  const lastTsRef   = useRef(null)
  const beltItemsRef = useRef({})
  const bnZoneRef   = useRef(-1)
  const zoneCountRef = useRef(6)
  const [renderItems, setRenderItems] = useState([])

  // pull zone count + bn zone into refs so animation loop stays current
  useEffect(() => {
    bnZoneRef.current   = metrics?.bottleneck?.avg_dwell > 0 ? metrics.bottleneck.zone : -1
    zoneCountRef.current = metrics?.zones?.count ?? 6
  }, [metrics])

  // sync real items from websocket
  useEffect(() => {
    const { w, h } = svgSizeRef.current
    const zc    = metrics?.zones?.count ?? 6
    const zoneW = w / zc
    const beltY = h * 0.38
    const beltH = h * 0.26
    const itemY = beltY + (beltH - ITEM_H) / 2

    const realItems = metrics?.items ?? []
    const realIds   = new Set(realItems.map(i => i.id))

    for (const id of Object.keys(beltItemsRef.current)) {
      if (!realIds.has(Number(id))) delete beltItemsRef.current[id]
    }

    for (const item of realItems) {
      if (!(item.id in beltItemsRef.current)) {
        beltItemsRef.current[item.id] = {
          id: item.id, x: item.zone * zoneW + 4, y: itemY,
          wsZone: item.zone, zone: item.zone, dwell: item.dwell,
        }
      } else {
        const belt = beltItemsRef.current[item.id]
        belt.dwell  = item.dwell
        belt.y      = itemY
        if (item.zone > belt.wsZone) {
          belt.x      = Math.max(belt.x, item.zone * zoneW + 4)
          belt.wsZone = item.zone
        }
      }
    }
  }, [metrics])

  // resize observer
  useEffect(() => {
    if (!containerRef.current) return
    const ro = new ResizeObserver(([entry]) => {
      const { width, height } = entry.contentRect
      svgSizeRef.current = { w: width, h: height }
      setSvgSize({ w: width, h: height })
    })
    ro.observe(containerRef.current)
    return () => ro.disconnect()
  }, [])

  // animation loop
  useEffect(() => {
    function tick(ts) {
      if (lastTsRef.current === null) lastTsRef.current = ts
      const dt = Math.min((ts - lastTsRef.current) / 1000, 0.05)
      lastTsRef.current = ts

      const { w, h } = svgSizeRef.current
      const zc    = zoneCountRef.current
      const zoneW = w / zc
      const beltY = h * 0.38
      const beltH = h * 0.26
      const itemY = beltY + (beltH - ITEM_H) / 2

      for (const item of Object.values(beltItemsRef.current)) {
        const zone      = Math.max(0, Math.min(zc - 1, Math.floor((item.x + ITEM_W / 2) / zoneW)))
        const speed     = zone === bnZoneRef.current ? SLOW_SPEED : NORMAL_SPEED
        const zoneRight = (zone + 1) * zoneW - ITEM_W - 4
        item.x    = Math.min(item.x + speed * dt, zoneRight)
        item.zone = zone
        item.y    = itemY
      }

      setRenderItems(Object.values(beltItemsRef.current).map(i => ({ ...i })))
      animRef.current = requestAnimationFrame(tick)
    }

    animRef.current = requestAnimationFrame(tick)
    return () => { cancelAnimationFrame(animRef.current); lastTsRef.current = null }
  }, [])

  const { w, h } = svgSize
  const zc     = metrics?.zones?.count ?? 6
  const zones  = metrics?.zones?.names ?? Array.from({ length: zc }, (_, i) => `Zone ${i + 1}`)
  const zoneW  = w / zc
  const beltY  = h * 0.38
  const beltH  = h * 0.26
  const bnZone = metrics?.bottleneck?.avg_dwell > 0 ? metrics.bottleneck.zone : -1

  return (
    <div ref={containerRef} style={{
      flex: 1, background: '#0d0d0d', border: '1px solid #222',
      borderRadius: 4, overflow: 'hidden',
    }}>
      <svg width="100%" height="100%" style={{ display: 'block' }}>

        {/* Zone fills */}
        {zones.map((_, i) => (
          <rect key={i} x={i * zoneW} y={0} width={zoneW} height={h}
            fill={zoneColor(i)} fillOpacity={i === bnZone ? 0.08 : 0.03} />
        ))}

        {/* Belt track */}
        <rect x={0} y={beltY} width={w} height={beltH} fill="#1a1a1a" />
        <line x1={0} y1={beltY}         x2={w} y2={beltY}         stroke="#333" strokeWidth={1} />
        <line x1={0} y1={beltY + beltH} x2={w} y2={beltY + beltH} stroke="#333" strokeWidth={1} />

        {/* Zone dividers */}
        {zones.map((_, i) => i > 0 && (
          <line key={i} x1={i * zoneW} y1={0} x2={i * zoneW} y2={h} stroke="#222" strokeWidth={1} />
        ))}

        {/* Bottleneck glow border */}
        {bnZone >= 0 && (
          <rect className="bn-glow"
            x={bnZone * zoneW + 1} y={1} width={zoneW - 2} height={h - 2}
            fill="none" stroke="#ff4444" strokeWidth={1.5} />
        )}

        {/* Zone labels */}
        {zones.map((name, i) => (
          <g key={i}>
            <text x={i * zoneW + 10} y={24}
              fill={i === bnZone ? '#ff4444' : zoneColor(i)}
              fontSize={12} fontFamily="'Courier New', monospace"
              fontWeight={i === bnZone ? 'bold' : 'normal'}>
              {name}
            </text>
            {i === bnZone && (
              <text className="bn-text" x={i * zoneW + 10} y={40}
                fill="#ff4444" fontSize={10} fontFamily="'Courier New', monospace">
                ▼ BOTTLENECK
              </text>
            )}
          </g>
        ))}

        {/* Items */}
        {renderItems.map(item => (
          <g key={item.id}>
            <rect x={item.x} y={item.y} width={ITEM_W} height={ITEM_H} rx={4}
              fill={zoneColor(item.zone)} fillOpacity={0.2}
              stroke={zoneColor(item.zone)} strokeWidth={1.5} />
            <text x={item.x + 2} y={item.y - 4}
              fill={zoneColor(item.zone)}
              fontSize={10} fontFamily="'Courier New', monospace">
              #{item.id}
            </text>
            <text x={item.x + ITEM_W / 2} y={item.y + ITEM_H / 2 + 4}
              fill="#fff" fontSize={9} fontFamily="'Courier New', monospace" textAnchor="middle">
              {item.dwell.toFixed(1)}s
            </text>
          </g>
        ))}
      </svg>
    </div>
  )
}

// ── Zone Dwell Chart ─────────────────────────────────────────────────────────
function ZoneDwellChart({ metrics }) {
  const zoneAvgs = metrics?.bottleneck?.zone_avgs ?? {}
  const zc       = metrics?.zones?.count ?? 6
  const names    = metrics?.zones?.names ?? Array.from({ length: zc }, (_, i) => `Zone ${i + 1}`)
  const dwells   = names.map((_, i) => zoneAvgs[String(i)] ?? 0)
  const maxDwell = Math.max(...dwells, 1)
  const bnZone   = metrics?.bottleneck?.avg_dwell > 0 ? metrics.bottleneck.zone : -1

  return (
    <div style={panel}>
      <div style={{ ...mono, fontSize: 11, color: '#444', letterSpacing: 3, marginBottom: 14 }}>
        ZONE DWELL
      </div>
      {names.map((name, i) => (
        <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 9 }}>
          <span style={{ ...mono, fontSize: 10, color: '#555', width: 70, flexShrink: 0 }}>
            {name}
          </span>
          <div style={{ flex: 1, height: 5, background: '#1a1a1a', borderRadius: 2, overflow: 'hidden' }}>
            <div style={{
              height: '100%',
              width: `${(dwells[i] / maxDwell) * 100}%`,
              background: zoneColor(i),
              boxShadow: i === bnZone ? `0 0 8px ${zoneColor(i)}` : 'none',
              transition: 'width 0.8s ease',
              borderRadius: 2,
            }} />
          </div>
          <span style={{ ...mono, fontSize: 10, color: zoneColor(i), width: 38, textAlign: 'right', flexShrink: 0 }}>
            {dwells[i].toFixed(1)}s
          </span>
        </div>
      ))}
    </div>
  )
}

// ── Alerts Feed ──────────────────────────────────────────────────────────────
function AlertsFeed({ latestAlerts, metrics }) {
  const [feed, setFeed] = useState([])

  useEffect(() => {
    if (!latestAlerts.length) return
    const ts = new Date().toLocaleTimeString()
    setFeed(prev => [...latestAlerts.map(text => ({ text, ts })), ...prev].slice(0, 6))
  }, [latestAlerts])

  const bn      = metrics?.bottleneck
  const bnAlert = bn && bn.avg_dwell > 0 && bn.zone !== -1
    ? `⚠ Bottleneck at ${bn.zone_name} — avg dwell ${bn.avg_dwell}s`
    : null

  return (
    <div style={panel}>
      <div style={{ ...mono, fontSize: 11, color: '#444', letterSpacing: 3, marginBottom: 14 }}>
        ALERTS
      </div>
      {!bnAlert && feed.length === 0 ? (
        <div style={{ ...mono, fontSize: 11, color: '#00ff88' }}>● All systems nominal</div>
      ) : (
        <>
          {bnAlert && (
            <div style={{
              display: 'flex', justifyContent: 'space-between',
              borderLeft: '2px solid #ff4444', background: '#1a0000',
              padding: '5px 8px', marginBottom: 4,
            }}>
              <span style={{ ...mono, fontSize: 11, color: '#ff4444' }}>{bnAlert}</span>
            </div>
          )}
          {feed.map((item, i) => (
            <div key={i} style={{
              display: 'flex', justifyContent: 'space-between',
              borderLeft: '2px solid #ff4444', background: '#1a0000',
              padding: '5px 8px', marginBottom: 4, gap: 8,
            }}>
              <span style={{ ...mono, fontSize: 11, color: '#ff4444', flex: 1 }}>{item.text}</span>
              <span style={{ ...mono, fontSize: 10, color: '#333', flexShrink: 0 }}>{item.ts}</span>
            </div>
          ))}
        </>
      )}
    </div>
  )
}

// ── Throughput Sparkline ─────────────────────────────────────────────────────
function ThroughputSparkline({ history }) {
  return (
    <div style={panel}>
      <div style={{ ...mono, fontSize: 11, color: '#444', letterSpacing: 3, marginBottom: 10 }}>
        THROUGHPUT HISTORY
      </div>
      <ResponsiveContainer width="100%" height={72}>
        <AreaChart data={history} margin={{ top: 4, right: 0, left: 0, bottom: 0 }}>
          <Area type="monotone" dataKey="value"
            stroke="#00ff88" strokeWidth={1.5}
            fill="#00ff88" fillOpacity={0.1}
            dot={false} isAnimationActive={false} />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  )
}

// ── Cycle Time Breakdown ─────────────────────────────────────────────────────
function CycleTimeBreakdown({ cycleTime }) {
  const rows   = [
    { label: 'MEAN', key: 'mean', color: '#ffaa00' },
    { label: 'P90',  key: 'p90',  color: '#ffaa00' },
    { label: 'MIN',  key: 'min',  color: '#00ff88' },
    { label: 'MAX',  key: 'max',  color: '#ff4444' },
  ]
  const maxVal = cycleTime ? Math.max(cycleTime.max, 1) : 1

  return (
    <div style={panel}>
      <div style={{ ...mono, fontSize: 11, color: '#444', letterSpacing: 3, marginBottom: 14 }}>
        CYCLE TIME
      </div>
      {rows.map(({ label, key, color }) => (
        <div key={key} style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12 }}>
          <span style={{ ...mono, fontSize: 10, color: '#444', width: 34, flexShrink: 0 }}>{label}</span>
          <span style={{ ...mono, fontSize: 10, color, width: 44, flexShrink: 0 }}>
            {cycleTime ? `${cycleTime[key].toFixed(1)}s` : '—'}
          </span>
          <div style={{ flex: 1, height: 4, background: '#1a1a1a', borderRadius: 2, overflow: 'hidden' }}>
            <div style={{
              height: '100%',
              width: cycleTime ? `${(cycleTime[key] / maxVal) * 100}%` : '0%',
              background: color, borderRadius: 2, transition: 'width 0.8s ease',
            }} />
          </div>
        </div>
      ))}
    </div>
  )
}

// ── App ──────────────────────────────────────────────────────────────────────
export default function App() {
  const [metrics,   setMetrics]   = useState(null)
  const [connected, setConnected] = useState(false)
  const [history,   setHistory]   = useState([])
  const [alerts,    setAlerts]    = useState([])
  const [time,      setTime]      = useState(new Date())
  const wsRef        = useRef(null)
  const reconnectRef = useRef(null)

  useEffect(() => {
    function connect() {
      const ws = new WebSocket(WS_URL)
      wsRef.current = ws
      ws.onopen  = () => { setConnected(true); clearTimeout(reconnectRef.current) }
      ws.onclose = () => { setConnected(false); reconnectRef.current = setTimeout(connect, 3000) }
      ws.onerror = () => ws.close()
      ws.onmessage = e => {
        const data = JSON.parse(e.data)
        setMetrics(data)
        setHistory(h => [...h.slice(-59), { value: data.throughput_per_min }])
        if (data.alerts?.length) setAlerts(data.alerts)
      }
    }
    connect()
    return () => { wsRef.current?.close(); clearTimeout(reconnectRef.current) }
  }, [])

  useEffect(() => {
    const t = setInterval(() => setTime(new Date()), 1000)
    return () => clearInterval(t)
  }, [])

  return (
    <div style={{ height: '100vh', display: 'flex', flexDirection: 'column', background: '#0a0a0a', overflow: 'hidden' }}>
      <TopBar connected={connected} time={time} />
      <KPICards metrics={metrics} />

      <div style={{ flex: 1, display: 'flex', gap: 1, padding: 1, overflow: 'hidden', minHeight: 0 }}>

        <div style={{ flex: '0 0 65%', display: 'flex', flexDirection: 'column', minHeight: 0 }}>
          <ConveyorBelt metrics={metrics} />
        </div>

        <div style={{ flex: '0 0 35%', display: 'flex', flexDirection: 'column', gap: 1, overflow: 'auto', minHeight: 0 }}>
          <ZoneDwellChart      metrics={metrics} />
          <AlertsFeed          latestAlerts={alerts} metrics={metrics} />
          <ThroughputSparkline history={history} />
          <CycleTimeBreakdown  cycleTime={metrics?.cycle_time} />
        </div>

      </div>
    </div>
  )
}
