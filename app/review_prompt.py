from app.models import ResultsOut
import json


class ReviewPrompt:
    @staticmethod
    def handle(results: ResultsOut):
        prompt = f"""You are an expert in inclusive language.
You are tasked with editing the "text you just generated" from your previous response.
Show the before and after the edits.
Explain the changes in the edits using the "explanation" given for each "issue".

For each item in the below "issues list", replace the content provided in "issue" within the "text you just generated" using any of the provided "alternatives".
Pick which ever element in the "alternatives" list fits best in the given context.
Either using the text in "alt" or if "remove" is set to True, consider removing the given "issue" from the text entirely.
If no "alternatives" are provided, try to rephrase the given text portion.
Use content in "explanation" to explain your changes.

Do not include the "issues list" or a "foreword message" in your response.
"""

        changes = []
        for result in results:
            if len(result.alternatives) == 0:
                continue

            change = {
                "issue": result.text,
                "explanation": result.explanation.text,
                "alternatives": [],
            }

            for alternative in result.alternatives:
                if alternative.remove:
                    change["alternatives"].append({"remove": True})
                else:
                    change["alternatives"].append({"alt": alternative.text})

            changes.append(change)

        while len(json.dumps(changes)) > 1900 - len(prompt):
            changes.pop()

        return prompt + '\nBelow is the "issues list":\n' + json.dumps(changes)
