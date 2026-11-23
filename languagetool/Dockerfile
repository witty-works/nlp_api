# The deployable LanguageTool: the stock image plus this project's ignore
# lists and config.properties. Do not deploy the stock image instead, and do
# not point LANGUAGETOOL_API at the hosted service - neither carries the
# ignore lists, so both report spelling errors on vocabulary this product uses
# on purpose, and neither applies the disabledRuleIds below, several of which
# are LanguageTool's own gendered-language rules that collide with ours.

# The LanguageTool release, pinned here and nowhere else (compose.yml and CI
# build this file), by tag and digest. Dependabot (.github/dependabot.yml)
# proposes a new release or digest as a pull request, whose test run shows how
# the findings change: LanguageTool adds and retunes rules every release, and
# this project filters its output by rule and category id, so adjudicate the
# snapshot diff before merging one.
FROM erikvl87/languagetool:6.8@sha256:ef8fa12cbd485166c9ceeb7139d76d56d07707a624da6bb1fc1fbb5411750527

# https://github.com/Erikvl87/docker-languagetool#improving-the-spell-checker
USER languagetool

COPY en_ignore.txt en_ignore.txt
RUN  (echo; cat en_ignore.txt) >> org/languagetool/resource/en/hunspell/ignore.txt

COPY de_ignore.txt de_ignore.txt
RUN  (echo; cat de_ignore.txt) >> org/languagetool/resource/de/hunspell/ignore.txt

WORKDIR /LanguageTool

# start.sh runs LanguageTool with `--config config.properties` and appends any
# langtool_* environment variables to it, so this file is read and anything
# set through the environment wins over it.
COPY --chown=languagetool config.properties config.properties
