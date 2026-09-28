from unittest.mock import Mock, patch

from docsgpt.vectorstore import base
from docsgpt.vectorstore import embeddings_tasks


def test_embed_texts_does_not_dispatch_back_to_the_worker():
    base.EmbeddingsSingleton._instances = {}
    local = Mock()
    local.embed_documents.return_value = [[0.1, 0.2]]

    with patch.object(base.settings, "EMBEDDINGS_BASE_URL", None):
        with patch.object(base.settings, "EMBEDDINGS_DELEGATE_TO_WORKER", True):
            with patch.object(base, "build_local_embeddings", return_value=local):
                with patch(
                    "docsgpt.celery_init.celery.send_task",
                    side_effect=AssertionError("embedding task was re-dispatched"),
                ):
                    result = embeddings_tasks.embed_texts.run(["hello"], "some/model")

    assert result == [[0.1, 0.2]]
    local.embed_documents.assert_called_once_with(["hello"])
