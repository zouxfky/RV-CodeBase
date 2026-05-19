QA_METRICS = (
    "faithfulness",
    "accuracy",
    "precision",
    "f1",
)


REQUIRED_QUESTION_FIELDS = ("id", "question", "answer_key")
REQUIRED_ANSWER_KEY_FIELDS = ("gold_evidence", "formats", "intrinsics")
REQUIRED_PREDICTION_FIELDS = ("id", "method", "answer")


def validate_qa_questions(questions):
    seen_ids = set()
    for row in questions:
        question_id = require_string(row, "id", "question")
        if question_id in seen_ids:
            raise ValueError(f"duplicate question id: {question_id}")
        seen_ids.add(question_id)

        for field in REQUIRED_QUESTION_FIELDS:
            if field not in row:
                raise ValueError(f"question {question_id}: missing field {field}")

        answer_key = row.get("answer_key")
        if not isinstance(answer_key, dict):
            raise ValueError(f"question {question_id}: answer_key must be an object")

        for field in REQUIRED_ANSWER_KEY_FIELDS:
            if field not in answer_key:
                raise ValueError(f"question {question_id}: missing answer_key.{field}")

        require_string_list(answer_key, "gold_evidence", f"question {question_id}")
        require_string_list(answer_key, "formats", f"question {question_id}")
        require_string_list(answer_key, "intrinsics", f"question {question_id}")


def validate_qa_predictions(predictions):
    seen_ids = set()
    for row in predictions:
        prediction_id = require_string(row, "id", "prediction")
        if prediction_id in seen_ids:
            raise ValueError(f"duplicate prediction id: {prediction_id}")
        seen_ids.add(prediction_id)

        for field in REQUIRED_PREDICTION_FIELDS:
            if field not in row:
                raise ValueError(f"prediction {prediction_id}: missing field {field}")

        require_string(row, "method", f"prediction {prediction_id}")
        require_string(row, "answer", f"prediction {prediction_id}")

        if "retrieved_evidence" in row:
            require_string_list(row, "retrieved_evidence", f"prediction {prediction_id}")


def require_string(row, field, owner):
    value = row.get(field)
    if not isinstance(value, str) or not value:
        raise ValueError(f"{owner}: {field} must be a non-empty string")
    return value


def require_string_list(row, field, owner):
    value = row.get(field)
    if not isinstance(value, list):
        raise ValueError(f"{owner}: {field} must be a list")
    for index, item in enumerate(value):
        if not isinstance(item, str) or not item:
            raise ValueError(f"{owner}: {field}[{index}] must be a non-empty string")
    return value


def predictions_by_id(questions, predictions):
    prediction_by_id = {row["id"]: row for row in predictions}
    missing = [row["id"] for row in questions if row["id"] not in prediction_by_id]
    if missing:
        raise ValueError(f"missing predictions for ids: {', '.join(missing)}")
    return prediction_by_id
