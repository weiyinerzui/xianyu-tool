import { useState, useEffect } from 'react';
import { Card, Row, Col, Statistic, Table, Tag, Space, Spin } from 'antd';
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, PieChart, Pie, Cell, LineChart, Line, Legend } from 'recharts';
import { dashboardOverview, dashboardPriceDist, dashboardTopProducts, dashboardKeywordRanking, dashboardCategoryDist, dashboardPublishTrend } from '../api';

const PIE_COLORS = ['#8884d8', '#83a6ed', '#8dd1e1', '#82ca9d', '#a2d46b', '#ffc658', '#ff8042'];

export default function Dashboard() {
  const [overview, setOverview] = useState<Record<string, unknown> | null>(null);
  const [priceDist, setPriceDist] = useState<Record<string, unknown>[]>([]);
  const [topProducts, setTopProducts] = useState<Record<string, unknown>[]>([]);
  const [keywords, setKeywords] = useState<Record<string, unknown>[]>([]);
  const [categories, setCategories] = useState<Record<string, unknown>[]>([]);
  const [trend, setTrend] = useState<Record<string, unknown>[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => {
      setLoading(true);
      try {
        const [ov, pd, tp, kw, cat, tr] = await Promise.all([
          dashboardOverview(), dashboardPriceDist(), dashboardTopProducts('hot_score', 10),
          dashboardKeywordRanking(10), dashboardCategoryDist(), dashboardPublishTrend(),
        ]);
        setOverview(ov);
        setPriceDist((pd.bins as Record<string, unknown>[]) || []);
        setTopProducts((tp.items as Record<string, unknown>[]) || []);
        setKeywords((kw.items as Record<string, unknown>[]) || []);
        setCategories((cat.items as Record<string, unknown>[]) || []);
        setTrend((tr.trend as Record<string, unknown>[]) || []);
      } finally { setLoading(false); }
    })();
  }, []);

  if (loading) return <Spin size="large" />;

  const price = overview?.price as Record<string, number> || {};
  const want = overview?.want_count as Record<string, number> || {};
  const hot = overview?.hot_score as Record<string, number> || {};

  return (
    <Space direction="vertical" style={{ width: '100%' }} size="large">
      <Row gutter={16}>
        <Col span={4}><Card size="small"><Statistic title="商品总数" value={overview?.total as number || 0} /></Card></Col>
        <Col span={4}><Card size="small"><Statistic title="均价" value={price.avg || 0} prefix="¥" /></Card></Col>
        <Col span={4}><Card size="small"><Statistic title="中位价" value={price.median || 0} prefix="¥" /></Card></Col>
        <Col span={4}><Card size="small"><Statistic title="平均想要数" value={want.avg || 0} /></Card></Col>
        <Col span={4}><Card size="small"><Statistic title="卖家数" value={overview?.sellers as number || 0} /></Card></Col>
        <Col span={4}><Card size="small"><Statistic title="类目数" value={overview?.categories as number || 0} /></Card></Col>
      </Row>

      <Row gutter={16}>
        <Col span={12}>
          <Card title="价格分布" size="small">
            <ResponsiveContainer width="100%" height={300}>
              <BarChart data={priceDist}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="label" angle={-30} textAnchor="end" height={60} interval={0} />
                <YAxis />
                <Tooltip />
                <Bar dataKey="count" fill="#8884d8" />
              </BarChart>
            </ResponsiveContainer>
          </Card>
        </Col>
        <Col span={12}>
          <Card title="类目分布" size="small">
            <ResponsiveContainer width="100%" height={300}>
              <PieChart>
                <Pie data={categories} dataKey="count" nameKey="category" cx="50%" cy="50%" outerRadius={100} label>
                  {categories.map((_, i) => <Cell key={i} fill={PIE_COLORS[i % PIE_COLORS.length]} />)}
                </Pie>
                <Tooltip />
                <Legend />
              </PieChart>
            </ResponsiveContainer>
          </Card>
        </Col>
      </Row>

      {trend.length > 0 && (
        <Card title="发布时间趋势（最近30天）" size="small">
          <ResponsiveContainer width="100%" height={250}>
            <LineChart data={trend}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="date" />
              <YAxis />
              <Tooltip />
              <Line type="monotone" dataKey="count" stroke="#82ca9d" />
            </LineChart>
          </ResponsiveContainer>
        </Card>
      )}

      <Row gutter={16}>
        <Col span={12}>
          <Card title="热门商品 Top 10" size="small">
            <Table size="small" dataSource={topProducts} rowKey="xianyu_id" pagination={false}
              columns={[
                { title: '标题', dataIndex: 'title', ellipsis: true },
                { title: '价格', dataIndex: 'price', render: (v: number) => `¥${v}`, width: 80 },
                { title: '想要', dataIndex: 'want_count', width: 60 },
                { title: '热度', dataIndex: 'hot_score', width: 70, render: (v: number) => v?.toFixed(1) },
              ]}
            />
          </Card>
        </Col>
        <Col span={12}>
          <Card title="关键词排行" size="small">
            <Table size="small" dataSource={keywords} rowKey="keyword" pagination={false}
              columns={[
                { title: '关键词', dataIndex: 'keyword' },
                { title: '采集量', dataIndex: 'count', width: 100, render: (v: number) => <Tag color="blue">{v}</Tag> },
              ]}
            />
          </Card>
        </Col>
      </Row>
    </Space>
  );
}
