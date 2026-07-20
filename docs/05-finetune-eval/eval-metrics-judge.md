# 评估：BLEU / ROUGE / LLM-as-Judge

> 所属模块：05 · 微调与评估 ｜ 学习日期：2026-07-20  
> 实验：`experiments/finetune-eval/finetune_eval_demo.py`（BLEU/ROUGE 排序 + Judge 位置偏差与交换缓解全绿）

## 一句话总结

**字面指标量重合，Judge 量偏好**；前者便宜但虐释义，后者灵活但有位置/长度偏差——评估要「指标 + 盲评协议」一起设计，不能只看一个分。

## 我的理解

```
生成质量怎么量？

  自动字面     BLEU / ROUGE / 精确匹配     快、可复现、偏表面
  语义自动     BERTScore 等               需模型，仍非任务真值
  偏好/综合    LLM-as-Judge / Arena       贴人类，有系统偏差
  业务         引用率 / 工具成功率 / 回归  最贴产品（P1/P3）
```

### BLEU

- 看 **n-gram 精确率**（modified precision）+ **简短惩罚 BP**  
- 强项：翻译等「接近参考译文」  
- 弱项：合理解释换词 → 分低（实验 paraphrase BLEU 0.19 vs good 0.60）

### ROUGE-L

- 看与参考的 **最长公共子序列** → 兼顾准确率/召回（略偏召回）  
- 摘要场景常用；同样偏字面重合  
- 实验：good 0.89 ≫ bad 0.07，paraphrase 介于中间

### LLM-as-Judge

用强模型打分/二选一。灵活，但已知偏差：

| 偏差 | 现象 | 缓解 |
|------|------|------|
| **位置** | 同样内容放 A 更容易赢 | **交换顺序投两票**；不一致则盲评/第三人 |
| **长度** | 更长答案被偏好 | 限长、长度归一、提示「勿因长度加分」 |
| **自我偏好** | 同家族模型偏爱自家文风 | 多 judge 交叉、或人类抽检 |
| **标准漂移** | 提示含糊导致分数不可比 | 固定 rubric、锚点样例 |

实验抓手：

1. 无偏 judge：correct vs wrong → 总选 correct  
2. `prefer_first=10` 模拟位置偏差 → **错误答案放 A 也能赢**  
3. **swap 投票** 后恢复 correct  

## 动手记录

```bash
cd experiments/finetune-eval && python3 finetune_eval_demo.py
# BLEU good=0.60 bad=0.00 | ROUGE good=0.89
# biased A=wrong → A；swap mitigation → ans2=correct
```

## 和 Prompt Evaluation 的关系

评估 **一个 prompt 版本** 时同一套思想：

1. 固定 devset（题 + 参考/rubric）  
2. 字面指标做回归门禁（不降）  
3. Judge / 人工看「任务成功」  
4. 改 prompt = 改版本号，A/B 对比（模块 02 Registry 可挂）

## 踩过的坑

- **只报 BLEU 说模型变强**：可能只是更会抄参考措辞。  
- **Judge 单次单顺序**：位置偏差可翻盘，必须 swap 或随机位。  
- **用被评模型当 judge**：自我偏好；至少换一家或加规则分。

## 面试问答（自测）

- **Q: BLEU/ROUGE 衡量什么？局限？** n-gram / LCS 重合；虐释义与多样正确。  
- **Q: LLM-as-Judge 偏差？** 位置、长度、自我偏好；交换、多 judge、rubric。  
- **Q: INT4 量化代价？** 显存/吞吐换精度与个别任务掉点（与 QLoRA 存基座同一谱系）。

## 参考资料

- BLEU / ROUGE 原始论文；LLM-as-Judge 位置偏差相关工作  
- 实验：`experiments/finetune-eval/finetune_eval_demo.py`
