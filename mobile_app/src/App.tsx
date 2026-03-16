import { Routes, Route } from 'react-router-dom'
import Layout from './components/Layout'
import Dashboard from './pages/Dashboard'
import Signals from './pages/Signals'
import SignalDetail from './pages/SignalDetail'
import Positions from './pages/Positions'
import PositionDetail from './pages/PositionDetail'
import Learning from './pages/Learning'
import Profile from './pages/Profile'

function App() {
  return (
    <Routes>
      <Route path="/" element={<Layout />}>
        <Route index element={<Dashboard />} />
        <Route path="signals" element={<Signals />} />
        <Route path="signals/:id" element={<SignalDetail />} />
        <Route path="positions" element={<Positions />} />
        <Route path="positions/:code" element={<PositionDetail />} />
        <Route path="learning" element={<Learning />} />
        <Route path="profile" element={<Profile />} />
      </Route>
    </Routes>
  )
}

export default App
