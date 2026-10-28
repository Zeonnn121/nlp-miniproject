import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { ActivityIcon } from '../components/icons'
import { useAuth } from '../auth/useAuth'
import { AuthError } from '../auth/types'

function getNextPath() {
  const next = new URLSearchParams(window.location.search).get('next')
  return next?.startsWith('/') && !next.startsWith('//') ? next : '/'
}

export function LoginPage() {
  const { login, isAuthenticated, isLoading } = useAuth()
  const [identifier, setIdentifier] = useState('')
  const [password, setPassword] = useState('')
  const [identifierError, setIdentifierError] = useState('')
  const [passwordError, setPasswordError] = useState('')
  const [submitError, setSubmitError] = useState('')
  const [isSubmitting, setIsSubmitting] = useState(false)

  useEffect(() => {
    if (!isLoading && isAuthenticated) window.location.replace(getNextPath())
  }, [isAuthenticated, isLoading])

  const validate = () => {
    const nextIdentifierError = identifier.trim() ? '' : 'Username or email is required.'
    const nextPasswordError = password ? '' : 'Password is required.'
    setIdentifierError(nextIdentifierError)
    setPasswordError(nextPasswordError)
    return !nextIdentifierError && !nextPasswordError
  }

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setSubmitError('')
    if (!validate()) return

    setIsSubmitting(true)
    try {
      await login({ identifier: identifier.trim(), password })
      window.location.replace(getNextPath())
    } catch (error) {
      if (error instanceof AuthError) {
        setSubmitError(error.message)
      } else {
        setSubmitError('We could not complete sign in. Please try again.')
      }
    } finally {
      setIsSubmitting(false)
    }
  }

  if (isLoading || isAuthenticated) {
    return (
      <main className="grid min-h-screen place-items-center" style={{ background: '#030407' }} aria-live="polite">
        <div className="size-8 animate-spin rounded-full border-2 border-[#1e2a45] border-t-[#1558c9]" aria-hidden="true" />
      </main>
    )
  }

  return (
    <main className="min-h-screen px-4 py-8 sm:px-6 sm:py-12" style={{ background: '#030407' }}>
      <div className="mx-auto flex min-h-[calc(100vh-4rem)] max-w-md items-center justify-center">
        <section className="w-full rounded-3xl border border-[#1e2a45] p-6 shadow-2xl shadow-black/60 sm:p-8" style={{ background: '#0a0d16' }} aria-labelledby="login-title">
          <div className="mb-8 text-center">
            <div className="mx-auto mb-5 grid size-12 place-items-center rounded-2xl shadow-sm" style={{ background: 'linear-gradient(135deg, #1558c9, #0d3fa0)' }}>
              <ActivityIcon className="size-6 text-white" />
            </div>
            <p className="text-xs font-semibold uppercase tracking-[0.16em] text-[#4a5a80]">NetWatch</p>
            <h1 id="login-title" className="mt-2 text-2xl font-semibold tracking-tight text-[#f0f4ff]">Administrator sign in</h1>
            <p className="mt-2 text-sm leading-6 text-[#8b9dc0]">Sign in to access the network monitoring workspace.</p>
          </div>

          {submitError && <div className="mb-5 rounded-xl border border-[#3a1a1a] px-4 py-3 text-sm text-[#f87171]" style={{ background: '#1a0a0a' }} role="alert">{submitError}</div>}

          <form className="space-y-5" onSubmit={handleSubmit} noValidate>
            <div>
              <label htmlFor="identifier" className="block text-sm font-medium text-[#8b9dc0]">Username or email</label>
              <input id="identifier" name="identifier" type="text" autoComplete="username" value={identifier} onChange={(event) => setIdentifier(event.target.value)} aria-invalid={Boolean(identifierError)} aria-describedby={identifierError ? 'identifier-error' : undefined} className="mt-2 block w-full rounded-xl border border-[#1e2a45] px-3.5 py-3 text-sm text-[#f0f4ff] shadow-sm outline-none transition placeholder:text-[#4a5a80] focus:border-[#1558c9] focus:ring-2" style={{ background: '#030407' }} placeholder="Enter your username or email" disabled={isSubmitting} />
              {identifierError && <p id="identifier-error" className="mt-2 text-xs text-[#f87171]">{identifierError}</p>}
            </div>

            <div>
              <label htmlFor="password" className="block text-sm font-medium text-[#8b9dc0]">Password</label>
              <input id="password" name="password" type="password" autoComplete="current-password" value={password} onChange={(event) => setPassword(event.target.value)} aria-invalid={Boolean(passwordError)} aria-describedby={passwordError ? 'password-error' : undefined} className="mt-2 block w-full rounded-xl border border-[#1e2a45] px-3.5 py-3 text-sm text-[#f0f4ff] shadow-sm outline-none transition placeholder:text-[#4a5a80] focus:border-[#1558c9] focus:ring-2" style={{ background: '#030407' }} placeholder="Enter your password" disabled={isSubmitting} />
              {passwordError && <p id="password-error" className="mt-2 text-xs text-[#f87171]">{passwordError}</p>}
            </div>

            <button type="submit" disabled={isSubmitting} className="flex w-full items-center justify-center rounded-xl px-4 py-3 text-sm font-semibold text-white shadow-sm transition disabled:cursor-not-allowed disabled:opacity-60" style={{ background: 'linear-gradient(135deg, #1558c9, #0d3fa0)' }}>
              {isSubmitting ? <><span className="mr-2 size-4 animate-spin rounded-full border-2 border-white/30 border-t-white" aria-hidden="true" />Signing in…</> : 'Sign in'}
            </button>
          </form>

          <p className="mt-6 text-center text-xs leading-5 text-[#4a5a80]">Administrator access only. Authentication is provided by the system backend when connected.</p>
        </section>
      </div>
    </main>
  )
}
