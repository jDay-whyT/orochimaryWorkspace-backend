const TEXT = {
  no_models: {
    title: 'No access yet',
    body: 'No models are assigned to you. Send your username to the admin to get access.',
  },
  no_username: {
    title: 'Username required',
    body: 'Set a username in Telegram settings, then send it to the admin and reopen the app.',
  },
  outside_telegram: {
    title: 'Access denied',
    body: 'Open this app from the Telegram bot.',
  },
}

export default function NoAccessScreen({ reason, username }) {
  const text = TEXT[reason] || TEXT.no_models
  return (
    <div className="center">
      <div className="no-access">
        <h2>{text.title}</h2>
        <p>{text.body}</p>
        {username && <div className="no-access-handle">{username}</div>}
      </div>
    </div>
  )
}
