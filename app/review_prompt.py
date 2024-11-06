from app.models import ResultsOut, ReviewType
import json


class ReviewPrompt:
    @staticmethod
    def handle(results: ResultsOut, review_type: ReviewType):
        prompt = f"""You are an expert in inclusive language.
You are tasked with editing the "previous response" from your previous response.

For each item in the below "issues list", replace the content provided in "issue" within the "previous response" using any of the provided "alternatives".
Pick which ever element in the "alternatives" list fits best in the given context.
Either using the text in "alt" or if "remove" is set to True, consider removing the given "issue" from the text entirely.
If no "alternatives" are provided, try to rephrase the given text portion.

Do not include the "issues list" or a "foreword message" in your response.
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

            if review_type != ReviewType.NO_EXPLANATION:
                change["explanation"] = result.explanation.text

            for alternative in result.alternatives:
                if alternative.remove:
                    change["alternatives"].append({"remove": True})
                else:
                    change["alternatives"].append({"alt": alternative.text})

            changes.append(change)

        while len(json.dumps(changes)) > 1900 - len(prompt):
            changes.pop()

        return prompt + '\nBelow is the "issues list":\n' + json.dumps(changes)
