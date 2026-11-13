import { useNavigate } from 'react-router-dom'
import { Cell, LabelList, ReferenceLine, ResponsiveContainer, Scatter, ScatterChart, Tooltip, XAxis, YAxis, ZAxis } from 'recharts'
import { ACCENT_COLOR, BRAND_COLOR, CHART_AXIS, CHART_GRID } from '../../brand'
import { money, pct, points } from '../../components/story'
import type { AccountRow } from './shared'

type Side = 'right' | 'top' | 'left' | 'bottom'

interface Point {
  customer_id: string
  name: string
  label: string
  /** Revenue against plan over the last 12 months. */
  x: number
  /** Change in device share over the year. */
  y: number
  /** Revenue, for bubble size. */
  z: number
  at_risk: boolean
  /** Which side of its bubble the name goes, chosen so neighbouring names do not collide. */
  side: Side
  /** Bubble radius in pixels, to keep the name clear of it. */
  radius: number
}

/** Bubble area range in square pixels, as given to the Z axis. */
const AREA: [number, number] = [110, 760]

/** Round a bound outward to a whole 10 points, so every tick lands on one. */
const down = (v: number) => Math.floor(Math.round(v * 100) / 10) / 10
const up = (v: number) => Math.ceil(Math.round(v * 100) / 10) / 10

/** A tick every 10 points from `low` to `high`. */
const ticks = ([low, high]: [number, number]) =>
  Array.from({ length: Math.round((high - low) * 10) + 1 }, (_, i) => Math.round((low + i / 10) * 10) / 10)

/**
 * The ten accounts on two measures at once: how they are tracking against plan
 * (across) and whether our share of their new devices is growing (up), sized by
 * revenue. The accounts in trouble separate from the rest at the lower left.
 */
export default function PortfolioMap({ accounts }: { accounts: AccountRow[] }) {
  const navigate = useNavigate()
  const usable = accounts.filter((a) => a.plan_attainment != null && a.device_share_change != null && a.revenue_usd != null)
  if (usable.length === 0) return null

  // A first name is enough to label a bubble unless two accounts share it.
  const firstWords = usable.map((a) => a.customer_name.split(' ')[0])
  const points_: Point[] = usable.map((a, i) => ({
    customer_id: a.customer_id,
    name: a.customer_name,
    label: firstWords.filter((w) => w === firstWords[i]).length > 1 ? a.customer_name : firstWords[i],
    x: a.plan_attainment as number,
    y: a.device_share_change as number,
    z: a.revenue_usd as number,
    at_risk: a.at_risk,
    side: 'right',
    radius: 0,
  }))

  // Place names from the right edge inward: a name goes on the first side no nearby bubble has used.
  const zs = points_.map((p) => p.z)
  const zMin = Math.min(...zs)
  const zSpan = Math.max(...zs) - zMin || 1
  for (const p of points_) p.radius = Math.sqrt((AREA[0] + ((p.z - zMin) / zSpan) * (AREA[1] - AREA[0])) / Math.PI)
  const placed: Point[] = []
  for (const p of [...points_].sort((a, b) => b.x - a.x)) {
    const taken = new Set(placed.filter((q) => Math.abs(q.x - p.x) < 0.05 && Math.abs(q.y - p.y) < 0.08).map((q) => q.side))
    p.side = (['right', 'top', 'left', 'bottom'] as Side[]).find((side) => !taken.has(side)) ?? 'right'
    placed.push(p)
  }

  const xs = points_.map((p) => p.x)
  const ys = points_.map((p) => p.y)
  const xDomain: [number, number] = [down(Math.min(...xs, 0.95) - 0.02), up(Math.max(...xs, 1.05) + 0.02)]
  const yDomain: [number, number] = [down(Math.min(...ys, -0.05) - 0.02), up(Math.max(...ys, 0.05) + 0.02)]

  return (
    <figure>
      <figcaption className="mb-1 text-sm font-medium text-ink-light">
        Where each account stands: against plan, and in share of its new devices. Bubble size is revenue.
      </figcaption>
      <div className="relative h-[330px]" role="img" aria-label="Scatter of the top 10 by revenue against plan and change in device share. The same figures are in the table below.">
        <ResponsiveContainer width="100%" height="100%">
          <ScatterChart margin={{ top: 22, right: 48, bottom: 30, left: 4 }}>
            <XAxis
              type="number"
              dataKey="x"
              domain={xDomain}
              ticks={ticks(xDomain)}
              tickFormatter={(v: number) => `${Math.round(v * 100)}%`}
              tick={{ fontSize: 11, fill: CHART_AXIS }}
              axisLine={{ stroke: CHART_GRID }}
              tickLine={false}
              label={{ value: 'Revenue against plan, last 12 months', position: 'insideBottom', offset: -18, fontSize: 11, fill: CHART_AXIS }}
            />
            <YAxis
              type="number"
              dataKey="y"
              domain={yDomain}
              ticks={ticks(yDomain)}
              width={48}
              tickFormatter={(v: number) => `${v > 0 ? '+' : ''}${Math.round(v * 100)}`}
              tick={{ fontSize: 11, fill: CHART_AXIS }}
              axisLine={{ stroke: CHART_GRID }}
              tickLine={false}
              label={{ value: 'Device share, points vs a year ago', angle: -90, position: 'insideLeft', offset: 14, fontSize: 11, fill: CHART_AXIS, style: { textAnchor: 'middle' } }}
            />
            <ZAxis type="number" dataKey="z" range={AREA} />
            <ReferenceLine x={1} stroke="#9AA1AB" strokeDasharray="4 4" />
            <ReferenceLine y={0} stroke="#9AA1AB" strokeDasharray="4 4" />
            <Tooltip cursor={false} content={<MapTooltip />} />
            <Scatter
              data={points_}
              isAnimationActive={false}
              style={{ cursor: 'pointer' }}
              onClick={(entry: unknown) => {
                const e = entry as { customer_id?: string; payload?: { customer_id?: string } }
                const id = e.payload?.customer_id ?? e.customer_id
                if (id) navigate(id)
              }}
            >
              {points_.map((p) => (
                <Cell key={p.customer_id} fill={p.at_risk ? ACCENT_COLOR : BRAND_COLOR} fillOpacity={0.72} stroke="#fff" strokeWidth={1.5} />
              ))}
              <LabelList content={(props) => <PointName {...props} points={points_} />} />
            </Scatter>
          </ScatterChart>
        </ResponsiveContainer>
        <span className="pointer-events-none absolute bottom-[58px] left-[60px] text-[0.7rem] font-semibold uppercase tracking-wide text-accent/80">
          Behind plan, losing share
        </span>
      </div>
    </figure>
  )
}

/** A bubble's name. Recharts hands a label the bubble's top-left corner and size, not its center. */
function PointName({
  x,
  y,
  width,
  height,
  index,
  points,
}: {
  x?: number | string
  y?: number | string
  width?: number | string
  height?: number | string
  index?: number
  points: Point[]
}) {
  const p = index == null ? undefined : points[index]
  const w = Number(width ?? 0)
  const h = Number(height ?? 0)
  const cx = Number(x) + w / 2
  const cy = Number(y) + h / 2
  if (!p || Number.isNaN(cx) || Number.isNaN(cy)) return null
  const gap = Math.max(w, h) / 2 + 5
  const place = {
    right: { x: cx + gap, y: cy + 4, anchor: 'start' },
    left: { x: cx - gap, y: cy + 4, anchor: 'end' },
    top: { x: cx, y: cy - gap, anchor: 'middle' },
    bottom: { x: cx, y: cy + gap + 9, anchor: 'middle' },
  }[p.side] as { x: number; y: number; anchor: 'start' | 'end' | 'middle' }
  return (
    <text x={place.x} y={place.y} textAnchor={place.anchor} fontSize={11} fill="#151515" style={{ pointerEvents: 'none' }}>
      {p.label}
    </text>
  )
}

function MapTooltip({ active, payload }: { active?: boolean; payload?: { payload: Point }[] }) {
  const p = active ? payload?.[0]?.payload : undefined
  if (!p) return null
  return (
    <div className="rounded-lg border border-line bg-white px-3 py-2 text-xs shadow-tile">
      <div className="text-sm font-semibold text-ink">{p.name}</div>
      <div className="mt-1 text-ink-light">
        {money(p.z)} revenue · {pct(p.x)} of plan
      </div>
      <div className="text-ink-light">Device share {points(p.y)}</div>
      {p.at_risk && <div className="mt-1 font-medium text-accent">Risk signal in the last 120 days</div>}
      <div className="mt-1 text-ink-muted">Click to open</div>
    </div>
  )
}
