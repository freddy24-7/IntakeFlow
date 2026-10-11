"""Classification (PRD F2): which kind of document is this?"""

from app.agents.prompts import Prompt
from app.agents.schema import ClassificationAnswer
from app.inference.interfaces import ChatModel, ModelUsage
from app.reading.interfaces import ReadResult

# The type is clear from the first part of a document. This keeps long contracts cheap.
MAX_CHARACTERS = 6000


async def classify(
    model: ChatModel, prompt: Prompt, reading: ReadResult
) -> tuple[ClassificationAnswer, ModelUsage]:
    text = reading.text[:MAX_CHARACTERS]
    user = f"<document_text>\n{text}\n</document_text>"
    result = await model.structured(system=prompt.text, user=user, schema=ClassificationAnswer)
    answer = result.value
    # The schema cannot enforce the range with every model, so it is enforced here.
    confidence = min(1.0, max(0.0, answer.confidence))
    return answer.model_copy(update={"confidence": confidence}), result.usage
