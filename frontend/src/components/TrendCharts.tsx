import { useId } from 'react'
import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import type { MonitoringRecord } from '../monitoring/types'

interface TrendPoint {
  time: number
  stamp: string
  value: number
}

interface RawPoint extends Omit<TrendPoint, 'value'> {
  value: number | null
}

const labelFormat = new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' })
const tickFormat = new Intl.DateTimeFormat(undefined, { hour: '2-digit', minute: '2-digit' })

function sortChronologically(records: MonitoringRecord[]): MonitoringRecord[] {
  // The API returns newest-first; charts read left-to-right in time order.
  return records.slice().sort((a, b) => Date.parse(a.timestamp) - Date.parse(b.timestamp))
}

function TrendChart({ records, pick, name, unit, color, ariaLabel, emptyMessage, height = 220 }: {
  records: MonitoringRecord[]
  pick: (record: MonitoringRecord) => number | null
  name: string
  unit: string
  color: string
  ariaLabel: string
  emptyMessage: string
  height?: number
}) {
  const gradientId = useId()
  const raw: RawPoint[] = sortChronologically(records).map((record) => ({
    time: Date.parse(record.timestamp),
    stamp: record.timestamp,
    value: pick(record),
  }))
  const points: TrendPoint[] = raw.filter((point): point is TrendPoint => point.value !== null)

  if (points.length === 0) {
    return <div className="rounded-xl border border-dashed border-[#1e2a45] p-6 text-sm text-[#8b9dc0]">{emptyMessage}</div>
  }

  return (
    <div style={{ height }} className="w-full">
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={points} margin={{ top: 8, right: 8, left: -8, bottom: 0 }}>
          <defs>
            <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%" stopColor={color} stopOpacity={0.35} />
              <stop offset="95%" stopColor={color} stopOpacity={0} />
            </linearGradient>
          </defs>
          <CartesianGrid strokeDasharray="3 3" stroke="#1e2a45" vertical={false} />
          <XAxis
            dataKey="time"
            type="number"
            domain={['dataMin', 'dataMax']}
            minTickGap={36}
            tickFormatter={(value: number) => tickFormat.format(new Date(value))}
            tick={{ fontSize: 11, fill: '#4a5a80' }}
            tickLine={false}
            axisLine={{ stroke: '#1e2a45' }}
          />
          <YAxis
            width={46}
            tickFormatter={(value: number) => String(value)}
            tick={{ fontSize: 11, fill: '#4a5a80' }}
            tickLine={false}
            axisLine={false}
          />
          <Tooltip
            labelFormatter={(label) => {
              const parsed = typeof label === 'number' ? label : Date.parse(String(label))
              return Number.isNaN(parsed) ? String(label) : labelFormat.format(new Date(parsed))
            }}
            formatter={(value) => [`${value ?? '—'} ${unit}`, name]}
            contentStyle={{ borderRadius: 12, border: '1px solid #1e2a45', fontSize: 12, background: '#0a0d16', color: '#f0f4ff' }}
          />
          <Area
            type="monotone"
            dataKey="value"
            name={name}
            stroke={color}
            strokeWidth={2}
            fill={`url(#${gradientId})`}
            dot={points.length <= 24}
            activeDot={{ r: 4 }}
            isAnimationActive={false}
            aria-label={ariaLabel}
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  )
}

const noData = (what: string) => `No ${what} has been recorded for this device yet.`

export function LatencyTrendChart({ records }: { records: MonitoringRecord[] }) {
  return (
    <TrendChart
      records={records}
      pick={(record) => record.latencyMs}
      name="Latency"
      unit="ms"
      color="#1558c9"
      ariaLabel="Latency over time"
      emptyMessage={noData('latency')}
    />
  )
}

export function PacketLossTrendChart({ records }: { records: MonitoringRecord[] }) {
  return (
    <TrendChart
      records={records}
      pick={(record) => record.packetLossPercent}
      name="Packet loss"
      unit="%"
      color="#f87171"
      ariaLabel="Packet loss over time"
      emptyMessage={noData('packet loss')}
    />
  )
}

export function HttpResponseTrendChart({ records }: { records: MonitoringRecord[] }) {
  return (
    <TrendChart
      records={records}
      pick={(record) => (record.httpOk === null ? null : record.httpResponseTimeMs)}
      name="Response time"
      unit="ms"
      color="#d4ff24"
      ariaLabel="HTTP response time over time"
      emptyMessage="No HTTP response time has been recorded. Configure an endpoint to start collecting it."
      height={200}
    />
  )
}
