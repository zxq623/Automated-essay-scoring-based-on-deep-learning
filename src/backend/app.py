from __future__ import annotations

import io
import re
from collections import Counter
from datetime import datetime
from pathlib import Path

import pandas as pd
from flask import Flask, request
from flask_restful import Api, Resource

from model_service import EssayScoringService
from storage import HistoryStore


BASE_DIR = Path(__file__).resolve().parents[1]
DEFAULT_MODEL_PATH = BASE_DIR / "best_fold_model.pt"
UPLOAD_DIR = BASE_DIR / "uploads"
DB_PATH = BASE_DIR / "data" / "history.db"


def text_analysis(text: str) -> dict:
    clean = text.strip()
    words = re.findall(r"\w+", clean.lower())
    sentences = [s for s in re.split(r"[.!?。！？]+", clean) if s.strip()]
    paragraphs = [p for p in clean.splitlines() if p.strip()]

    word_count = len(words)
    sentence_count = max(len(sentences), 1)
    avg_sentence_length = word_count / sentence_count if word_count else 0
    lexical_diversity = len(set(words)) / word_count if word_count else 0

    stopwords = {
        "the", "a", "an", "and", "or", "but", "is", "are", "to", "of", "in", "on",
        "for", "with", "that", "this", "it", "as", "at", "by", "be", "from", "was", "were",
    }
    top_words = [
        {"word": w, "count": c}
        for w, c in Counter([w for w in words if w not in stopwords]).most_common(10)
    ]

    return {
        "characters": len(clean),
        "words": word_count,
        "sentences": len(sentences),
        "paragraphs": len(paragraphs),
        "avg_sentence_length": round(avg_sentence_length, 2),
        "lexical_diversity": round(lexical_diversity, 4),
        "top_words": top_words,
    }


def create_app() -> Flask:
    app = Flask(__name__)
    api = Api(app)

    service = EssayScoringService(DEFAULT_MODEL_PATH)
    store = HistoryStore(DB_PATH)
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

    class HealthResource(Resource):
        def get(self):
            return {
                "status": "ok",
                "model_path": str(DEFAULT_MODEL_PATH),
                "db_path": str(DB_PATH),
                "essay_sets": service.available_essay_sets(),
            }, 200

    class ScoreTextResource(Resource):
        def post(self):
            payload = request.get_json(silent=True) or {}
            essay = str(payload.get("essay", "")).strip()
            essay_set_raw = payload.get("essay_set", 1)
            essay_set_value = str(essay_set_raw).strip().lower()

            if not essay:
                return {"error": "'essay' is required"}, 400

            try:
                if essay_set_value == "unknown":
                    unknown_pred = service.score_unknown([essay])[0]
                    pred_score = int(unknown_pred["score"])
                    pred_scaled = float(unknown_pred["scaled_score"])
                    pred_set = "unknown"
                    fusion_sets = None
                    default_essay_set = None
                else:
                    essay_set = int(essay_set_raw)
                    pred = service.score([essay], [essay_set])[0]
                    pred_score = pred.score
                    pred_scaled = pred.scaled_score
                    pred_set = pred.essay_set
                    fusion_sets = None
                    default_essay_set = essay_set

                analysis = text_analysis(essay)
                saved_records = [
                    {
                        "row": 1,
                        "essay_set": -1 if pred_set == "unknown" else int(pred_set),
                        "score": pred_score,
                        "scaled_score": pred_scaled,
                        "essay_text": essay,
                        "preview": essay[:120],
                        "analysis": analysis,
                    }
                ]
                submission_id = store.save_submission(
                    source_type="text",
                    filename=None,
                    default_essay_set=default_essay_set,
                    records=saved_records,
                )
            except Exception as exc:
                return {"error": str(exc)}, 400

            response = {
                "submission_id": submission_id,
                "score": pred_score,
                "scaled_score": pred_scaled,
                "essay_set": pred_set,
                "analysis": analysis,
            }
            return response, 200

    class ScoreFileResource(Resource):
        def post(self):
            if "file" not in request.files:
                return {"error": "Upload file is required in form-data key 'file'"}, 400

            uploaded = request.files["file"]
            default_essay_set_raw = request.form.get("essay_set", "1")
            is_unknown = str(default_essay_set_raw).strip().lower() == "unknown"
            default_essay_set = None if is_unknown else int(default_essay_set_raw)

            original_filename = uploaded.filename or "upload_file"
            filename = original_filename.lower()
            content = uploaded.read()

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            archive_name = f"{timestamp}_{Path(original_filename).name}"
            archive_path = UPLOAD_DIR / archive_name
            archive_path.write_bytes(content)

            try:
                if filename.endswith(".csv"):
                    try:
                        df = pd.read_csv(io.BytesIO(content), header=None, sep=None, engine="python")
                    except Exception:
                        df = pd.read_csv(io.BytesIO(content), header=None, sep=",")
                    values = df.fillna("").astype(str).values.ravel().tolist()
                    essays = [v.strip() for v in values if str(v).strip()]
                    if not essays:
                        return {"error": "CSV has no essay content"}, 400
                    rows = [
                        {"essay": essay, "essay_set": "unknown" if is_unknown else default_essay_set}
                        for essay in essays
                    ]
                else:
                    return {"error": "Only .csv is supported"}, 400

                essays = [str(item["essay"]).strip() for item in rows]

                if not essays or any(not e for e in essays):
                    return {"error": "Found empty essay content"}, 400

                scored = []
                for item in rows:
                    essay_set_item = str(item["essay_set"]).strip().lower()
                    if essay_set_item == "unknown":
                        pred = service.score_unknown([str(item["essay"])])[0]
                        scored.append(pred)
                    else:
                        pred = service.score([str(item["essay"])], [int(item["essay_set"])])[0]
                        scored.append(
                            {
                                "essay_set": pred.essay_set,
                                "score": pred.score,
                                "scaled_score": pred.scaled_score,
                            }
                        )

                results = []
                persisted = []
                for idx, (item, pred) in enumerate(zip(rows, scored), start=1):
                    essay_text = str(item["essay"])
                    analysis = text_analysis(essay_text)
                    essay_set_value = pred["essay_set"] if isinstance(pred, dict) else pred.essay_set
                    score_value = pred["score"] if isinstance(pred, dict) else pred.score
                    scaled_value = pred["scaled_score"] if isinstance(pred, dict) else pred.scaled_score
                    result_item = {
                        "row": idx,
                        "essay_set": essay_set_value,
                        "score": score_value,
                        "scaled_score": scaled_value,
                        "analysis": analysis,
                        "preview": essay_text[:120],
                    }
                    results.append(result_item)
                    persisted.append(
                        {
                            **result_item,
                            "essay_text": essay_text,
                            "essay_set": -1 if str(essay_set_value).lower() == "unknown" else int(essay_set_value),
                        }
                    )

                submission_id = store.save_submission(
                    source_type="file",
                    filename=archive_name,
                    default_essay_set=default_essay_set,
                    records=persisted,
                )

                return {
                    "submission_id": submission_id,
                    "archived_file": str(archive_path),
                    "count": len(results),
                    "results": results,
                }, 200
            except Exception as exc:
                return {"error": str(exc)}, 400

    class HistoryListResource(Resource):
        def get(self):
            limit = int(request.args.get("limit", 20))
            offset = int(request.args.get("offset", 0))
            essay_set_raw = request.args.get("essay_set", "all")
            source_type_raw = request.args.get("source_type", "all")
            limit = min(max(limit, 1), 200)
            offset = max(offset, 0)

            essay_set_value = str(essay_set_raw).strip().lower()
            if essay_set_value == "all":
                filter_value: int | None | str = "all"
            elif essay_set_value == "unknown":
                filter_value = None
            else:
                filter_value = int(essay_set_value)

            source_type = str(source_type_raw).strip().lower()
            if source_type not in {"all", "text", "file"}:
                return {"error": "source_type must be one of: all, text, file"}, 400

            items = store.get_submissions(
                limit=limit,
                offset=offset,
                default_essay_set=filter_value,
                source_type=source_type,
            )
            total = store.count_submissions(default_essay_set=filter_value, source_type=source_type)
            return {
                "limit": limit,
                "offset": offset,
                "count": len(items),
                "total": total,
                "items": items,
            }, 200

    class HistoryDetailResource(Resource):
        def get(self, submission_id: int):
            data = store.get_submission_detail(submission_id)
            if data is None:
                return {"error": f"submission_id={submission_id} not found"}, 404
            return data, 200

        def delete(self, submission_id: int):
            deleted = store.delete_submission(submission_id)
            if not deleted:
                return {"error": f"submission_id={submission_id} not found"}, 404
            return {"submission_id": submission_id, "deleted": True}, 200

    api.add_resource(HealthResource, "/api/health")
    api.add_resource(ScoreTextResource, "/api/score/text")
    api.add_resource(ScoreFileResource, "/api/score/file")
    api.add_resource(HistoryListResource, "/api/history")
    api.add_resource(HistoryDetailResource, "/api/history/<int:submission_id>")

    return app


if __name__ == "__main__":
    app = create_app()
    app.run(host="0.0.0.0", port=5000, debug=False)
