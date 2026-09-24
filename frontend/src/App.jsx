import { useState, useEffect } from 'react'
import { fetchModels } from './api'
import ModelList from './components/ModelList'
import ModelCard from './components/ModelCard'
import NoAccessScreen from './components/NoAccessScreen'

export default function App() {
  const [screen, setScreen] = useState('loading')
  const [models, setModels] = useState([])
  const [scout, setScout] = useState(null)
  const [selectedModel, setSelectedModel] = useState(null)
  const [error, setError] = useState(null)
  const [noAccess, setNoAccess] = useState(null)

  useEffect(() => {
    async function load() {
      setScreen('loading')
      try {
        const data = await fetchModels()
        if (data.status === 'no_access') {
          setNoAccess({ reason: data.reason, username: data.username })
          setScreen('denied')
          return
        }
        setScout(data.scout)
        setModels(data.models || [])
        setScreen('list')
      } catch (e) {
        if (e.status === 401) {
          setNoAccess({ reason: 'outside_telegram' })
          setScreen('denied')
        } else {
          setError(e.message)
          setScreen('error')
        }
      }
    }

    window.Telegram?.WebApp?.ready()
    load()
  }, [])

  function openCard(name) {
    setSelectedModel(name)
    setScreen('card')
  }

  function backToList() {
    setSelectedModel(null)
    setScreen('list')
  }

  if (screen === 'loading') {
    return <div className="center"><div className="spinner" /></div>
  }

  if (screen === 'denied') {
    return <NoAccessScreen reason={noAccess?.reason} username={noAccess?.username} />
  }

  if (screen === 'error') {
    return <div className="center"><p>Error: {error}</p></div>
  }

  if (screen === 'card') {
    return <ModelCard name={selectedModel} onBack={backToList} />
  }

  return <ModelList models={models} scout={scout} onSelect={openCard} />
}
