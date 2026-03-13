from __future__ import annotations

import io
import json
import pandas as pd
import requests
import streamlit as st

API_BASE = "http://127.0.0.1:5000"
ESSAY_SET_MAX_SCORE = {
    "1": 12,
    "2": 6,
    "3": 3,
    "4": 3,
    "5": 4,
    "6": 4,
    "7": 30,
    "8": 60,
}
st.set_page_config(
    page_title="作文自动评分系统",
    page_icon="🚀",
    layout="wide",
    initial_sidebar_state="expanded",
    menu_items={
        "Get help": None,
        "Report a bug": None,
        "About": None,
    },
)


def call_health() -> dict:
    resp = requests.get(f"{API_BASE}/api/health", timeout=20)
    resp.raise_for_status()
    return resp.json()


def call_score_text(essay: str, essay_set: int | str) -> dict:
    resp = requests.post(
        f"{API_BASE}/api/score/text",
        json={"essay": essay, "essay_set": essay_set},
        timeout=120,
    )
    resp.raise_for_status()
    return resp.json()


def call_score_file(uploaded_file, essay_set: int | str) -> dict:
    files = {"file": (uploaded_file.name, uploaded_file.getvalue(), uploaded_file.type)}
    data = {"essay_set": essay_set}
    resp = requests.post(f"{API_BASE}/api/score/file", files=files, data=data, timeout=240)
    resp.raise_for_status()
    return resp.json()


def extract_csv_essays(uploaded_file) -> list[str]:
    content = uploaded_file.getvalue()
    try:
        df = pd.read_csv(io.BytesIO(content), header=None, sep=None, engine="python")
    except Exception:
        df = pd.read_csv(io.BytesIO(content), header=None, sep=",")
    values = df.fillna("").astype(str).values.ravel().tolist()
    return [v.strip() for v in values if str(v).strip()]


def call_history(limit: int = 20, offset: int = 0, essay_set: str = "all", source_type: str = "all") -> dict:
    resp = requests.get(
        f"{API_BASE}/api/history",
        params={"limit": limit, "offset": offset, "essay_set": essay_set, "source_type": source_type},
        timeout=20,
    )
    resp.raise_for_status()
    return resp.json()


def call_history_detail(submission_id: int) -> dict:
    resp = requests.get(f"{API_BASE}/api/history/{submission_id}", timeout=20)
    resp.raise_for_status()
    return resp.json()


def call_history_delete(submission_id: int) -> dict:
    resp = requests.delete(f"{API_BASE}/api/history/{submission_id}", timeout=20)
    resp.raise_for_status()
    return resp.json()


def build_export_csv(submission_id: int) -> bytes:
    detail = call_history_detail(submission_id)
    records = detail.get("records", [])
    rows: list[dict[str, str]] = []
    for idx, record in enumerate(records, start=1):
        essay_set_raw = record.get("essay_set", -1)
        essay_set_key = "unknown" if int(essay_set_raw) < 0 else str(int(essay_set_raw))
        score = record.get("score", 0)
        if essay_set_key == "unknown":
            score_text = f"{int(score)}/100"
        else:
            max_score = ESSAY_SET_MAX_SCORE.get(essay_set_key)
            score_text = f"{int(score)}/{max_score}" if max_score is not None else str(int(score))

        analysis = record.get("analysis", {})
        analysis_payload = {k: v for k, v in analysis.items() if k != "top_words"}
        row_id = f"{submission_id}-{idx}" if len(records) > 1 else str(submission_id)
        rows.append(
            {
                # Use Excel text formula form to avoid auto-converting values like 1-2 or 10/12 into dates.
                "编号": f'="{row_id}"',
                "预测成绩": f'="{score_text}"',
                "文本分析": json.dumps(analysis_payload, ensure_ascii=False),
                "高频词": json.dumps(analysis.get("top_words", []), ensure_ascii=False),
                "文章": record.get("essay_text", ""),
            }
        )

    df = pd.DataFrame(rows, columns=["编号", "预测成绩", "文本分析", "高频词", "文章"])
    return df.to_csv(index=False).encode("utf-8-sig")


@st.dialog("确认删除")
def show_delete_confirm_dialog(submission_id: int) -> None:
    confirm_col, cancel_col = st.columns(2)
    with confirm_col:
        if st.button("确认", key=f"dialog_confirm_delete_{submission_id}", type="secondary", use_container_width=True):
            try:
                call_history_delete(submission_id)
                st.session_state["history_delete_confirm_id"] = None
                if st.session_state.get("history_selected_submission_id") == submission_id:
                    st.session_state["history_selected_submission_id"] = None
                st.rerun()
            except Exception as exc:
                st.error(f"删除失败: {exc}")
    with cancel_col:
        if st.button("取消", key=f"dialog_cancel_delete_{submission_id}", type="primary", use_container_width=True):
            st.session_state["history_delete_confirm_id"] = None
            st.rerun()


st.markdown(
    """
    <style>
    [data-testid="stToolbar"],
    [data-testid="stToolbarActions"],
    [data-testid="stDeployButton"],
    [data-testid="stSidebarCollapseButton"] {
        display: none !important;
    }
    #MainMenu {
        display: none !important;
    }
    section[data-testid="stSidebar"] [data-testid="stRadio"] {
        gap: 0.35rem;
    }
    .block-container {
        padding-top: 2.5rem !important;
    }
    section[data-testid="stSidebar"] [data-testid="stRadio"] label p {
        margin: 0;
        font-size: 1.02rem;
        line-height: 1.3;
    }
    section[data-testid="stSidebar"] [data-testid="stRadio"] input[type="radio"] { display: none !important; }
    section[data-testid="stSidebar"] [data-testid="stRadio"] label > div:first-child { display: none !important; }
    section[data-testid="stSidebar"] [data-testid="stRadio"] label {
        width: calc(100% + 1.2rem);
        margin-left: -0.6rem;
        margin-right: -0.6rem;
        padding: 0.7rem 0.9rem;
        border-radius: 0.5rem;
    }
    section[data-testid="stSidebar"] [data-testid="stRadio"] label:has(input[type="radio"]:checked) {
        background: rgba(29, 78, 216, 0.18);
        color: #1e3a8a;
        font-weight: 600;
    }
    [data-testid="stTable"] table th,
    [data-testid="stTable"] table td {
        text-align: center !important;
    }
    div.stButton > button[kind="primary"] {
        background-color: #3b82f6 !important;
        border-color: #3b82f6 !important;
        color: #ffffff !important;
    }
    div.stButton > button[kind="primary"]:hover {
        background-color: #2563eb !important;
        border-color: #2563eb !important;
        color: #ffffff !important;
    }
    div.stButton > button[kind="primary"]:focus {
        box-shadow: 0 0 0 0.2rem rgba(59, 130, 246, 0.25) !important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

mode = st.sidebar.radio(
    "导航菜单",
    ["🚀 单篇评分", "📦 批量评分", "📓 历史记录"],
    index=0,
    label_visibility="collapsed",
)


def load_prompt_options() -> list[tuple[str, str]]:
    return [
        ("1 Effects of technology on people's lives(argument)", "1"),
        ("2 Should students be required to wear uniforms(argument)", "2"),
        ("3 Explain what makes a good teacher(explanation)", "3"),
        ("4 Are celebrities good role models for young people(explanation)", "4"),
        ("5 Do video games help or harm teenagers(explanation)", "5"),
        ("6 Should cell phones be allowed in school(explanation)", "6"),
        ("7 Write about a memorable event in your life(narrative)", "7"),
        ("8 Write about a birthday you will never forget(narrative)", "8"),
        ("unknown", "unknown"),
    ]


prompt_options = load_prompt_options()

if "single_essay_error" not in st.session_state:
    st.session_state["single_essay_error"] = False

if mode == "🚀 单篇评分":
    col_left, col_right = st.columns([1, 1])
    with col_left:
        st.markdown("**<span style='font-size:1.08rem;'>作文题目</span>**", unsafe_allow_html=True)
        selected_prompt = st.selectbox(
            "单篇评分题目选择",
            options=prompt_options,
            index=0,
            format_func=lambda item: item[0],
            label_visibility="collapsed",
        )
        st.markdown("**<span style='font-size:1.08rem;'>输入作文</span>**", unsafe_allow_html=True)
        essay_text = st.text_area(
            "单篇作文文本输入",
            height=360,
            key="single_essay_text",
            label_visibility="collapsed",
        )
        if essay_text.strip():
            st.session_state["single_essay_error"] = False
        submit = st.button("开始评分", type="primary", use_container_width=True)

    if submit:
        if not essay_text.strip():
            st.session_state["single_essay_error"] = True
            with col_left:
                st.warning("请输入作文内容")
        else:
            st.session_state["single_essay_error"] = False
            try:
                essay_set_value = selected_prompt[1]
                essay_set_payload = essay_set_value if essay_set_value == "unknown" else int(essay_set_value)
                result = call_score_text(essay_text, essay_set_payload)
                with col_right:
                    essay_set_key = str(result.get("essay_set", essay_set_value))
                    if essay_set_key == "unknown":
                        score_text = f"{int(result['score'])}/100"
                    else:
                        max_score = ESSAY_SET_MAX_SCORE.get(essay_set_key)
                        score_text = (
                            f"{int(result['score'])}/{max_score}"
                            if max_score is not None
                            else str(int(result["score"]))
                        )
                    st.subheader(f"编号: {result['submission_id']}")
                    st.subheader(f"预测分数: {score_text}")

                    analysis = result["analysis"]
                    st.subheader("文本统计")
                    stats_df = pd.DataFrame(
                        [
                            {"指标": "字符数", "值": f"{int(analysis['characters'])}"},
                            {"指标": "词数", "值": f"{int(analysis['words'])}"},
                            {"指标": "句子数", "值": f"{int(analysis['sentences'])}"},
                            {"指标": "段落数", "值": f"{int(analysis['paragraphs'])}"},
                            {"指标": "平均句长", "值": f"{analysis['avg_sentence_length']:.2f}"},
                            {"指标": "词汇丰富度", "值": f"{analysis['lexical_diversity']:.4f}"},
                        ]
                    )
                    st.table(stats_df)

                    top_df = pd.DataFrame(analysis["top_words"])
                    if not top_df.empty:
                        st.subheader("高频词")
                        st.bar_chart(top_df.set_index("word")["count"], use_container_width=True, height=220)
            except Exception as exc:
                st.error(f"评分失败: {exc}")

elif mode == "📦 批量评分":
    batch_left, batch_right = st.columns([1, 1])
    with batch_left:
        st.markdown("**<span style='font-size:1.08rem;'>作文题目</span>**", unsafe_allow_html=True)
        selected_prompt = st.selectbox(
            "批量评分题目选择",
            options=prompt_options,
            index=0,
            format_func=lambda item: item[0],
            label_visibility="collapsed",
            key="batch_prompt_select",
        )
        st.markdown("**<span style='font-size:1.08rem;'>上传文件</span>**", unsafe_allow_html=True)
        upload = st.file_uploader(
            "批量评分文件上传",
            type=["csv"],
            accept_multiple_files=False,
            label_visibility="collapsed",
        )
        if upload is not None:
            try:
                essays = extract_csv_essays(upload)
                if essays:
                    st.markdown("**<span style='font-size:1.08rem;'>CSV 内容</span>**", unsafe_allow_html=True)
                    st.text_area(
                        "CSV 内容预览",
                        value="\n\n".join(essays),
                        height=360,
                        disabled=True,
                        label_visibility="collapsed",
                        key="batch_csv_preview",
                    )
            except Exception as exc:
                st.warning(f"无法解析 CSV: {exc}")
        start_batch = st.button("开始评分", type="primary", use_container_width=True)

    with batch_right:
        if start_batch:
            if upload is None:
                st.warning("请先上传 CSV 文件")
            else:
                try:
                    essay_set_value = selected_prompt[1]
                    essay_set_payload = essay_set_value if essay_set_value == "unknown" else int(essay_set_value)
                    result = call_score_file(upload, essay_set_payload)
                    submission_id = result.get("submission_id", "-")
                    st.subheader(f"编号: {submission_id}")
                    for idx, item in enumerate(result.get("results", []), start=1):
                        essay_set_key = str(item.get("essay_set", essay_set_value))
                        if essay_set_key == "unknown":
                            score_text = f"{int(item.get('score', 0))}/100"
                        else:
                            max_score = ESSAY_SET_MAX_SCORE.get(essay_set_key)
                            if max_score is not None:
                                score_text = f"{int(item.get('score', 0))}/{max_score}"
                            else:
                                score_text = str(int(item.get("score", 0)))
                        st.subheader(f"编号: {submission_id}-{idx}")
                        st.subheader(f"预测分数: {score_text}")

                        analysis = item.get("analysis", {})
                        st.subheader("文本分析")
                        stats_df = pd.DataFrame(
                            [
                                {"指标": "字符数", "值": f"{int(analysis.get('characters', 0))}"},
                                {"指标": "词数", "值": f"{int(analysis.get('words', 0))}"},
                                {"指标": "句子数", "值": f"{int(analysis.get('sentences', 0))}"},
                                {"指标": "段落数", "值": f"{int(analysis.get('paragraphs', 0))}"},
                                {"指标": "平均句长", "值": f"{float(analysis.get('avg_sentence_length', 0)):.2f}"},
                                {"指标": "词汇丰富度", "值": f"{float(analysis.get('lexical_diversity', 0)):.4f}"},
                            ]
                        )
                        st.table(stats_df)

                        top_df = pd.DataFrame(analysis.get("top_words", []))
                        if not top_df.empty and "word" in top_df.columns and "count" in top_df.columns:
                            st.subheader("高频词")
                            st.bar_chart(
                                top_df.set_index("word")["count"],
                                use_container_width=True,
                                height=220,
                            )
                        st.markdown("<br><br>", unsafe_allow_html=True)
                except Exception as exc:
                    st.error(f"批量评分失败: {exc}")

else:
    HISTORY_PAGE_SIZE = 20
    st.markdown(
        """
        <style>
        /* 历史记录页按钮按类型单独定义：secondary=红 */
        div.stButton > button[kind="secondary"] {
            background-color: #ef4444 !important;
            border-color: #ef4444 !important;
            color: #ffffff !important;
        }
        div.stButton > button[kind="secondary"]:hover {
            background-color: #dc2626 !important;
            border-color: #dc2626 !important;
            color: #ffffff !important;
        }
        div.stButton > button[kind="tertiary"] {
            background-color: rgba(59, 130, 246, 0.18) !important;
            border: 1px solid rgba(59, 130, 246, 0.35) !important;
            color: #1e3a8a !important;
        }
        div.stButton > button[kind="tertiary"]:hover {
            background-color: rgba(59, 130, 246, 0.28) !important;
            border-color: rgba(37, 99, 235, 0.45) !important;
            color: #1e3a8a !important;
        }
        div[data-testid="stDownloadButton"] > button {
            background-color: #22c55e !important;
            border-color: #22c55e !important;
            color: #ffffff !important;
        }
        div[data-testid="stDownloadButton"] > button:hover {
            background-color: #16a34a !important;
            border-color: #16a34a !important;
            color: #ffffff !important;
        }
        div[data-testid="stDownloadButton"] > button:focus {
            box-shadow: 0 0 0 0.2rem rgba(34, 197, 94, 0.25) !important;
        }
        div[data-testid="stTextInput"] > div {
            min-height: 2.6rem;
        }
        div[data-testid="stTextInput"] input {
            height: 2.6rem;
            line-height: 2.6rem;
            padding-top: 0;
            padding-bottom: 0;
            padding-left: 0.75rem;
            padding-right: 0.75rem;
            text-align: left;
        }
        div[data-baseweb="select"] > div {
            min-height: 2.6rem;
            padding-left: 0.75rem;
            padding-right: 0.75rem;
            align-items: center;
        }
        div[data-baseweb="select"] > div > div {
            min-height: 2.6rem;
            display: flex;
            align-items: center;
            justify-content: flex-start;
            text-align: left;
        }
        div[data-baseweb="select"] span,
        div[data-baseweb="select"] p,
        div[data-baseweb="select"] input {
            text-align: left !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    if "history_page" not in st.session_state:
        st.session_state["history_page"] = 0
    if "history_selected_submission_id" not in st.session_state:
        st.session_state["history_selected_submission_id"] = None
    if "history_filter_essay_set" not in st.session_state:
        st.session_state["history_filter_essay_set"] = "all"
    if "history_filter_type" not in st.session_state:
        st.session_state["history_filter_type"] = "all"
    if "history_filter_id" not in st.session_state:
        st.session_state["history_filter_id"] = ""
    if "history_delete_confirm_id" not in st.session_state:
        st.session_state["history_delete_confirm_id"] = None
    if st.session_state["history_delete_confirm_id"] is not None:
        show_delete_confirm_dialog(int(st.session_state["history_delete_confirm_id"]))

    prompt_filter_options = [("全部题目", "all")] + prompt_options
    prompt_filter_values = [value for _, value in prompt_filter_options]
    prompt_label_map = {value: label for label, value in prompt_filter_options}
    type_filter_options = [("全部类型", "all"), ("单篇", "text"), ("文件", "file")]
    type_filter_values = [value for _, value in type_filter_options]
    type_label_map = {value: label for label, value in type_filter_options}
    selected_id = st.session_state.get("history_selected_submission_id")
    if not selected_id:
        id_input_col, filter_select_col, type_select_col, query_btn_col, _ = st.columns([0.6, 1.8, 0.8, 0.4, 3.4])
        with id_input_col:
            query_id_input = st.text_input(
                "历史记录编号查询",
                value=st.session_state["history_filter_id"],
                placeholder="🔍 查询编号",
                label_visibility="collapsed",
            )
        with filter_select_col:
            selected_prompt_filter = st.selectbox(
                "历史记录题目筛选",
                options=prompt_filter_values,
                index=prompt_filter_values.index(st.session_state["history_filter_essay_set"]),
                format_func=lambda item: prompt_label_map[item],
                key="history_prompt_filter_input",
                label_visibility="collapsed",
            )
        with type_select_col:
            selected_type_filter = st.selectbox(
                "历史记录类型筛选",
                options=type_filter_values,
                index=type_filter_values.index(st.session_state["history_filter_type"]),
                format_func=lambda item: type_label_map[item],
                key="history_type_filter_input",
                label_visibility="collapsed",
            )
        with query_btn_col:
            if st.button("查询", key="history_query_btn", type="primary", use_container_width=True):
                st.session_state["history_filter_id"] = query_id_input.strip()
                st.session_state["history_filter_essay_set"] = selected_prompt_filter
                st.session_state["history_filter_type"] = selected_type_filter
                st.session_state["history_page"] = 0
                st.session_state["history_selected_submission_id"] = None
                st.rerun()

    filter_id = st.session_state["history_filter_id"].strip()
    filter_value = st.session_state["history_filter_essay_set"]
    filter_type = st.session_state["history_filter_type"]

    offset = st.session_state["history_page"] * HISTORY_PAGE_SIZE
    try:
        if filter_id:
            detail = call_history_detail(int(filter_id))
            history = {"items": [detail], "total": 1}
        else:
            history = call_history(
                limit=HISTORY_PAGE_SIZE,
                offset=offset,
                essay_set=filter_value,
                source_type=filter_type,
            )
    except Exception as exc:
        st.error(f"历史记录加载失败: {exc}")
        history = {"items": [], "total": 0}

    items = history.get("items", [])
    total_items = int(history.get("total", len(items)))
    total_pages = max(1, (total_items + HISTORY_PAGE_SIZE - 1) // HISTORY_PAGE_SIZE)
    if st.session_state["history_page"] >= total_pages:
        st.session_state["history_page"] = total_pages - 1
        st.rerun()
    prompt_lookup = {value: label for label, value in prompt_options}

    if selected_id:
        if st.button("返回记录表", key="history_back_btn", type="primary"):
            st.session_state["history_selected_submission_id"] = None
            st.rerun()

        st.subheader(f"历史记录 - 编号 {selected_id}")
        try:
            detail = call_history_detail(int(selected_id))
            records = detail.get("records", [])
            if not records:
                st.warning("该提交下没有记录")
            else:
                selected_record = records[0]

                essay_set_raw = selected_record.get("essay_set", -1)
                essay_set_key = "unknown" if int(essay_set_raw) < 0 else str(int(essay_set_raw))

                detail_left, detail_right = st.columns([1, 1])
                with detail_left:
                    st.markdown("**<span style='font-size:1.08rem;'>作文题目</span>**", unsafe_allow_html=True)
                    st.selectbox(
                        "历史记录题目查看",
                        options=prompt_options,
                        index=next((i for i, opt in enumerate(prompt_options) if opt[1] == essay_set_key), 0),
                        format_func=lambda item: item[0],
                        disabled=True,
                        key=f"history_prompt_readonly_{selected_id}_{selected_record['row']}",
                        label_visibility="collapsed",
                    )
                    st.markdown("**<span style='font-size:1.08rem;'>作文文本</span>**", unsafe_allow_html=True)
                    essays_text = "\n\n".join([r.get("essay_text", "") for r in records])
                    st.text_area(
                        "历史记录作文文本",
                        value=essays_text,
                        height=360,
                        disabled=True,
                        key=f"history_essay_readonly_{selected_id}",
                        label_visibility="collapsed",
                    )

                with detail_right:
                    for idx, record in enumerate(records, start=1):
                        essay_set_raw = record.get("essay_set", -1)
                        essay_set_key = "unknown" if int(essay_set_raw) < 0 else str(int(essay_set_raw))
                        score = record.get("score", 0)
                        display_record_id = str(selected_id) if len(records) == 1 else f"{selected_id}-{idx}"
                        if essay_set_key == "unknown":
                            score_text = f"{int(score)}/100"
                        else:
                            max_score = ESSAY_SET_MAX_SCORE.get(essay_set_key)
                            score_text = f"{int(score)}/{max_score}" if max_score is not None else str(int(score))

                        st.subheader(f"编号: {display_record_id}")
                        st.subheader(f"预测分数: {score_text}")

                        analysis = record.get("analysis", {})
                        st.subheader("文本分析")
                        stats_df = pd.DataFrame(
                            [
                                {"指标": "字符数", "值": f"{int(analysis.get('characters', 0))}"},
                                {"指标": "词数", "值": f"{int(analysis.get('words', 0))}"},
                                {"指标": "句子数", "值": f"{int(analysis.get('sentences', 0))}"},
                                {"指标": "段落数", "值": f"{int(analysis.get('paragraphs', 0))}"},
                                {"指标": "平均句长", "值": f"{float(analysis.get('avg_sentence_length', 0)):.2f}"},
                                {"指标": "词汇丰富度", "值": f"{float(analysis.get('lexical_diversity', 0)):.4f}"},
                            ]
                        )
                        st.table(stats_df)

                        top_df = pd.DataFrame(analysis.get("top_words", []))
                        if not top_df.empty and "word" in top_df.columns and "count" in top_df.columns:
                            st.subheader("高频词")
                            st.bar_chart(top_df.set_index("word")["count"], use_container_width=True, height=220)
                        st.markdown("<br><br>", unsafe_allow_html=True)
        except Exception as exc:
            st.error(f"读取详情失败: {exc}")
    else:
        st.markdown("<div style='height:0.65rem;'></div>", unsafe_allow_html=True)
        if not items:
            st.info("当前筛选条件下暂无记录")
        else:
            col_ratio = [0.35, 0.7, 0.8, 2.5, 0.7, 1.1, 1.6]
            header_cols = st.columns(col_ratio)
            header_cols[0].markdown("<div style='text-align:center; font-weight:600;'>序号</div>", unsafe_allow_html=True)
            header_cols[1].markdown("<div style='text-align:center; font-weight:600;'>编号</div>", unsafe_allow_html=True)
            header_cols[2].markdown("<div style='text-align:center; font-weight:600;'>作文类型</div>", unsafe_allow_html=True)
            header_cols[3].markdown("<div style='text-align:center; font-weight:600;'>作文题目</div>", unsafe_allow_html=True)
            header_cols[4].markdown("<div style='text-align:center; font-weight:600;'>数量</div>", unsafe_allow_html=True)
            header_cols[5].markdown("<div style='text-align:center; font-weight:600;'>创建时间</div>", unsafe_allow_html=True)
            header_cols[6].markdown("<div style='text-align:center; font-weight:600;'>操作</div>", unsafe_allow_html=True)
            st.markdown("<div style='height:0.32rem;'></div>", unsafe_allow_html=True)

            source_map = {"text": "单篇", "file": "文件"}
            for idx, item in enumerate(items, start=1):
                sid = int(item["id"])
                display_index = offset + idx
                display_id = sid
                prompt_value = item.get("default_essay_set")
                prompt_key = "unknown" if prompt_value is None else str(prompt_value)
                prompt_text = prompt_lookup.get(prompt_key, prompt_key)

                row_cols = st.columns(col_ratio)
                row_cols[0].markdown(f"<div style='text-align:center;'>{display_index}</div>", unsafe_allow_html=True)
                row_cols[1].markdown(f"<div style='text-align:center;'>{display_id}</div>", unsafe_allow_html=True)
                row_cols[2].markdown(
                    f"<div style='text-align:center;'>{source_map.get(item.get('source_type'), item.get('source_type', '-'))}</div>",
                    unsafe_allow_html=True,
                )
                row_cols[3].markdown(f"<div style='text-align:center;'>{prompt_text}</div>", unsafe_allow_html=True)
                row_cols[4].markdown(f"<div style='text-align:center;'>{item.get('item_count', 0)}</div>", unsafe_allow_html=True)
                row_cols[5].markdown(f"<div style='text-align:center;'>{item.get('created_at', '-')}</div>", unsafe_allow_html=True)
                action_cols = row_cols[6].columns([1, 1, 1], gap="small")
                if action_cols[0].button("查看", key=f"view_detail_{sid}", type="primary", use_container_width=True):
                    st.session_state["history_delete_confirm_id"] = None
                    st.session_state["history_selected_submission_id"] = sid
                    st.rerun()
                export_csv = build_export_csv(sid)
                action_cols[1].download_button(
                    "导出",
                    data=export_csv,
                    file_name=f"{sid}.csv",
                    mime="text/csv",
                    use_container_width=True,
                    key=f"export_detail_{sid}",
                )
                if action_cols[2].button("删除", key=f"delete_detail_{sid}", type="secondary", use_container_width=True):
                    st.session_state["history_delete_confirm_id"] = sid
                    st.rerun()

            st.markdown("<div style='height:0.75rem;'></div>", unsafe_allow_html=True)
            pager_wrap = st.columns([4.0, 2.4])
            with pager_wrap[1]:
                pager_cols = st.columns([1, 1, 1, 1.15], gap="small")
                with pager_cols[0]:
                    if st.button("上一页", key="history_prev_btn", type="tertiary", disabled=st.session_state["history_page"] <= 0, use_container_width=True):
                        st.session_state["history_page"] = max(st.session_state["history_page"] - 1, 0)
                        st.session_state["history_selected_submission_id"] = None
                        st.rerun()
                with pager_cols[1]:
                    st.markdown(
                        f"<div style='text-align:center; font-size:1.08rem; font-weight:600; margin-top:0.45rem;'>第 {st.session_state['history_page'] + 1} 页</div>",
                        unsafe_allow_html=True,
                    )
                with pager_cols[2]:
                    if st.button(
                        "下一页",
                        key="history_next_btn",
                        type="tertiary",
                        disabled=st.session_state["history_page"] >= (total_pages - 1),
                        use_container_width=True,
                    ):
                        st.session_state["history_page"] += 1
                        st.session_state["history_selected_submission_id"] = None
                        st.rerun()
                with pager_cols[3]:
                    st.markdown(
                        f"<div style='text-align:center; font-size:1.08rem; font-weight:600; margin-top:0.45rem;'>共 {total_pages} 页</div>",
                        unsafe_allow_html=True,
                    )
