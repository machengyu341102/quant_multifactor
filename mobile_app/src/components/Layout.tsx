import { Outlet } from 'react-router-dom'
import { TabBar } from 'antd-mobile'
import { useNavigate, useLocation } from 'react-router-dom'
import {
  AppOutline,
  MessageOutline,
  UnorderedListOutline,
  UserOutline,
} from 'antd-mobile-icons'
import './Layout.css'

const tabs = [
  {
    key: '/',
    title: '首页',
    icon: <AppOutline />,
  },
  {
    key: '/signals',
    title: '信号',
    icon: <MessageOutline />,
  },
  {
    key: '/positions',
    title: '持仓',
    icon: <UnorderedListOutline />,
  },
  {
    key: '/learning',
    title: '学习',
    icon: <UserOutline />,
  },
]

export default function Layout() {
  const navigate = useNavigate()
  const location = useLocation()

  const setRouteActive = (value: string) => {
    navigate(value)
  }

  return (
    <div className="app-layout">
      <div className="app-content">
        <Outlet />
      </div>
      <div className="app-tabbar">
        <TabBar activeKey={location.pathname} onChange={setRouteActive}>
          {tabs.map(item => (
            <TabBar.Item key={item.key} icon={item.icon} title={item.title} />
          ))}
        </TabBar>
      </div>
    </div>
  )
}
