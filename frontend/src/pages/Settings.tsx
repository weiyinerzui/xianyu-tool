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
    try {
      const cookies = JSON.parse(cookieText);
      const data = await sessionImport(cookies);
      if (data.valid) {
        message.success('登录态导入成功');
      } else {
        message.warning('已保存，但缺少必需字段（unb / _m_h5_tk）');
      }
      loadAll();
    } catch {
      message.error('JSON 格式错误');
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
        <Text type="secondary">粘贴从浏览器 DevTools 导出的 cookie JSON：</Text>
        <TextArea
          value={cookieText}
          onChange={(e) => setCookieText(e.target.value)}
          placeholder='{"unb":"xxx","_m_h5_tk":"xxx","cookie2":"xxx",...}'
          rows={4}
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

