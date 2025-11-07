from app.settings import Settings
from app.models import ResultOut, Language
from app.context import AppContext

from slack_bolt.app.async_app import AsyncApp
from slack_sdk.models.blocks import (
    SectionBlock,
    MarkdownTextObject,
)
from slack_bolt import Respond
from slack_sdk.web.async_client import AsyncWebClient


def get_bolt(settings: Settings, context: AppContext) -> AsyncApp:
    if settings.slack_bot_token and settings.slack_signing_secret:  # pragma: no cover
        bolt = AsyncApp(
            token=settings.slack_bot_token, signing_secret=settings.slack_signing_secret
        )
    else:
        bolt = AsyncApp(
            signing_secret="valid",
            client=AsyncWebClient(
                token="valid_token",
                base_url="http://localhost",
            ),
        )

    # Inject AppContext into Slack Bolt's context for all listeners
    @bolt.middleware
    async def inject_app_context(context_, next):  # type: ignore[no-redef]
        context_["app_context"] = context
        return await next()

    return bolt


async def process_command_witty(
    text: str,
    language: Language,
    limit_reached: bool,
    results: list[ResultOut],
    respond: Respond,
):  # pragma: no cover
    analyzed_text = f"*Analyzed*: {text}"
    if limit_reached:
        analyzed_text += " (text length limit reached)"

    blocks = [
        SectionBlock(
            block_id="text",
            text=MarkdownTextObject(text=analyzed_text),
        ),
        SectionBlock(
            block_id="details",
            text=MarkdownTextObject(
                text=f"*Language*: {language.lang}, *Number of Issues Detected*: {len(results)}"
            ),
        ),
    ]

    if len(results):
        for result_index, result in enumerate(results):
            issue_text = f"#{result_index+1} Matched Text: {result.text} (category {result.category}, proficiency_level {result.proficiency_level})\n"

            if result.explanation.icon:
                issue_text += f"{result.explanation.icon} "

            if result.explanation.url:
                issue_text += f"<{result.explanation.url}|{result.explanation.text}>"
            else:
                issue_text += f"{result.explanation.text}"

            if result.explanation.context:
                issue_text += f" ({result.explanation.context})"

            blocks.append(
                SectionBlock(
                    block_id=f"match{result_index}",
                    text=MarkdownTextObject(text=issue_text),
                )
            )

            alternatives_list = result.alternatives or []
            if alternatives_list:
                alternatives = ""
                for alternative in alternatives_list:
                    if alternative.remove:
                        alternatives += f"\n• ~{alternative.text}~"
                    else:
                        alternatives += f"\n• {alternative.text}"

                    if alternative.context:
                        alternatives += f"- ({alternative.context})"

                blocks.append(
                    SectionBlock(
                        block_id=f"alternatives{result_index}",
                        text=MarkdownTextObject(text=alternatives),
                    )
                )

    await respond(blocks=blocks)
    return None
