
type FeedbackTone = 'success' | 'info' | 'warning' | 'error'

export type ToastNotice = { message: string; tone: FeedbackTone }

export const feedbackToneFor = (message: string): FeedbackTone => {
  if (/(失败|错误|不一致|无法|不能|不可|拒绝|损坏|异常|无效|超时|故障|未通过|未找到|没有.+权限|不支持|回滚|failed|error|invalid|mismatch|forbidden|unauthorized|not found|conflict)/i.test(message)) return 'error'
  if (/(警告|超过阈值|超限|已暂停|安全停止|已停止|已删除|已停用|取消|放弃|待连接|等待|请至少|请选择|只有.+权限|后续步骤|未生成|未应用|未完成|未确认|延后)/.test(message)) return 'warning'
  if (/(成功|完成|通过|正常|在线|就绪|已保存|已创建|已建立|已连接|已开始|已继续|已添加|已更新|已确认|已记录|已锁定|已发布|已绑定|已应用|已恢复|已导出|已生成|已复制|已清空|已标记|已暂存|已提交|已收尾)/.test(message)) return 'success'
  return 'info'
}
