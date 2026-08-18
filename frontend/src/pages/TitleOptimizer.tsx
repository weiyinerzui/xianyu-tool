import { useState } from 'react';
import { Input, Button, Card, Progress, Tag, List, Space, Typography, Row, Col, Statistic, Divider } from 'antd';
import { EditOutlined } from '@ant-design/icons';
import { titleScore, titleGenerate } from '../api';

const { Text } = Typography;

export default function TitleOptimizer() {
  const [title, setTitle] = useState('');
  const [keyword, setKeyword] = useState('');
  const [score, setScore] = useState<Record<string, unknown> | null>(null);
  const [candidates, setCandidates] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);

  const handleScore = async () => {
    if (!title.trim()) return;
    setLoading(true);
    try {
      const data = await titleScore(title, keyword);
      setScore(data);
    } finally { setLoading(false); }
  };

  const handleGenerate = async () => {
    if (!keyword.trim()) return;
    setLoading(true);
    try {
      const data = await titleGenerate({ core_keyword: keyword });
      setCandidates(data.candidates || []);
    } finally { setLoading(false); }
  };

  const bannedHits = (score?.banned_hits as Record<string, unknown>[]) || [];

  return (
    <Space direction="vertical" style={{ width: '100%' }} size="large">
      <Card title="标题评分" size="small">
        <Space style={{ width: '100%' }}>
          <Input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="输入商品标题" style={{ flex: 1 }} />
          <Input value={keyword} onChange={(e) => setKeyword(e.target.value)} placeholder="核心词（可选）" style={{ width: 200 }} />
          <Button type="primary" icon={<EditOutlined />} onClick={handleScore} loading={loading}>评分</Button>
        </Space>
      </Card>

      {score && (
        <>
          <Row gutter={16}>
            <Col span={6}><Card size="small"><Statistic title="总分" value={score.total_score as number} suffix="/100" /></Card></Col>
            <Col span={6}><Card size="small"><Statistic title="长度分" value={score.length_score as number} /></Card></Col>
            <Col span={6}><Card size="small"><Statistic title="结构分" value={score.structure_score as number} /></Card></Col>
            <Col span={6}><Card size="small"><Statistic title="关键词位置分" value={score.keyword_position_score as number} /></Card></Col>
          </Row>

          <Card title="5段式覆盖" size="small">
            <Space wrap>
              {Object.entries((score.segments as Record<string, boolean>) || {}).map(([k, v]) => (
                <Tag key={k} color={v ? 'green' : 'default'}>{k}: {v ? '✓' : '✗'}</Tag>
              ))}
            </Space>
          </Card>

          {bannedHits.length > 0 && (
            <Card title="违禁词命中" size="small">
              {bannedHits.map((h, i) => (
                <Tag key={i} color={h.severity === 'block' ? 'red' : 'orange'}>
                  {h.word as string} ({h.category as string}) → {h.replacement as string || '删除'}
                </Tag>
              ))}
            </Card>
          )}

          {score.issues && (score.issues as string[]).length > 0 && (
            <Card title="问题" size="small"><ul>{(score.issues as string[]).map((s, i) => <li key={i}>{s}</li>)}</ul></Card>
          )}

          {score.suggestions && (score.suggestions as string[]).length > 0 && (
            <Card title="优化建议" size="small"><ul>{(score.suggestions as string[]).map((s, i) => <li key={i}>{s}</li>)}</ul></Card>
          )}
        </>
      )}

      <Divider />

      <Card title="标题生成（5段式公式）" size="small">
        <Text type="secondary">输入核心词，自动生成合规候选标题</Text>
        <div style={{ marginTop: 12 }}>
          <Button onClick={handleGenerate} loading={loading} disabled={!keyword}>生成候选</Button>
        </div>
        {candidates.length > 0 && (
          <List
            size="small"
            style={{ marginTop: 12 }}
            dataSource={candidates}
            renderItem={(c, i) => (
              <List.Item>
                <Space>
                  <Tag>{i + 1}</Tag>
                  <Text>{c}</Text>
                  <Text type="secondary">({c.length}字)</Text>
                </Space>
              </List.Item>
            )}
          />
        )}
      </Card>
    </Space>
  );
}
