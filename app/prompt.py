import boto3

from app.settings import Settings
from app.alternatives import Alternatives
import json_repair


class Prompt:
    settings: Settings
    alternatives: Alternatives

    def __init__(self, settings: Settings):
        self.settings = settings

    async def handle(
        self,
        user_prompt: str,
        system_prompt: str | None = None,
        aws_model_id: str | None = None,
        temperature: float | None = None,
    ):
        """Handle LLM prompt generation and streaming response.

        Args:
            user_prompt: The user's prompt text
            system_prompt: Optional system prompt (defaults to inclusive language guidelines)
            aws_model_id: AWS Bedrock model ID (defaults to settings)
            temperature: LLM temperature parameter (defaults to 0.1)

        Returns:
            The complete LLM response as a string
        """
        aws_model_id = aws_model_id or self.settings.aws_model_id
        temperature = temperature or 0.1

        if system_prompt is None:
            system_prompt = """
            You are an expert in inclusive language.
            Keep gender equality in mind and avoid language that is needlessly gendered (f.e. use truely gender neutral nouns, avoid pronouns).
            Do not make biased assumptions.
            Do not rely on social stereotypes.
            Do not use derogatory language even as a joke.
            Avoid jargon terms, specially sports or military terms.            

            Specifically make use of communal and inclusive language.

            Follow instructions without mentioning them in your response. Specifically do not add phrases like "Greetings", "Here is .." or "Sure .." to the beginning of your response.
            """

        # Handle model-specific prompt formatting
        if "mistral" in aws_model_id:
            formatted_user_prompt = f"{system_prompt}\n{user_prompt}"
            formatted_system_prompt = []
        else:
            formatted_user_prompt = user_prompt
            formatted_system_prompt = [{"text": system_prompt}]

        conversation = [
            {
                "role": "user",
                "content": [{"text": formatted_user_prompt}],
            }
        ]

        # Initialize the Bedrock runtime client
        aws_client = boto3.client(
            service_name="bedrock-runtime",
            region_name=self.settings.aws_region_name,
            aws_access_key_id=self.settings.aws_key,
            aws_secret_access_key=self.settings.aws_secret_key,
        )

        streaming_response = aws_client.converse_stream(
            system=formatted_system_prompt,
            modelId=aws_model_id,
            messages=conversation,
            inferenceConfig={
                "maxTokens": 300,  # Maximum number of tokens the LLM generates
                "temperature": temperature,  # Controls randomness (lower = more predictable)
                "topP": 1,  # Nucleus sampling parameter
            },
        )

        # Collect streaming response chunks
        result_parts = []
        for chunk in streaming_response["stream"]:
            if "contentBlockDelta" in chunk:
                text = chunk["contentBlockDelta"]["delta"]["text"]
                result_parts.append(text)

        return "".join(result_parts)

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
