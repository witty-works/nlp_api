from app.models import ResultsOut, ReviewType
import json


class ReviewPrompt:
    @staticmethod
    def handle(
        results: ResultsOut,
        review_type: ReviewType,
        previous_prompt: str | None = None,
        max_prompt_length: int | None = None,
        min_changes: int | None = 0,
    ) -> str | None:
        prompt = (
            'You are an expert in inclusive language. You are tasked with editing the "previous response".'
            + "\n"
        )

        if review_type != ReviewType.INCLUDE_PREVIOUS:
            prompt += 'The "previous response" is the response you returned from the previous prompt send just before this prompt.'
        else:
            prompt += (
                'The "previous response" is the following JSON string: '
                + json.dumps(previous_prompt)
            )

        prompt += """For each item in the below "issues list", replace the content provided in "issue" within the "previous response" using any of the provided "alternatives".
Pick which ever element in the "alternatives" list fits best in the given context.
Either using the text in "alt" or if "remove" is set to True, consider removing the given "issue" from the text entirely.
If no "alternatives" are provided, try to rephrase the given text portion.

Do not include the "issues list" in your response.
"""

        if review_type == ReviewType.EXPLAIN_EDITS:
            prompt += 'Show the before and after the edits. Explain the changes in the edits using the content in "explanation" given for each "issue".'
        else:
            prompt += "Only respond with the edited version, so not provide a before/after. Do not explain the changes in the edits."

            if review_type == ReviewType.USE_EXPLANATION:
                prompt += (
                    ' Use the "explanation" only to determine which "alt" to pick.'
                )

        changes = []
        for result in results:
            if len(result.alternatives) == 0:
                continue

            change = {
                "issue": result.text,
                "alternatives": [],
            }

            if review_type in [ReviewType.EXPLAIN_EDITS, ReviewType.USE_EXPLANATION]:
                change["explanation"] = result.explanation.text

            for alternative in result.alternatives:
                if alternative.remove:
                    change["alternatives"].append({"remove": True})
                else:
                    change["alternatives"].append({"alt": alternative.text})

            changes.append(change)

        if max_prompt_length is not None:
            while len(json.dumps(changes)) > max_prompt_length - len(prompt):
                changes.pop()

        if len(changes) <= min_changes:
            return None

        return prompt + '\nBelow is the "issues list":\n' + json.dumps(changes)
