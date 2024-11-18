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
    ):
        if aws_model_id is None:
            aws_model_id = self.settings.aws_model_id

        if system_prompt is None:
            system_prompt = f"""
            You are an expert in inclusive language.
            """

        conversation = []

        if "mistral" in aws_model_id:
            user_prompt = f"{system_prompt}\n{user_prompt}"
            system_prompt = []
        else:
            system_prompt = [{"text": system_prompt}]

        user_prompt = {
            "role": "user",
            "content": [{"text": user_prompt}],
        }

        conversation.append(user_prompt)

        result = ""

        # Initialize the Bedrock runtime client
        aws_client = boto3.client(
            service_name="bedrock-runtime",
            region_name=self.settings.aws_region_name,
            aws_access_key_id=self.settings.aws_key,
            aws_secret_access_key=self.settings.aws_secret_key,
        )

        streaming_response = aws_client.converse_stream(
            system=system_prompt,
            modelId=aws_model_id,
            messages=conversation,
            inferenceConfig={
                # This is the maximum number of tokens that the LLM generates.
                "maxTokens": 300,
                # Temperature is a hyperparameter that controls the randomness of language model output. (lower is more predictable)
                "temperature": 0.1,
                # Top p, also known as nucleus sampling, is another hyperparameter that controls the randomness of language model output.
                "topP": 1,
            },
        )

        for chunk in streaming_response["stream"]:
            if "contentBlockDelta" in chunk:
                text = chunk["contentBlockDelta"]["delta"]["text"]
                result += text

        return result

    def parseJson(self, result: str):
        if "{" in result and "}" in result:
            result = result[result.find("{") : result.rfind("}") + 1]
        elif result == "" or result[0] != '"' or result[-1] != '"':
            return result

        return json_repair.loads(result)
