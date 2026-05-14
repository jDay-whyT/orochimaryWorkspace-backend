import { useState } from 'react'
import { verifyHandle } from '../api'

export default function VerifyScreen({ onVerified }) {
  const [handle, setHandle] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  async function submit(e) {
    e.preventDefault()
    if (!handle.trim()) return
    setLoading(true)
    setError(null)
    try {
      await verifyHandle(handle.trim())
      onVerified()
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="center">
      <form className="verify-form" onSubmit={submit}>
        <h2>Enter your handle</h2>
        <p>Your Telegram username is hidden. Enter your scout handle to continue.</p>
        <input
          className="verify-input"
          type="text"
          placeholder="@username"
          value={handle}
          onChange={(e) => setHandle(e.target.value)}
          autoComplete="off"
          autoCapitalize="none"
        />
        <button className="verify-btn" type="submit" disabled={loading || !handle.trim()}>
          {loading ? 'Checking...' : 'Continue'}
        </button>
        {error && <p className="verify-error">{error}</p>}
      </form>
    </div>
  )
}
