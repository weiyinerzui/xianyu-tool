import { useState } from 'react';
import { Input, Button, Card, Table, Tag, Space, Select, Row, Col, Statistic, message } from 'antd';
import { SearchOutlined, ThunderboltOutlined } from '@ant-design/icons';
import { crawlSearch, productsSearch, productsStats } from '../api';

export default function ProductResearch() {
  const [keyword, setKeyword] = useState('');
  const [category, setCategory] = useState<string>();
  const [items, setItems] = useState<Record<string, unknown>[]>([]);
  const [total, setTotal] = useState(0);
  const [stats, setStats] = useState<Record<string, unknown> | null>(null);
  const [loading, setLoading] = useState(false);
  const [crawling, setCrawling] = useState(false);
  const [sort, setSort] = useState('hotness');
  const [page, setPage] = useState(1);

  const handleSearch = async () => {
    setLoading(true);
    try {
      const data = await productsSearch({ keyword, category, sort, page, page_size: 20 });
      setItems(data.items || []);
      setTotal(data.total || 0);
      const s = await productsStats(keyword);
      setStats(s);
    } finally { setLoading(false); }
  };

  const handleCrawl = async () => {
    if (!keyword.trim()) { message.warning('请输入关键词'); return; }
    setCrawling(true);
    try {
      const data = await crawlSearch(keyword, category);
      message.success(`采集完成：${data.total} 条（来源：${data.source}）`);
      handleSearch();
    } catch {
      message.error('采集失败，可能需要登录态或触发风控');
    } finally { setCrawling(false); }
  };

  return (
    <Space direction="vertical" style={{ width: '100%' }} size="large">
      <Card size="small">
        <Space style={{ width: '100%' }}>
          <Input value={keyword} onChange={(e) => setKeyword(e.target.value)} placeholder="搜索关键词" style={{ width: 250 }} onPressEnter={handleSearch} />
          <Select value={category} onChange={setCategory} placeholder="类目" style={{ width: 150 }} allowClear
            options={[{ value: '学习资料', label: '学习资料' }, { value: '软件教程', label: '软件教程' }, { value: '免费软件', label: '免费软件' }]} />
          <Select value={sort} onChange={setSort} style={{ width: 120 }}
            options={[{ value: 'hotness', label: '热度' }, { value: 'want_count', label: '想要数' }, { value: 'price_asc', label: '价格↑' }, { value: 'price_desc', label: '价格↓' }, { value: 'newest', label: '最新' }]} />
          <Button type="primary" icon={<SearchOutlined />} onClick={handleSearch} loading={loading}>查询</Button>
          <Button icon={<ThunderboltOutlined />} onClick={handleCrawl} loading={crawling}>采集</Button>
        </Space>
      </Card>

      {stats && (stats.total as number) > 0 && (
        <Row gutter={16}>
          <Col span={4}><Card size="small"><Statistic title="商品数" value={stats.total as number} /></Card></Col>
          <Col span={4}><Card size="small"><Statistic title="均价" value={((stats.price_bands as Record<string, number>)?.avg) || 0} prefix="¥" /></Card></Col>
          <Col span={4}><Card size="small"><Statistic title="中位价" value={((stats.price_bands as Record<string, number>)?.median) || 0} prefix="¥" /></Card></Col>
          <Col span={4}><Card size="small"><Statistic title="平均想要数" value={stats.avg_want_count as number} /></Card></Col>
          <Col span={4}><Card size="small"><Statistic title="最高想要数" value={stats.max_want_count as number} /></Card></Col>
          <Col span={4}><Card size="small"><Statistic title="竞争度" value={stats.competition_score as number} suffix="/100" /></Card></Col>
        </Row>
      )}

      <Table
        size="small"
        dataSource={items}
        rowKey="xianyu_id"
        loading={loading}
        pagination={{ current: page, total, pageSize: 20, onChange: setPage }}
        columns={[
          { title: '标题', dataIndex: 'title', ellipsis: true, width: 250 },
          { title: '价格', dataIndex: 'price', render: (v: number) => `¥${v}`, width: 80 },
          { title: '想要数', dataIndex: 'want_count', width: 80, sorter: (a: Record<string, number>, b: Record<string, number>) => a.want_count - b.want_count },
          { title: '热度', dataIndex: 'hotness', width: 80, render: (v: number) => v?.toFixed(1) },
          { title: '卖家', dataIndex: 'seller_name', width: 100, ellipsis: true },
          { title: '地区', dataIndex: 'area', width: 80 },
          { title: '发布', dataIndex: 'days_ago', width: 70, render: (v: number) => v != null ? `${v}天前` : '-' },
          {
            title: '标签', dataIndex: 'tags', width: 120,
            render: (v: unknown) => {
              const tags = (v as Record<string, string[]>)?.tags || [];
              return tags.map((t, i) => <Tag key={i}>{t}</Tag>);
            },
          },
        ]}
      />
    </Space>
  );
}
