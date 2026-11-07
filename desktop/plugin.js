// hermes-tuneup Desktop pane: read-only. Shows when compaction really fires on
// every profile and the fix command for each finding. There is no write path:
// fixes are applied only when the user types the command.
import { Badge, Button, CopyButton, EmptyState, ErrorState, ScrollArea, Skeleton, relativeTime, useQuery } from '@hermes/plugin-sdk'
import { jsx, jsxs } from 'react/jsx-runtime'

const SEVERITY_ORDER = { high: 0, medium: 1, low: 2 }
const SEVERITY_VARIANT = { high: 'destructive', medium: 'warn', low: 'muted' }

function worstSeverity(profile) {
  const ranks = (profile.findings || []).map(f => SEVERITY_ORDER[f.severity] ?? 3)
  return ranks.length ? Math.min(...ranks) : 3
}

function sortProfiles(profiles) {
  return [...profiles].sort((a, b) => {
    if (a.active !== b.active) return a.active ? -1 : 1
    return worstSeverity(a) - worstSeverity(b) || a.name.localeCompare(b.name)
  })
}

function FindingRow({ finding }) {
  return jsxs('div', {
    className: 'flex flex-col gap-1 border-t border-(--ui-stroke-secondary) pt-2',
    children: [
      jsxs('div', {
        className: 'flex items-start gap-2',
        children: [
          jsx(Badge, { variant: SEVERITY_VARIANT[finding.severity] || 'muted', children: finding.severity.toUpperCase() }),
          jsx('span', { className: 'text-xs text-(--ui-text-secondary)', children: finding.summary })
        ]
      }),
      jsxs('div', {
        className: 'flex items-center gap-1',
        children: [
          jsx('code', { className: 'text-[0.7rem] text-(--ui-text-tertiary)', children: finding.fix_command }),
          jsx(CopyButton, { text: finding.fix_command, label: `Copy fix command for ${finding.code}`, appearance: 'icon' })
        ]
      })
    ]
  })
}

function RouteRow({ route }) {
  const detail = route.status === 'unresolved' ? `unresolved: ${route.note}` : route.explain
  return jsx('div', {
    className: 'text-[0.7rem] text-(--ui-text-tertiary)',
    children: `${route.role}: ${route.model} on ${route.provider}, ${detail}`
  })
}

function ProfileCard({ profile }) {
  const main = (profile.routes || []).find(r => r.role === 'main')
  const others = (profile.routes || []).filter(r => r.role !== 'main')
  const findings = [...(profile.findings || [])].sort((a, b) => (SEVERITY_ORDER[a.severity] ?? 3) - (SEVERITY_ORDER[b.severity] ?? 3))
  const header = jsxs('div', {
    className: 'flex items-center gap-2',
    children: [
      jsx('span', { className: 'text-sm font-medium', children: profile.name }),
      profile.active ? jsx(Badge, { variant: 'outline', children: 'active' }) : null
    ]
  })
  if (profile.status !== 'ok') {
    return jsxs('div', {
      className: 'flex flex-col gap-1 rounded border border-(--ui-stroke-secondary) p-2',
      children: [header, jsx('div', { className: 'text-xs text-(--ui-text-tertiary)', children: `Could not read: ${profile.note}` })]
    })
  }
  if (!findings.length) {
    return jsxs('div', {
      className: 'flex flex-col gap-1 rounded border border-(--ui-stroke-secondary) p-2',
      children: [
        header,
        jsx('div', { className: 'text-xs text-(--ui-text-secondary)', children: 'No findings' }),
        main ? jsx(RouteRow, { route: main }) : null
      ]
    })
  }
  return jsxs('div', {
    className: 'flex flex-col gap-2 rounded border border-(--ui-stroke-secondary) p-2',
    children: [
      header,
      ...findings.map(f => jsx(FindingRow, { finding: f }, f.code)),
      main ? jsx(RouteRow, { route: main }) : null,
      ...others.map((r, i) => jsx(RouteRow, { route: r }, `${r.role}-${i}`)),
      profile.receipts ? jsx('div', { className: 'text-[0.7rem] text-(--ui-text-tertiary)', children: `Receipts: ${profile.receipts.text}` }) : null
    ]
  })
}

function TuneupPane({ ctx }) {
  const query = useQuery({
    queryKey: [ctx.source, 'report'],
    queryFn: () => ctx.rest('/report'),
    refetchInterval: 60000
  })
  const refresh = jsx(Button, { size: 'sm', variant: 'outline', onClick: () => query.refetch(), children: 'Refresh' })
  if (query.isPending) {
    return jsxs('div', { className: 'flex flex-col gap-2 p-3', children: [jsx(Skeleton, { className: 'h-16' }), jsx(Skeleton, { className: 'h-16' })] })
  }
  if (query.isError && !query.data) {
    return jsx('div', {
      className: 'p-3',
      children: jsx(ErrorState, {
        title: 'tuneup could not load the report',
        description: 'The gateway did not answer. Check that the hermes-tuneup plugin is enabled for this profile.',
        children: jsx(Button, { size: 'sm', onClick: () => query.refetch(), children: 'Retry' })
      })
    })
  }
  const data = query.data
  const profiles = sortProfiles(data.profiles || [])
  const stale = query.isError ? ' (refresh failed, showing the last report)' : ''
  return jsx(ScrollArea, {
    className: 'h-full',
    children: jsxs('div', {
      className: 'flex flex-col gap-2 p-3',
      children: [
        jsxs('div', {
          className: 'flex items-center justify-between gap-2',
          children: [
            jsx('span', { className: 'text-xs text-(--ui-text-tertiary)', children: `Updated ${relativeTime(data.generated_at)}${stale}` }),
            refresh
          ]
        }),
        profiles.length
          ? profiles.map(p => jsx(ProfileCard, { profile: p }, p.name))
          : jsx(EmptyState, { title: 'No Hermes profiles found' })
      ]
    })
  })
}

export default {
  id: 'hermes-tuneup',
  name: 'tuneup',
  register(ctx) {
    ctx.register({
      id: 'pane',
      area: 'panes',
      title: 'tuneup',
      data: { placement: 'right', width: '340px' },
      render: () => jsx(TuneupPane, { ctx })
    })
  }
}
