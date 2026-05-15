import { useState, useEffect } from 'react'
import { fetchModels } from './api'
import ModelList from './components/ModelList'
import ModelCard from './components/ModelCard'
import VerifyScreen from './components/VerifyScreen'

export default function App() {
  const [screen, setScreen] = useState('loading')
  const [models, setModels] = useState([])
  const [scout, setScout] = useState(null)
  const [selectedModel, setSelectedModel] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    window.Telegram?.WebApp?.ready()
    load()
  }, [])

  async function load() {
    setScreen('loading')
    try {
      const data = await fetchModels()
      if (data.status === 'unverified') {
        setScreen('verify')
        return
      }
      setScout(data.scout)
      setModels(data.models || [])
      setScreen('list')
    } catch (e) {
      if (e.status === 401) {
        setScreen('denied')
      } else {
        setError(e.message)
        setScreen('error')
      }
    }
  }

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
    return <div className="center"><p>Access denied</p></div>
  }

  if (screen === 'error') {
    return <div className="center"><p>Error: {error}</p></div>
  }

  if (screen === 'verify') {
    return <VerifyScreen onVerified={load} />
  }

  if (screen === 'card') {
    return <ModelCard name={selectedModel} onBack={backToList} />
  }

  return <ModelList models={models} scout={scout} onSelect={openCard} />
}
