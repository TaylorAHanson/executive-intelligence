import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { CHART_AXIS, CHART_GRID, SERIES_COLORS } from '../../brand'
import type { DashboardQuery } from '../../hooks/useDashboardQuery'
import { pivotRows, type ChartRow, type Series } from './chartData'
import { formatValue, type ValueFormat } from './format'
import WidgetCard, { type WidgetFrameProps } from './WidgetCard'
import WidgetState from './WidgetState'

interface ChartCardProps<Row> extends WidgetFrameProps {
  query: DashboardQuery<Row>
  kind: 'line' | 'area' | 'bar' | 'stacked-bar'
  /** Column on the x axis. Rows must arrive ordered by it. */
  x: string
  xFormat?: ValueFormat
  yFormat?: ValueFormat
  /** Wide rows: one column per series. */
  series?: Series[]
  /**
   * Long rows: one row per (x, series) pair, pivoted here. Prefer this when
   * the set of series comes from the data, such as one per region.
   */
  pivot?: { seriesKey: string; valueKey: string }
  /**
   * `zero` starts the y axis at 0; `fit` fits it to the data. Defaults to `fit`
   * for lines, where a rate moving between 88% and 95% would otherwise look
   * flat, and `zero` for bars and areas, whose length must stay proportional.
   */
  yAxis?: 'zero' | 'fit'
  height?: number
}

export default function ChartCard<Row>({
  query,
  kind,
  x,
  xFormat = 'text',
  yFormat = 'number',
  series,
  pivot,
  yAxis = kind === 'line' ? 'fit' : 'zero',
  height = 280,
  span = 6,
  ...frame
}: ChartCardProps<Row>) {
  return (
    <WidgetCard span={span} {...frame}>
      <WidgetState query={query} skeleton="chart">
        {(result) => {
          const source = result.rows as ChartRow[]
          const data = pivot ? pivotRows(source, x, pivot.seriesKey, pivot.valueKey) : { rows: source, series: series ?? [] }
          return (
            <div style={{ height }}>
              <ResponsiveContainer width="100%" height="100%">
                {renderChart(kind, data.rows, data.series, x, xFormat, yFormat, yAxis)}
              </ResponsiveContainer>
            </div>
          )
        }}
      </WidgetState>
    </WidgetCard>
  )
}

function renderChart(
  kind: ChartCardProps<unknown>['kind'],
  rows: ChartRow[],
  series: Series[],
  x: string,
  xFormat: ValueFormat,
  yFormat: ValueFormat,
  yAxis: 'zero' | 'fit',
) {
  const color = (i: number) => SERIES_COLORS[i % SERIES_COLORS.length]
  const axes = [
    <CartesianGrid key="grid" stroke={CHART_GRID} strokeDasharray="3 3" vertical={false} />,
    <XAxis
      key="x"
      dataKey={x}
      tickFormatter={(v) => formatValue(v, xFormat)}
      tick={{ fill: CHART_AXIS, fontSize: 11 }}
      tickLine={false}
      axisLine={{ stroke: CHART_GRID }}
      minTickGap={16}
    />,
    <YAxis
      key="y"
      domain={yAxis === 'fit' ? ['auto', 'auto'] : [0, 'auto']}
      tickFormatter={(v) => formatValue(v, yFormat === 'currency' ? 'currencyCompact' : yFormat)}
      tick={{ fill: CHART_AXIS, fontSize: 11 }}
      tickLine={false}
      axisLine={false}
      width={56}
    />,
    <Tooltip
      key="tooltip"
      labelFormatter={(v) => formatValue(v, xFormat)}
      formatter={(v) => formatValue(v, yFormat)}
      contentStyle={{ borderRadius: 8, borderColor: CHART_GRID, fontSize: 12 }}
    />,
    ...(series.length > 1 ? [<Legend key="legend" iconType="circle" wrapperStyle={{ fontSize: 12 }} />] : []),
  ]
  const margin = { top: 4, right: 8, bottom: 0, left: 0 }

  if (kind === 'line') {
    return (
      <LineChart data={rows} margin={margin}>
        {axes}
        {series.map((s, i) => (
          <Line key={s.key} type="monotone" dataKey={s.key} name={s.label} stroke={color(i)} strokeWidth={2} dot={false} />
        ))}
      </LineChart>
    )
  }
  if (kind === 'area') {
    return (
      <AreaChart data={rows} margin={margin}>
        {axes}
        {series.map((s, i) => (
          <Area
            key={s.key}
            type="monotone"
            dataKey={s.key}
            name={s.label}
            stackId="stack"
            stroke={color(i)}
            fill={color(i)}
            fillOpacity={0.15}
          />
        ))}
      </AreaChart>
    )
  }
  const stacked = kind === 'stacked-bar'
  return (
    <BarChart data={rows} margin={margin}>
      {axes}
      {series.map((s, i) => (
        <Bar
          key={s.key}
          dataKey={s.key}
          name={s.label}
          fill={color(i)}
          stackId={stacked ? 'stack' : undefined}
          radius={stacked && i < series.length - 1 ? 0 : [3, 3, 0, 0]}
          maxBarSize={36}
        />
      ))}
    </BarChart>
  )
}
