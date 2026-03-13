# 🚀 AES 作文自动评分系统

基于 `Flask-RESTful + Streamlit + RoBERTa + MLP` 的英文作文自动评分项目。当前仓库已经包含模型推理后端、可视化前端、历史记录持久化、训练数据与 notebook。

## 📌 项目概览

- 后端：提供作文评分、文件评分、历史记录查询、详情查看、删除等 API。
- 前端：提供单篇评分、批量评分、历史记录三块功能。
- 模型：使用 `roberta-base` 提取文本向量，结合 MLP 回归预测分数。
- 存储：使用 SQLite 保存提交记录和评分明细。
- 数据：包含训练数据 `data/training_set_rel3.tsv` 和历史库 `data/history.db`。

## 🗂️ 目录结构

```text
aes/
├─ backend/
│  ├─ app.py                  # Flask-RESTful API 入口
│  ├─ model_service.py        # 模型加载与推理逻辑
│  └─ storage.py              # SQLite 历史记录存储
├─ frontend/
│  └─ streamlit_app.py        # Streamlit 前端
├─ model/
│  ├─ aes.ipynb               # 训练/实验 notebook
│  └─ aes_all.ipynb
├─ data/
│  ├─ training_set_rel3.tsv   # 训练数据
│  ├─ test_batch.csv          # 批量测试样例
│  └─ history.db              # 历史记录数据库
├─ uploads/                   # 上传文件归档目录
├─ best_fold_model.pt         # 当前后端默认加载模型
├─ aes_5fold_ensemble.pt      # 其他训练产物
├─ PROJECT_STATUS.md          # 当前项目进度
├─ SYSTEM_DESIGN.md           # 系统设计文档
└─ REQUIREMENTS_ANALYSIS.md   # 需求分析文档
```

## ✨ 主要功能

### 1. ✍️ 单篇评分

- 选择作文题目 `1..8` 或 `unknown`
- 输入作文文本
- 返回预测分数、文本统计和高频词
- 自动写入历史记录

### 2. 📦 批量评分

- 前端当前支持上传 `csv`
- 后端 API 支持上传 `txt` 和 `csv`
- `csv` 按“无表头、每个单元格都是一篇作文”解析
- 返回每篇作文的编号、预测分数、文本分析和高频词
- 上传原文件会归档到 `uploads/`

### 3. 📚 历史记录

- 支持按编号查询
- 支持按题目筛选
- 支持按类型筛选：`全部 / 单篇 / 文件`
- 支持分页
- 支持查看详情
- 支持删除记录
- 支持导出 CSV

📝 说明：
- 单篇记录详情中的编号直接显示为 `submission_id`
- 多篇记录详情中的编号显示为 `submission_id-row`
- 导出的 CSV 使用 `UTF-8 with BOM`，兼容 Excel 打开中文内容

## 🤖 模型说明

训练逻辑主要在 `model/aes.ipynb` 中，当前推理流程如下：

1. 读取作文文本
2. 使用 `roberta-base` tokenizer 编码
3. 使用 RoBERTa 提取 `last_hidden_state` 的均值向量
4. 使用 MLP 回归预测标准化分数 `scaled_score`
5. 根据 `essay_set` 做反标准化，得到最终整数分
6. 当 `essay_set=unknown` 时，对多个题型分数区间做归一化融合，输出 `0-100`

后端默认加载根目录下的 `best_fold_model.pt`。

## 🧩 环境依赖

🛠️ 安装依赖：

```bash
pip install -r requirements.txt
```

当前依赖文件：

- `flask==3.0.3`
- `flask-restful==0.3.10`
- `streamlit==1.38.0`
- `torch>=2.2.0`
- `transformers>=4.40.0`
- `numpy>=1.26.0`
- `pandas>=2.2.0`
- `requests>=2.32.0`

## ▶️ 启动方式

### 1. 🔧 启动后端

在项目根目录执行：

```bash
python backend/app.py
```

📍 默认地址：

```text
http://127.0.0.1:5000
```

### 2. 🖥️ 启动前端

在项目根目录执行：

```bash
streamlit run frontend/streamlit_app.py
```

📍 默认地址通常为：

```text
http://localhost:8501
```

## 🔌 API 说明

### ❤️ 健康检查

```http
GET /api/health
```

返回模型路径、数据库路径和可用题目集合。

### ✍️ 单篇评分

```http
POST /api/score/text
Content-Type: application/json
```

📝 请求示例：

```json
{
  "essay": "This is my essay.",
  "essay_set": 1
}
```

📝 也支持：

```json
{
  "essay": "This is my essay.",
  "essay_set": "unknown"
}
```

### 📄 文件评分

```http
POST /api/score/file
Content-Type: multipart/form-data
```

🧾 表单字段：

- `file`:  `csv`
- `essay_set`: `1..8` 或 `unknown`

### 📋 历史记录列表

```http
GET /api/history?limit=20&offset=0&essay_set=all&source_type=all
```

🧾 支持参数：

- `limit`
- `offset`
- `essay_set`: `all / 1..8 / unknown`
- `source_type`: `all / text / file`

### 🔍 历史记录详情

```http
GET /api/history/<submission_id>
```

### 🗑️ 删除历史记录

```http
DELETE /api/history/<submission_id>
```

## 🛠️ 当前实现细节

- 前端题目选项当前写在 `frontend/streamlit_app.py` 中，为固定列表。
- 前端批量评分上传控件当前仅开放 `csv`。
- 历史记录导出文件名格式为 `<submission_id>.csv`。
- 导出列包含：`编号`、`预测成绩`、`文本分析`、`高频词`、`文章`。
- 上传文件会保存到 `uploads/时间戳_原文件名`。
