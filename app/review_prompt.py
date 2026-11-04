from app.models import ResultsOut
import json


class ReviewPrompt:
    @staticmethod
    def handle(
        results: ResultsOut,
        previous_response: str,
        min_changes: int = 0,
    ) -> str | None:
        """The reask: a message that quotes the model's answer and asks it to
        apply Witty's alternatives to what was flagged, and to rephrase what
        Witty has no alternative for, with the explanation as the reason. None
        where no more than `min_changes` findings have alternatives to offer."""
        prompt = (
            'You are an expert in inclusive language. You are tasked with editing the "previous response".'
            + "\n"
        )

        prompt += 'The "previous response" is the following JSON string: ' + json.dumps(
            previous_response, ensure_ascii=False
        )

        prompt += """For each item in the below "issues list", replace the content provided in "issue" within the "previous response" using any of the provided "alternatives".
Pick which ever element in the "alternatives" list fits best in the given context.
Either using the text in "alt" or if "remove" is set to True, consider removing the given "issue" from the text entirely.
If no "alternatives" are provided, try to rephrase the given text portion.

Do not include the "issues list" in your response.
"""

        prompt += "Only respond with the edited version, so not provide a before/after. Do not explain the changes in the edits."

        changes = []
        rephrase = []
        for result in results:
            if not result.alternatives:
                if result.explanation and result.explanation.text:
                    rephrase.append(
                        {
                            "issue": result.text,
                            "alternatives": [],
                            "explanation": result.explanation.text,
                        }
                    )
                continue

            change = {
                "issue": result.text,
                "alternatives": [],
            }

            for alternative in result.alternatives:
                if alternative.remove:
                    change["alternatives"].append({"remove": True})
                else:
                    change["alternatives"].append({"alt": alternative.text})

            changes.append(change)

        if len(changes) <= min_changes:
            return None

        return (
            prompt
            + '\nBelow is the "issues list":\n'
            + json.dumps(changes + rephrase, ensure_ascii=False)
        )
