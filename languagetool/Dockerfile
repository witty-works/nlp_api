# The deployable LanguageTool: the stock image plus this project's ignore
# lists and config.properties. Do not deploy the stock image instead, and do
# not point LANGUAGETOOL_API at the hosted service - neither carries the
# ignore lists, so both report spelling errors on vocabulary this product uses
# on purpose, and neither applies the disabledRuleIds below, several of which
# are LanguageTool's own gendered-language rules that collide with ours.

# Was hardcoded to 6.2, which is from 2023-12-07. 6.8 is both the newest tag
# the image publishes (2026-06-15, same build as `latest`) and what the test
# suite and compose.yml pin, so that is the default here.
#
# That is a six-release jump (6.3 through 6.8), so it is a behaviour change
# rather than a refresh: LanguageTool adds and retunes rules every release,
# and this project filters its output by rule and category id. Run the suite
# against this image and adjudicate the snapshot diff before enabling it.
ARG LT_VERSION=6.8

FROM erikvl87/languagetool:${LT_VERSION}

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
