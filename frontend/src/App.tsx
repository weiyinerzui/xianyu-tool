import { useState } from 'react';
import { ConfigProvider, Layout, Menu, theme } from 'antd';
import {
  SearchOutlined,
  StopOutlined,
  MedicineBoxOutlined,
  EditOutlined,
  DashboardOutlined,
  EyeOutlined,
  RobotOutlined,
  SettingOutlined,
} from '@ant-design/icons';
import zhCN from 'antd/locale/zh_CN';
import BannedChecker from './pages/BannedChecker';
import Diagnosis from './pages/Diagnosis';
import TitleOptimizer from './pages/TitleOptimizer';
import ProductResearch from './pages/ProductResearch';
import Dashboard from './pages/Dashboard';
import Competitors from './pages/Competitors';
import LLMAdvisor from './pages/LLMAdvisor';
import Settings from './pages/Settings';

const { Header, Sider, Content } = Layout;

const menuItems = [
  { key: 'research', icon: <SearchOutlined />, label: '选品中心' },
  { key: 'banned', icon: <StopOutlined />, label: '违禁词检测' },
  { key: 'diagnosis', icon: <MedicineBoxOutlined />, label: '曝光诊断' },
  { key: 'title', icon: <EditOutlined />, label: '标题优化' },
  { key: 'dashboard', icon: <DashboardOutlined />, label: '数据看板' },
  { key: 'competitors', icon: <EyeOutlined />, label: '竞品监控' },
  { key: 'llm', icon: <RobotOutlined />, label: 'AI 助手' },
  { key: 'settings', icon: <SettingOutlined />, label: '系统设置' },
];

function App() {
  const [current, setCurrent] = useState('research');
  const { token: { colorBgContainer, borderRadiusLG } } = theme.useToken();

  const renderPage = () => {
    switch (current) {
      case 'research': return <ProductResearch />;
      case 'banned': return <BannedChecker />;
      case 'diagnosis': return <Diagnosis />;
      case 'title': return <TitleOptimizer />;
      case 'dashboard': return <Dashboard />;
      case 'competitors': return <Competitors />;
      case 'llm': return <LLMAdvisor />;
      case 'settings': return <Settings />;
      default: return <ProductResearch />;
    }
  };

  return (
    <ConfigProvider locale={zhCN}>
      <Layout style={{ minHeight: '100vh' }}>
        <Sider breakpoint="lg" collapsedWidth="0" style={{ background: '#001529' }}>
          <div style={{ height: 48, margin: 16, color: '#fff', fontSize: 18, fontWeight: 700, textAlign: 'center', lineHeight: '48px' }}>
            闲鱼运营工具
          </div>
          <Menu
            theme="dark"
            mode="inline"
            selectedKeys={[current]}
            items={menuItems}
            onClick={(e) => setCurrent(e.key)}
          />
        </Sider>
        <Layout>
          <Header style={{ background: colorBgContainer, padding: '0 24px', fontSize: 16, fontWeight: 600 }}>
            {menuItems.find((m) => m.key === current)?.label}
          </Header>
          <Content style={{ margin: 24 }}>
            <div style={{ padding: 24, background: colorBgContainer, borderRadius: borderRadiusLG, minHeight: 360 }}>
              {renderPage()}
            </div>
          </Content>
        </Layout>
      </Layout>
    </ConfigProvider>
  );
}

export default App;
