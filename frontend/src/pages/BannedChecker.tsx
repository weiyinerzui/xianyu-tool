import { useState } from 'react';
import { Input, Button, Alert, Tag, Table, Card, Row, Col, Statistic, Space, Typography } from 'antd';
import { ScanOutlined } from '@ant-design/icons';
import { bannedCheck } from '../api';

const { TextArea } = Input;
const { Text } = Typography;

const severityColor: Record<string, string> = {
  block: 'red',
  warn: 'orange',
  info: 'blue',
};

const riskColor: Record<string, string> = {
  safe: 'green',
  warn: 'orange',
  danger: 'red',
};

export default function BannedChecker() {
  const [text, setText] = useState('');
  const [result, setResult] = useState<Record<string, unknown> | null>(null);
  const [loading, setLoading] = useState(false);

  const handleCheck = async () => {
    if (!text.trim()) return;
    setLoading(true);
    try {
      const data = await bannedCheck(text);
      setResult(data);
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  };

  const hits = (result?.hits as Record<string, unknown>[]) || [];

  return (
    <Space direction="vertical" style={{ width: '100%' }} size="large">
      <Card title="违禁词检测" size="small">
        <TextArea
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="输入商品标题、描述或消息内容进行违禁词检测..."
          rows={4}
          showCount
        />
        <Button
          type="primary"
          icon={<ScanOutlined />}
          onClick={handleCheck}
          loading={loading}
          style={{ marginTop: 12 }}
        >
          检测
        </Button>
      </Card>

      {result && (
        <>
          <Row gutter={16}>
            <Col span={6}>
              <Card size="small">
                <Statistic
                  title="风险等级"
                  value={result.risk_level as string}
                  valueStyle={{ color: riskColor[result.risk_level as string] }}
                />
              </Card>
            </Col>
            <Col span={6}>
              <Card size="small"><Statistic title="命中数" value={result.hit_count as number} /></Card>
            </Col>
            <Col span={6}>
              <Card size="small"><Statistic title="Block" value={result.block_count as number} valueStyle={{ color: '#cf1322' }} /></Card>
            </Col>
            <Col span={6}>
              <Card size="small"><Statistic title="Warn" value={result.warn_count as number} valueStyle={{ color: '#fa8c16' }} /></Card>
            </Col>
          </Row>

          {result.risk_level === 'danger' && (
            <Alert
              type="error"
              message="检测到高危违禁词，必须修改后才能发布"
              showIcon
            />
          )}

          {hits.length > 0 && (
            <Table
              size="small"
              dataSource={hits}
              rowKey={(_, i) => String(i)}
              pagination={false}
              columns={[
                { title: '违禁词', dataIndex: 'word', render: (v: string) => <Text strong>{v}</Text> },
                { title: '分类', dataIndex: 'category_label' },
                {
                  title: '级别', dataIndex: 'severity',
                  render: (v: string) => <Tag color={severityColor[v]}>{v.toUpperCase()}</Tag>,
                },
                { title: '替换建议', dataIndex: 'replacement', render: (v: string) => v || '-' },
                { title: '说明', dataIndex: 'note' },
              ]}
            />
          )}

          {result.summary && (result.summary as Record<string, unknown>).suggestions && (
            <Card title="优化建议" size="small">
              {(result.summary as Record<string, unknown>).suggestions as string[]}
              <ul>
                {((result.summary as Record<string, unknown>).suggestions as string[]).map((s, i) => (
                  <li key={i}>{s}</li>
                ))}
              </ul>
            </Card>
          )}
        </>
      )}
    </Space>
  );
}
