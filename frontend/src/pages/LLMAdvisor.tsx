import React, { useEffect, useState } from 'react';
import {
  Card,
  Col,
  Descriptions,
  Divider,
  Form,
  Input,
  Button,
  message,
  Row,
  Space,
  Statistic,
  Tag,
  Typography,
  Alert,
  Spin,
} from 'antd';
import { RobotOutlined, ThunderboltOutlined, FileTextOutlined } from '@ant-design/icons';
import {
  llmStatus,
  llmOptimizeTitle,
  llmGenerateDescription,
} from '../api';

const { TextArea } = Input;
const { Title, Paragraph, Text } = Typography;

interface LLMStatus {
  available: boolean;
  provider: string;
  model: string;
  fallback: string;
  base_url?: string;
}

const LLMAdvisor: React.FC = () => {
  const [status, setStatus] = useState<LLMStatus | null>(null);
  const [statusLoading, setStatusLoading] = useState(true);

  // 标题优化
  const [titleForm] = Form.useForm();
  const [titleLoading, setTitleLoading] = useState(false);
  const [titleResult, setTitleResult] = useState<Record<string, unknown> | null>(null);

  // 描述生成
  const [descForm] = Form.useForm();
  const [descLoading, setDescLoading] = useState(false);
  const [descResult, setDescResult] = useState<Record<string, unknown> | null>(null);

  const fetchStatus = async () => {
    setStatusLoading(true);
    try {
      const data = await llmStatus();
      setStatus(data);
    } catch {
      setStatus(null);
    } finally {
      setStatusLoading(false);
    }
  };

  useEffect(() => {
    fetchStatus();
  }, []);

  const onOptimizeTitle = async (values: {
    title: string;
    core_keyword?: string;
    category?: string;
  }) => {
    setTitleLoading(true);
    setTitleResult(null);
    try {
      const data = await llmOptimizeTitle(
        values.title,
        values.core_keyword || '',
        values.category || '',
      );
      setTitleResult(data);
      message.success('标题优化完成');
    } catch (e) {
      message.error('标题优化失败，请检查后端 LLM 配置');
    } finally {
      setTitleLoading(false);
    }
  };

  const onGenerateDesc = async (values: {
    title: string;
    category?: string;
    key_features?: string;
  }) => {
    setDescLoading(true);
    setDescResult(null);
    try {
      const data = await llmGenerateDescription(
        values.title,
        values.category || '',
        values.key_features || '',
      );
      setDescResult(data);
      message.success('描述生成完成');
    } catch {
      message.error('描述生成失败，请检查后端 LLM 配置');
    } finally {
      setDescLoading(false);
    }
  };

  return (
    <div>
      <Title level={3}>
        <RobotOutlined /> AI 智能助手
      </Title>
      <Paragraph type="secondary">
        基于 LLM 的标题优化与商品描述生成。当 LLM 未配置时自动回退到规则引擎。
      </Paragraph>

      {/* 状态卡片 */}
      <Card style={{ marginBottom: 24 }}>
        <Spin spinning={statusLoading}>
          <Row gutter={16}>
            <Col span={6}>
              <Statistic
                title="LLM 可用性"
                valueRender={() =>
                  status?.available ? (
                    <Tag color="green">可用</Tag>
                  ) : (
                    <Tag color="orange">回退规则引擎</Tag>
                  )
                }
              />
            </Col>
            <Col span={6}>
              <Statistic title="Provider" value={status?.provider || '-'} />
            </Col>
            <Col span={6}>
              <Statistic title="Model" value={status?.model || '-'} />
            </Col>
            <Col span={6}>
              <Statistic title="回退策略" value={status?.fallback || '-'} />
            </Col>
          </Row>
          {!statusLoading && !status?.available && (
            <Alert
              style={{ marginTop: 16 }}
              type="info"
              showIcon
              message="LLM 未配置或不可用"
              description="当前将使用内置规则引擎生成结果。配置环境变量 XIANYU_OPS_LLM_API_KEY / XIANYU_OPS_LLM_BASE_URL / XIANYU_OPS_LLM_MODEL 后可启用 LLM 增强。"
            />
          )}
          <Divider style={{ margin: '12px 0' }} />
          <Button size="small" onClick={fetchStatus}>
            刷新状态
          </Button>
        </Spin>
      </Card>

      <Row gutter={24}>
        {/* 标题优化 */}
        <Col span={12}>
          <Card title={<><ThunderboltOutlined /> 标题优化</>} loading={false}>
            <Form
              form={titleForm}
              layout="vertical"
              onFinish={onOptimizeTitle}
              initialValues={{ core_keyword: '', category: '' }}
            >
              <Form.Item
                name="title"
                label="商品标题"
                rules={[{ required: true, message: '请输入标题' }]}
              >
                <TextArea rows={2} placeholder="粘贴当前商品标题" maxLength={60} showCount />
              </Form.Item>
              <Form.Item name="core_keyword" label="核心关键词（可选）">
                <Input placeholder="如：PS教程" />
              </Form.Item>
              <Form.Item name="category" label="类目（可选）">
                <Input placeholder="如：学习资料" />
              </Form.Item>
              <Form.Item>
                <Button type="primary" htmlType="submit" loading={titleLoading}>
                  优化标题
                </Button>
              </Form.Item>
            </Form>

            {titleResult && (
              <div>
                <Divider />
                <Descriptions column={1} size="small" bordered>
                  <Descriptions.Item label="优化标题">
                    <Text strong>{String(titleResult.optimized_title ?? titleResult.title ?? '-')}</Text>
                  </Descriptions.Item>
                  {titleResult.score !== undefined && (
                    <Descriptions.Item label="评分">
                      {String(titleResult.score)}
                    </Descriptions.Item>
                  )}
                  {titleResult.reason && (
                    <Descriptions.Item label="优化理由">
                      {String(titleResult.reason)}
                    </Descriptions.Item>
                  )}
                  {Array.isArray(titleResult.suggestions) && (
                    <Descriptions.Item label="建议">
                      {(titleResult.suggestions as string[]).map((s, i) => (
                        <Tag key={i}>{s}</Tag>
                      ))}
                    </Descriptions.Item>
                  )}
                </Descriptions>
              </div>
            )}
          </Card>
        </Col>

        {/* 描述生成 */}
        <Col span={12}>
          <Card title={<><FileTextOutlined /> 商品描述生成</>} loading={false}>
            <Form
              form={descForm}
              layout="vertical"
              onFinish={onGenerateDesc}
              initialValues={{ category: '', key_features: '' }}
            >
              <Form.Item
                name="title"
                label="商品标题"
                rules={[{ required: true, message: '请输入标题' }]}
              >
                <Input placeholder="商品标题" />
              </Form.Item>
              <Form.Item name="category" label="类目（可选）">
                <Input placeholder="如：软件教程" />
              </Form.Item>
              <Form.Item name="key_features" label="核心卖点（可选）">
                <TextArea rows={3} placeholder="每行一个卖点，如：&#10;原版安装包&#10;图文教程" />
              </Form.Item>
              <Form.Item>
                <Button type="primary" htmlType="submit" loading={descLoading}>
                  生成描述
                </Button>
              </Form.Item>
            </Form>

            {descResult && (
              <div>
                <Divider />
                <Paragraph>
                  <pre style={{ whiteSpace: 'pre-wrap', margin: 0, background: '#fafafa', padding: 12, borderRadius: 6 }}>
                    {String(descResult.description ?? descResult.text ?? JSON.stringify(descResult, null, 2))}
                  </pre>
                </Paragraph>
              </div>
            )}
          </Card>
        </Col>
      </Row>

      <Card style={{ marginTop: 24 }}>
        <Space direction="vertical" style={{ width: '100%' }}>
          <Text strong>使用说明</Text>
          <Text type="secondary">
            1. 标题优化：输入当前标题，AI 会基于五段式公式（品牌+核心词+属性+场景+长尾）给出优化建议。
          </Text>
          <Text type="secondary">
            2. 描述生成：输入标题和卖点，AI 会生成结构化商品描述，可直接粘贴到闲鱼商品详情。
          </Text>
          <Text type="secondary">
            3. LLM 不可用时自动回退到规则引擎，结果仍可用但创意性较低。
          </Text>
        </Space>
      </Card>
    </div>
  );
};

export default LLMAdvisor;
