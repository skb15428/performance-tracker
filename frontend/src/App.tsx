import { useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { Navigate, Route, Routes } from 'react-router-dom'
import Layout from './components/Layout'
import { getToken, setToken } from './lib/api'
import Dashboard from './pages/Dashboard'
import DailyLog from './pages/DailyLog'
import GoalDetail from './pages/GoalDetail'
import Goals from './pages/Goals'
import Login from './pages/Login'
import SettingsPage from './pages/Settings'
import Trends from './pages/Trends'
import Weekly from './pages/Weekly'

export default function App() {
  const [authed, setAuthed] = useState(() => !!getToken())
  const qc = useQueryClient()

  useEffect(() => {
    const onLogout = () => {
      setAuthed(false)
      qc.clear()
    }
    window.addEventListener('goalcoach:logout', onLogout)
    return () => window.removeEventListener('goalcoach:logout', onLogout)
  }, [qc])

  if (!authed) return <Login onDone={() => setAuthed(true)} />

  const logout = () => {
    setToken(null)
    window.dispatchEvent(new Event('goalcoach:logout'))
  }

  return (
    <Routes>
      <Route element={<Layout onLogout={logout} />}>
        <Route index element={<Dashboard />} />
        <Route path="log" element={<DailyLog />} />
        <Route path="log/:day" element={<DailyLog />} />
        <Route path="goals" element={<Goals />} />
        <Route path="goals/:id" element={<GoalDetail />} />
        <Route path="trends" element={<Trends />} />
        <Route path="weekly" element={<Weekly />} />
        <Route path="settings" element={<SettingsPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  )
}
