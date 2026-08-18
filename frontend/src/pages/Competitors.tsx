import { useState, useEffect } from 'react';
import { Card, Table, Tag, Tabs, Space, InputNumber, Button, Row, Col, Statistic, message } from 'antd';
import { competitorsTopSellers, competitorsNewListings, competitorsPriceChanges } from '../api';

export default function Competitors() {
  const [sellers, setSellers] = useState<Record<string, unknown>[]>([]);
  const [newItems, setNewItems] = useState<Record<string, unknown>[]>([]);
  const [priceChanges, setPriceChanges] = useState<Record<string, unknown> | null>(null);
  const [hours, setHours] = useState(24);
  const [loading, setLoading] = useState(false);

  const loadData = async () => {
    setLoading(true);
    try {
      const [s, n, p] = await Promise.all([
        competitorsTopSellers(20), competitorsNewListings(hours, 50), competitorsPriceChanges(),
      ]);
      setSellers((s.items as Record<string, unknown>[]) || []);
      setNewItems((n.items as Record<string, unknown>[]) || []);
      setPriceChanges(p);
    } finally { setLoading(false); }
  };

  useEffect(() => { loadData(); }, []);

  return (
    <Space direction="vertical" style={{ width: '100%' }} size="large">
      <Tabs
        items={[
          {
            key: 'sellers', label: '头部卖家', children: (
              <Table size="small" dataSource={sellers} rowKey="seller_name" loading={loading} pagination={{ pageSize: 20 }}
                columns={[
                  { title: '卖家', dataIndex: 'seller_name' },
                  { title: '在售数', dataIndex: 'listing_count', width: 100, sorter: (a: Record<string, number>, b: Record<string, number>) => a.listing_count - b.listing_count },
                  { title: '想要总数', dataIndex: 'total_wants', width: 100, sorter: (a: Record<string, number>, b: Record<string, number>) => a.total_wants - b.total_wants },
                  { title: '均价', dataIndex: 'avg_price', width: 100, render: (v: number) => `¥${v}` },
                ]}
              />
            ),
          },
          {
            key: 'new', label: '最近新品', children: (
              <Space direction="vertical" style={{ width: '100%' }}>
                <Space>
                  <span>时间范围（小时）：</span>
                  <InputNumber value={hours} onChange={(v) => setHours(v || 24)} min={1} max={168} />
                  <Button onClick={loadData} loading={loading}>刷新</Button>
                </Space>
                <Table size="small" dataSource={newItems} rowKey="xianyu_id" loading={loading} pagination={{ pageSize: 20 }}
                  columns={[
                    { title: '标题', dataIndex: 'title', ellipsis: true },
                    { title: '价格', dataIndex: 'price', width: 80, render: (v: number) => `¥${v}` },
                    { title: '想要', dataIndex: 'want_count', width: 60 },
                    { title: '卖家', dataIndex: 'seller_name', width: 100, ellipsis: true },
                    { title: '发布时间', dataIndex: 'publish_time', width: 150 },
                  ]}
                />
              </Space>
            ),
          },
          {
            key: 'price', label: '价格变动', children: priceChanges ? (
              <Space direction="vertical" style={{ width: '100%' }}>
                <Row gutter={16}>
                  <Col span={8}><Card size="small"><Statistic title="类目均价" value={priceChanges.avg_price as number} prefix="¥" /></Card></Col>
                  <Col span={8}><Card size="small"><Statistic title="低于市场价商品数" value={priceChanges.below_market_count as number} /></Card></Col>
                </Row>
                <Table size="small" dataSource={(priceChanges.items as Record<string, unknown>[]) || []} rowKey="xianyu_id" pagination={{ pageSize: 20 }}
                  columns={[
                    { title: '标题', dataIndex: 'title', ellipsis: true },
                    { title: '当前价', dataIndex: 'price', width: 80, render: (v: number) => `¥${v}` },
                    { title: '均价', dataIndex: 'avg_price', width: 80, render: (v: number) => `¥${v}` },
                    { title: '偏离', dataIndex: 'deviation', width: 80, render: (v: number) => <Tag color={v < -30 ? 'green' : 'orange'}>{v}%</Tag> },
                    { title: '卖家', dataIndex: 'seller_name', width: 100, ellipsis: true },
                  ]}
                />
              </Space>
            ) : null,
          },
        ]}
      />
    </Space>
  );
}
