interface LoadingStateProps {
  label?: string
}

export function LoadingState({ label = 'Loading monitoring data…' }: LoadingStateProps) {
  return (
    <div className="rounded-2xl border border-[#1e2a45] px-6 py-12 text-center" style={{ background: '#0a0d16' }} role="status" aria-live="polite">
      <div className="mx-auto mb-4 size-8 animate-spin rounded-full border-2 border-[#1e2a45] border-t-[#1558c9]" aria-hidden="true" />
      <p className="text-sm font-medium text-[#8b9dc0]">{label}</p>
    </div>
  )
}
