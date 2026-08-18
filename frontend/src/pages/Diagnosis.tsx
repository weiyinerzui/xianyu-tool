import { useState } from 'react';
import { Form, Input, InputNumber, Switch, Button, Card, Alert, Tag, List, Progress, Space, Typography, Row, Col, Statistic } from 'antd';
import { MedicineBoxOutlined } from '@ant-design/icons';
import { diagnose } from '../api';

const { Text } = Typography;

const severityColor: Record<string, string> = {
  critical: 'red', high: 'volcano', medium: 'orange', low: 'blue',
};
const riskColor: Record<string, string> = {
  healthy: 'green', warning: 'orange', danger: 'red',
};

export default function Diagnosis() {
  const [form] = Form.useForm();
  const [result, setResult] = useState<Record<string, unknown> | null>(null);
  const [loading, setLoading] = useState(false);

  const handleDiagnose = async (values: Record<string, unknown>) => {
    setLoading(true);
    try {
      const data = await diagnose(values);
      setResult(data);
    } finally { setLoading(false); }
  };

  const causes = (result?.matched_causes as Record<string, unknown>[]) || [];

  return (
    <Space direction="vertical" style={{ width: '100%' }} size="large">
      <Card title="曝光诊断输入" size="small">
        <Form form={form} layout="inline" onFinish={handleDiagnose}>
          <Row gutter={[12, 12]}>
            <Col span={6}><Form.Item name="title" label="标题"><Input placeholder="商品标题" /></Form.Item></Col>
            <Col span={4}><Form.Item name="price" label="价格"><InputNumber style={{ width: '100%' }} /></Form.Item></Col>
            <Col span={4}><Form.Item name="market_avg_price" label="市场均价"><InputNumber style={{ width: '100%' }} /></Form.Item></Col>
            <Col span={5}><Form.Item name="category" label="当前类目"><Input /></Form.Item></Col>
            <Col span={5}><Form.Item name="recommended_category" label="推荐类目"><Input /></Form.Item></Col>
            <Col span={4}><Form.Item name="image_count" label="图片数"><InputNumber style={{ width: '100%' }} /></Form.Item></Col>
            <Col span={4}><Form.Item name="first_image_ratio" label="首图比例"><Input placeholder="1:1" /></Form.Item></Col>
            <Col span={4}><Form.Item name="desc_length" label="描述字数"><InputNumber style={{ width: '100%' }} /></Form.Item></Col>
            <Col span={4}><Form.Item name="account_health_score" label="闲气值"><InputNumber style={{ width: '100%' }} /></Form.Item></Col>
            <Col span={4}><Form.Item name="edit_count_within_1h" label="1h编辑次数"><InputNumber style={{ width: '100%' }} /></Form.Item></Col>
            <Col span={6}><Form.Item name="price_title_change_within_24h" label="24h降价改标" valuePropName="checked"><Switch /></Form.Item></Col>
            <Col span={6}><Form.Item name="category_mismatch" label="类目错放" valuePropName="checked"><Switch /></Form.Item></Col>
            <Col span={6}><Form.Item name="has_watermark" label="含水印" valuePropName="checked"><Switch /></Form.Item></Col>
            <Col span={6}><Form.Item name="has_violation_record" label="有违规记录" valuePropName="checked"><Switch /></Form.Item></Col>
          </Row>
          <Button type="primary" htmlType="submit" icon={<MedicineBoxOutlined />} loading={loading}>诊断</Button>
        </Form>
      </Card>

      {result && (
        <>
          <Row gutter={16}>
            <Col span={8}>
              <Card size="small">
                <Statistic title="综合健康分" value={result.overall_score as number} suffix="/100"
                  valueStyle={{ color: riskColor[result.risk_level as string] }} />
              </Card>
            </Col>
            <Col span={8}>
              <Card size="small"><Statistic title="风险等级" value={result.risk_level as string} valueStyle={{ color: riskColor[result.risk_level as string] }} /></Card>
            </Col>
            <Col span={8}>
              <Card size="small"><Statistic title="命中归因数" value={causes.length} /></Card>
            </Col>
          </Row>

          {causes.length > 0 && (
            <Card title="嫌疑归因（按概率排序）" size="small">
              <List
                dataSource={causes}
                renderItem={(c: Record<string, unknown>) => (
                  <List.Item>
                    <Space direction="vertical" style={{ width: '100%' }}>
                      <Space>
                        <Tag color={severityColor[c.severity as string]}>{(c.severity as string).toUpperCase()}</Tag>
                        <Text strong>{c.label as string}</Text>
                        <Text type="secondary">概率 {((c.probability as number) * 100).toFixed(0)}%</Text>
                        <Text type="secondary">置信度 {((c.confidence as number) * 100).toFixed(0)}%</Text>
                      </Space>
                      <Text type="secondary">原因：{c.cause as string}</Text>
                      <div>
                        <Text type="secondary">证据：</Text>
                        <ul>{(c.evidence as string[]).map((e, i) => <li key={i}>{e}</li>)}</ul>
                      </div>
                      <div>
                        <Text type="secondary">修复建议：</Text>
                        <ul>{(c.fix as string[]).map((f, i) => <li key={i}>{f}</li>)}</ul>
                      </div>
                      {c.recovery ? <Text type="secondary">恢复周期：{c.recovery as string}</Text> : null}
                    </Space>
                  </List.Item>
                )}
              />
            </Card>
          )}

          {result.suggestions && (
            <Card title="修复建议汇总" size="small">
              <ul>{(result.suggestions as string[]).map((s, i) => <li key={i}>{s}</li>)}</ul>
            </Card>
          )}

          {result.factor_scores && (
            <Card title="因子得分" size="small">
              {Object.entries(result.factor_scores as Record<string, number>).map(([k, v]) => (
                <div key={k} style={{ marginBottom: 8 }}>
                  <Text>{k}</Text>
                  <Progress percent={Math.round(v)} size="small" />
                </div>
              ))}
            </Card>
          )}
        </>
      )}
    </Space>
  );
}
