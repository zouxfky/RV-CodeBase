# RAG 构造方式 Baseline 设计

## 目标

比较不同 RAG 构造方式对 **RISC-V 指令约束代码生成** 的影响。

任务形式：

```text
RISC-V 指令/Intrinsic 文档
→ 不同 RAG 方法检索相关知识
→ LLM 生成 RISC-V 代码
→ 编译和运行测试
```

除五个 RAG 方法外，实验中需要保留 `No RAG` 作为基础对照。

---

## Baseline 0：No RAG

不提供任何外部 RISC-V 指令文档，只让模型直接生成代码。

作用：

```text
衡量模型原生能力，证明 RAG 数据是否真的有用。
```

---

## Baseline 1：Text RAG

最基础的文本 RAG。把每条 RISC-V 指令或 intrinsic 渲染成文本 chunk，然后做向量检索。

构造方式：

```text
指令文档 → 文本 chunk → embedding → 向量库 → top-k 检索 → LLM
```

适合检索：

```text
指令说明
intrinsic 名称
函数签名
参数说明
使用示例
```

代码/参考：

- RAG 原始论文：https://nlp.cs.ucl.ac.uk/publications/2020-05-retrieval-augmented-generation-for-knowledge-intensive-nlp-tasks/
- RAG 综述：https://arxiv.org/abs/2312.10997
- 可用工具：FAISS、Qdrant、Milvus、pgvector、LlamaIndex、LangChain

预期作用：

```text
降低伪造 intrinsic 的比例，提高函数名和签名命中率。
```

---

## Baseline 2：TreeRAG

层级式 RAG。代表方法是 RAPTOR，通过聚类和递归摘要构建树状索引。

构造方式：

```text
底层指令 chunk
→ 聚类
→ 摘要
→ 再聚类
→ 构建树状索引
→ 检索底层细节 + 高层摘要
```

适合检索：

```text
指令族
相似指令
组合指令
高层类别说明
```

代码/参考：

- RAPTOR 论文：https://huggingface.co/papers/2401.18059
- RAPTOR 代码：https://github.com/parthsarthi03/raptor

预期作用：

```text
比 Text RAG 更适合多指令组合和指令族级别的问题。
```

---

## Baseline 3：GraphRAG

图结构 RAG。把指令文档转成实体-关系图，再基于图进行检索。

构造方式：

```text
指令文档
→ 抽取实体和关系
→ 构建图
→ 社区发现/图摘要
→ 图检索
→ LLM
```

可建模实体：

```text
Instruction
Intrinsic
Operation
Type
Parameter
Category
Constraint
Example
```

可建模关系：

```text
HAS_INTRINSIC
HAS_PARAMETER
RETURNS
IMPLEMENTS
BELONGS_TO
HAS_CONSTRAINT
SIMILAR_TO
USED_WITH
```

代码/参考：

- Microsoft GraphRAG：https://github.com/microsoft/graphrag
- GraphRAG 论文：https://www.microsoft.com/en-us/research/publication/from-local-to-global-a-graph-rag-approach-to-query-focused-summarization/
- GraphRAG 综述：https://arxiv.org/abs/2408.08921
- Neo4j GraphRAG：https://github.com/neo4j/neo4j-graphrag-python
- LightRAG：https://github.com/HKUDS/LightRAG

预期作用：

```text
适合指令关系建模、相似指令消歧、约束检索和指令族分析。
```

---

## Baseline 4：HippoRAG

基于图记忆和 Personalized PageRank 的 RAG。它从查询相关节点出发，在知识图中扩散，检索多跳相关证据。

构造方式：

```text
指令文档
→ 抽取 triples / 构建知识图
→ 查询映射到 seed nodes
→ Personalized PageRank 扩散
→ 多跳证据检索
→ LLM
```

适合检索：

```text
隐含相关指令
load/store/vsetvl 相关证据
多跳依赖
组合代码所需上下文
```

代码/参考：

- HippoRAG 论文：https://huggingface.co/papers/2405.14831
- HippoRAG 代码：https://github.com/OSU-NLP-Group/HippoRAG

预期作用：

```text
适合多跳检索和组合指令生成，例如从 vadd 关联到 load、store、vsetvl。
```

---

## Baseline 5：MemoRAG

记忆增强 RAG。先用 memory model 对整个语料形成全局记忆，再根据用户问题生成检索线索，用线索指导检索。

构造方式：

```text
指令文档
→ memory model 建立全局记忆
→ 用户问题
→ 生成 retrieval clues
→ 检索相关证据
→ LLM
```

适合检索：

```text
用户没有显式提到、但生成代码必须需要的知识。
```

例子：

```text
用户只说：生成 int32 数组加法的 RVV 代码

MemoRAG 应该推断还需要：
- <riscv_vector.h>
- vsetvl
- vector load
- vector add
- vector store
- vl 参数
```

代码/参考：

- MemoRAG 论文：https://huggingface.co/papers/2409.05591
- MemoRAG 代码：https://github.com/qhjqhj00/MemoRAG

预期作用：

```text
适合需求模糊、隐含依赖多的代码生成任务。
```

---

# 实验设计

## 第一类任务：问答

比较：

```text
No RAG
Text RAG
TreeRAG
GraphRAG
HippoRAG
MemoRAG
```

任务：

```text
给定 RVV 相关问题，模型根据检索到的文档内容回答。
```

Questions 构成：

- 单指令综合问答：250 条。给定某个 RVV 指令，要求综合回答它的用途、核心语义、汇编格式和常见 intrinsic。
- 事实判断与纠错问题：300 条。给出一个关于 RVV 指令功能、格式、操作数、结果位置或 intrinsic 的陈述，要求判断是否正确；如果错误，需要给出正确说法。
- 指令族问答：120 条。围绕一个 section / 指令族提问，询问该族包含哪些指令、共同功能是什么、各指令分别用于什么场景。
- 对比类问题：150 条。比较两个或多个相近指令，询问功能差异、操作数差异、数据类型差异或使用场景差异。
- 反向查询类问题：130 条。给出功能描述、汇编格式、intrinsic 名称或语义片段，要求反推出对应 RVV 指令。
- 场景应用类问题：50 条。给出保守的使用需求，询问应该选择哪类 RVV 指令或哪条具体指令。

总计：

```text
1000 条
```

指标：

- Recall：检索召回率，方法返回的 top-k `retrieved_evidence` 覆盖标准 `gold_evidence` 的比例。
- 指令准确率：回答中的 RVV 汇编指令名是否正确，例如 `vredsum.vs`、`vcpop.m`。
- 操作数准确率：回答中的汇编操作数及顺序是否正确，例如 `vd, vs2, vs1, vm`。
- 内置函数准确率：回答中的 RVV C intrinsic / `__riscv_*` 内置函数是否正确。
- Faithfulness：回答中的结构化 claim 是否能被 `retrieved_evidence` 支持。分别计算指令名、汇编格式、内置函数三类支持率，再对非空子分数做等权平均。

目的：

```text
比较不同 RAG 构造方式对 RVV 指令知识问答准确性的影响。
```

## 第二类任务：代码优化

比较：

```text
No RAG
Text RAG
TreeRAG
GraphRAG
HippoRAG
MemoRAG
```

任务：

```text
给定 benchmark 原始代码，模型生成 RVV 优化版本，并通过编译、正确性和性能测试评价优化效果。
```

可用性指标：

- 首轮编译通过率：模型第一次生成的代码能否直接编译通过。
- 最终编译通过率：允许修复后，最终代码能否编译通过。
- 最终正确率：最终代码能否通过 reference 正确性测试。
- RVV 使用率：最终正确代码中，实际使用 RVV 指令的比例。

性能指标：

- 首轮平均加速比：首轮生成且正确的代码相对原始 benchmark 的平均加速比。
- 最终平均加速比：最终正确代码相对原始 benchmark 的平均加速比。
- 最大加速比：所有最终正确样本中的最大加速比。
- 加速成功率：最终正确样本中，速度快于原始 benchmark 的比例。

说明：

```text
运行时间取多次运行的中位数，平均加速比使用几何平均。性能指标只在结果正确的样本上统计。
```
