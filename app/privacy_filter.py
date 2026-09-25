import re
from functools import lru_cache


class PrivacyFilter:
    """Filter URLs, emails, and numbers from text for privacy purposes.

    References:
    - https://github.com/lmeulen/PrivacyFilter
    """

    def __init__(self):
        self.url_re = self.compile_url_regex()

    @staticmethod
    def compile_url_regex():
        """Compile a permissive URL-matching regular expression.

        Reference: https://stackoverflow.com/questions/827557/how-do-you-validate-a-url-with-a-regular-expression-in-python
        """
        ul = "\u00a1-\uffff"  # Unicode letters range (must not be a raw string).

        # IP patterns
        ipv4_re = r"(?:0|25[0-5]|2[0-4]\d|1\d?\d?|[1-9]\d?)(?:\.(?:0|25[0-5]|2[0-4]\d|1\d?\d?|[1-9]\d?)){3}"
        ipv6_re = (
            r"\[?((([0-9A-Fa-f]{1,4}:){7}([0-9A-Fa-f]{1,4}|:))|(([0-9A-Fa-f]{1,4}:){6}(:[0-9A-Fa-f]{1,"
            r"4}|((25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)(\.(25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)){3})|:))|(([0-9A-Fa-f]{"
            r"1,4}:){5}(((:[0-9A-Fa-f]{1,4}){1,2})|:((25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)(\.(25[0-5]|2["
            r"0-4]\d|1\d\d|[1-9]?\d)){3})|:))|(([0-9A-Fa-f]{1,4}:){4}(((:[0-9A-Fa-f]{1,4}){1,"
            r"3})|((:[0-9A-Fa-f]{1,4})?:((25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)(\.(25[0-5]|2[0-4]\d|1\d\d|["
            r"1-9]?\d)){3}))|:))|(([0-9A-Fa-f]{1,4}:){3}(((:[0-9A-Fa-f]{1,4}){1,4})|((:[0-9A-Fa-f]{1,4}){0,"
            r"2}:((25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)(\.(25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)){3}))|:))|((["
            r"0-9A-Fa-f]{1,4}:){2}(((:[0-9A-Fa-f]{1,4}){1,5})|((:[0-9A-Fa-f]{1,4}){0,3}:((25[0-5]|2["
            r"0-4]\d|1\d\d|[1-9]?\d)(\.(25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)){3}))|:))|(([0-9A-Fa-f]{1,4}:){1}(((:["
            r"0-9A-Fa-f]{1,4}){1,6})|((:[0-9A-Fa-f]{1,4}){0,4}:((25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)(\.(25[0-5]|2["
            r"0-4]\d|1\d\d|[1-9]?\d)){3}))|:))|(:(((:[0-9A-Fa-f]{1,4}){1,7})|((:[0-9A-Fa-f]{1,4}){0,"
            r"5}:((25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)(\.(25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)){3}))|:)))(%.+)?\]?"
        )

        # Host patterns
        hostname_re = (
            r"[a-z" + ul + r"0-9](?:[a-z" + ul + r"0-9-]{0,61}[a-z" + ul + r"0-9])?"
        )
        # Max length for domain name labels is 63 characters per RFC 1034 sec. 3.1
        domain_re = r"(?:\.(?!-)[a-z" + ul + r"0-9-]{1,63}(?<!-))*"
        tld_re = (
            r"\."  # dot
            r"(?!-)"  # can't start with a dash
            r"(?:[a-z" + ul + "-]{2,63}"  # domain label
            r"|xn--[a-z0-9]{1,59})"  # or punycode label
            r"(?<!-)"  # can't end with a dash
            r"\.?"  # may have a trailing dot
        )
        host_re = "(" + hostname_re + domain_re + tld_re + "|localhost)"

        return re.compile(
            r"([a-z0-9.+-]*:?//)?"  # scheme is validated separately
            r"(?:[^\s:@/]+(?::[^\s:@/]*)?@)?"  # user:pass authentication
            r"(?:" + ipv4_re + "|" + ipv6_re + "|" + host_re + ")"
            r"(?::\d{2,5})?"  # port
            r"(?:[/?#][^\s]*)?",  # resource path
            re.IGNORECASE,
        )

    def remove_numbers(self, text: str) -> str:
        """Replace all numeric sequences with <NUMBER> placeholder."""
        return re.sub(r"\d+", "<NUMBER>", text)

    def remove_email(self, text: str) -> str:
        """Replace email addresses with <EMAIL> placeholder."""
        return re.sub(
            r"(([a-zA-Z0-9_+]+(?:\.[\w-]+)*)@((?:[\w-]+\.)*\w[\w-]{0,66})\.([a-z]{2,6}(?:\.[a-z]{2})?))"
            "(?![^<]*>)",
            "<EMAIL>",
            text,
        )

    def remove_url(self, text: str) -> str:
        """Replace URLs with <URL> placeholder."""
        return re.sub(self.url_re, "<URL>", text)

    def filter_regular_expressions(self, text: str) -> str:
        """Apply all privacy filters to text."""
        text = self.remove_email(text)
        text = self.remove_url(text)
        text = self.remove_numbers(text)
        return text.strip()

    def clean(self, text: str) -> str:
        """Clean text by applying all privacy filters."""
        return self.filter_regular_expressions(text)

    def clean_dict(self, data: dict) -> dict:
        """Clean all string values in a dictionary recursively."""
        for dict_key in data.keys():
            data[dict_key] = self.clean_var(data[dict_key])
        return data

    def clean_var(self, var):
        """Recursively clean strings in any data structure (str, dict, list)."""
        if isinstance(var, str):
            var = self.clean(var)
        elif isinstance(var, dict):
            var = self.clean_dict(var)
        elif isinstance(var, list):
            var = [self.clean_var(item) for item in var]
        return var


@lru_cache()
def get_privacy_filter():
    """Return a cached PrivacyFilter instance.

    Uses LRU caching to reuse a single instance across calls.
    """
    return PrivacyFilter()
