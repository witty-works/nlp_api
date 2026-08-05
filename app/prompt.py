import litellm

from app.settings import Settings
from app.alternatives import Alternatives
import json_repair

# Providers differ in which parameters they accept, and a request that names one
# they do not is an error rather than a warning. Dropping the unsupported ones is
# what lets LLM_MODEL be swapped between providers without touching this file.
litellm.drop_params = True
# Nothing about a check leaves this process except the request to the model.
litellm.telemetry = False
litellm.suppress_debug_info = True


class Prompt:
    settings: Settings
    alternatives: Alternatives

    def __init__(self, settings: Settings):
        self.settings = settings

    def _credentials(self, model: str) -> dict:
        """Provider credentials, keyed off the provider prefix in the model id.

        Bedrock signs with a key pair rather than a bearer token, and passing
        empty strings would break a deployment relying on an instance role, so
        the AWS settings are only forwarded when they are actually set.
        """
        if model.startswith("bedrock/"):
            if not self.settings.aws_key:
                return {"aws_region_name": self.settings.aws_region_name or None}

            return {
                "aws_region_name": self.settings.aws_region_name or None,
                "aws_access_key_id": self.settings.aws_key,
                "aws_secret_access_key": self.settings.aws_secret_key,
            }

        return {
            "api_key": self.settings.llm_api_key or None,
            "api_base": self.settings.llm_api_base or None,
        }

    async def handle(
        self,
        user_prompt: str,
        system_prompt: str | None = None,
        model: str | None = None,
        temperature: float | None = None,
    ):
        """Handle LLM prompt generation and response.

        Args:
            user_prompt: The user's prompt text
            system_prompt: Optional system prompt (defaults to inclusive language guidelines)
            model: LiteLLM model identifier, e.g. `openai/gpt-4o` (defaults to settings)
            temperature: LLM temperature parameter (defaults to 0.1)

        Returns:
            The complete LLM response as a string
        """
        model = self.settings.resolve_llm_model(model)
        temperature = temperature or 0.1

        if system_prompt is None:
            system_prompt = """
            You are an expert in inclusive language.
            Keep gender equality in mind and avoid language that is needlessly gendered (f.e. use truly gender neutral nouns, avoid pronouns).
            Do not make biased assumptions.
            Do not rely on social stereotypes.
            Do not use derogatory language even as a joke.
            Avoid jargon terms, specially sports or military terms.            

            Specifically make use of communal and inclusive language.

            Follow instructions without mentioning them in your response. Specifically do not add phrases like "Greetings", "Here is .." or "Sure .." to the beginning of your response.
            """

        # A model that has no system role of its own — Bedrock's Mistral ones,
        # among others — gets the system prompt folded into the message by
        # LiteLLM, so it no longer has to be special-cased here.
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        response = await litellm.acompletion(
            model=model,
            messages=messages,
            max_tokens=300,  # Maximum number of tokens the LLM generates
            temperature=temperature,  # Controls randomness (lower = more predictable)
            top_p=1,  # Nucleus sampling parameter
            **self._credentials(model),
        )

        return response.choices[0].message.content or ""

    def parse_json(self, result: str):
        """Parse and repair potentially malformed JSON from LLM responses.

        Handles common issues:
        - Unicode escape sequences
        - Extra text before/after JSON
        - Malformed JSON structure

        Args:
            result: Raw string output from LLM

        Returns:
            Parsed JSON object or original string if not valid JSON
        """
        if not result:
            return result

        # Handle unicode escape sequences
        if "\\u00" in result:
            result = result.encode().decode("unicode-escape")

        # Extract JSON from text if present
        if "{" in result and "}" in result:
            start = result.find("{")
            end = result.rfind("}") + 1
            result = result[start:end]
        elif not result.startswith('"') or not result.endswith('"'):
            return result

        return json_repair.loads(result)
