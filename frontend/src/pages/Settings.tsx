import { useState, useEffect } from 'react';
import { Card, Button, Input, Alert, Tag, Descriptions, Space, InputNumber, message, Divider, Row, Col, Statistic, Typography } from 'antd';
import { ReloadOutlined, ThunderboltOutlined, ImportOutlined, PlayCircleOutlined } from '@ant-design/icons';
import { sessionStatus, sessionImport, guardStatus, guardReset, schedulerStatus, schedulerRun, schedulerSetKeywords } from '../api';

const { TextArea } = Input;
const { Text } = Typography;

export default function Settings() {
  const [session, setSession] = useState<Record<string, unknown> | null>(null);
  const [guard, setGuard] = useState<Record<string, unknown> | null>(null);
  const [scheduler, setScheduler] = useState<Record<string, unknown> | null>(null);
  const [cookieText, setCookieText] = useState('');
  const [keywords, setKeywords] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);

  const loadAll = async () => {
    setLoading(true);
    try {
      const [s, g, sc] = await Promise.all([sessionStatus(), guardStatus(), schedulerStatus()]);
      setSession(s);
      setGuard(g);
      setScheduler(sc);
      setKeywords((sc.keywords as string[]) || []);
    } finally { setLoading(false); }
  };

  useEffect(() => { loadAll(); }, []);

  const handleImport = async () => {
    if (!cookieText.trim()) {
      message.warning('请先粘贴 cookie 内容');
      return;
    }
    try {
      // 直接把原文发给后端，后端兼容 JSON 数组 / JSON 对象 / Cookie 头字符串
      const data = await sessionImport(cookieText);
      if (data.valid) {
        message.success(`登录态导入成功，共 ${data.total_keys} 个 cookie 字段`);
      } else {
        const missing = (data.missing_keys as string[]) || [];
        message.warning(`已保存，但缺少必需字段：${missing.join(' / ')}`);
      }
      loadAll();
    } catch (e) {
      const detail = (e as { response?: { data?: { detail?: string } } }).response?.data?.detail;
      message.error(detail ? `导入失败：${detail}` : '导入失败，请检查粘贴内容');
    }
  };

  const handleGuardReset = async () => {
    await guardReset();
    message.success('熔断器已重置');
    loadAll();
  };

  const handleSchedulerRun = async () => {
    message.loading('采集任务已触发...');
    try {
      const data = await schedulerRun();
      if (data.skipped) {
        message.warning(`采集跳过：${data.reason}`);
      } else {
        message.success('采集任务完成');
      }
      loadAll();
    } catch {
      message.error('采集任务失败');
    }
  };

  const handleSaveKeywords = async () => {
    await schedulerSetKeywords(keywords);
    message.success('关键词已保存');
    loadAll();
  };

  const circuit = guard?.circuit as Record<string, unknown> || {};

  return (
    <Space direction="vertical" style={{ width: '100%' }} size="large">
      {/* 登录态管理 */}
      <Card title="登录态管理" size="small" extra={<Button icon={<ReloadOutlined />} onClick={loadAll} loading={loading}>刷新</Button>}>
        {session && (
          <Descriptions column={2} size="small">
            <Descriptions.Item label="状态">
              <Tag color={session.valid ? 'green' : 'red'}>{session.valid ? '有效' : '无效'}</Tag>
            </Descriptions.Item>
            <Descriptions.Item label="unb">{session.unb as string || '-'}</Descriptions.Item>
            <Descriptions.Item label="tracknick">{session.tracknick as string || '-'}</Descriptions.Item>
            <Descriptions.Item label="cookie字段数">{session.total_keys as number || 0}</Descriptions.Item>
          </Descriptions>
        )}
        <Divider />
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 8 }}
          message="如何导出 cookie（任选一种）"
          description={
            <ol style={{ margin: 0, paddingLeft: 16 }}>
              <li>
                方法一（最快）：浏览器登录 https://www.goofish.com 后按 F12，切到
                Console 标签，输入 <Text code>copy(document.cookie)</Text> 回车，
                剪贴板即为 cookie 字符串，直接粘贴到下方输入框。
              </li>
              <li>
                方法二：F12 → Application → Storage → Cookies →
                https://www.goofish.com，用 EditThisCookie 等扩展导出 JSON 数组后粘贴。
              </li>
              <li>导入后状态显示「有效」即成功（需包含 unb 和 _m_h5_tk 字段）。</li>
            </ol>
          }
        />
        <Text type="secondary">
          {'支持三种格式：JSON 数组 [{"name":"unb","value":"..."}...] / JSON 对象 {"unb":"..."} / Cookie 头字符串 "unb=...; _m_h5_tk=..."'}
        </Text>
        <TextArea
          value={cookieText}
          onChange={(e) => setCookieText(e.target.value)}
          placeholder='[{"name":"unb","value":"xxx"},{"name":"_m_h5_tk","value":"xxx"},...]'
          rows={6}
          style={{ marginTop: 8 }}
        />
        <Button icon={<ImportOutlined />} onClick={handleImport} style={{ marginTop: 8 }}>导入</Button>
      </Card>

      {/* 风控状态 */}
      <Card title="风控护栏" size="small">
        <Row gutter={16}>
          <Col span={8}>
            <Card size="small">
              <Statistic
                title="熔断状态"
                value={circuit.tripped ? '已熔断' : '正常'}
                valueStyle={{ color: circuit.tripped ? '#cf1322' : '#3f8600' }}
              />
            </Card>
          </Col>
          <Col span={8}>
            <Card size="small"><Statistic title="剩余熔断秒数" value={circuit.remaining_seconds as number || 0} /></Card>
          </Col>
          <Col span={8}>
            <Card size="small">
              <Space direction="vertical">
                <Button icon={<ThunderboltOutlined />} onClick={handleGuardReset}>重置熔断器</Button>
              </Space>
            </Card>
          </Col>
        </Row>
      </Card>

      {/* 定时采集 */}
      <Card title="定时采集" size="small">
        {scheduler && (
          <Descriptions column={2} size="small" style={{ marginBottom: 16 }}>
            <Descriptions.Item label="运行状态">
              <Tag color={scheduler.running ? 'green' : 'default'}>{scheduler.running ? '运行中' : '已停止'}</Tag>
            </Descriptions.Item>
            <Descriptions.Item label="任务数">{(scheduler.jobs as unknown[] || []).length}</Descriptions.Item>
          </Descriptions>
        )}
        <Text type="secondary">采集关键词（每行一个）：</Text>
        <TextArea
          value={keywords.join('\n')}
          onChange={(e) => setKeywords(e.target.value.split('\n').filter((s) => s.trim()))}
          rows={5}
          style={{ marginTop: 8 }}
          placeholder={'考研资料\nPython教程\n英语学习资料'}
        />
        <Space style={{ marginTop: 8 }}>
          <Button onClick={handleSaveKeywords}>保存关键词</Button>
          <Button type="primary" icon={<PlayCircleOutlined />} onClick={handleSchedulerRun}>手动触发采集</Button>
        </Space>
      </Card>
    </Space>
  );
}

